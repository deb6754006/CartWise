import { useCallback, useEffect, useRef, useState } from 'react';

import { api } from '../api/client';
import type { components } from '../api/schema';

export type Club = components['schemas']['ClubOut'];
export type ClubsData = {
  clubs: Club[];
  /** Only ids of clubs that still exist. A stale mark is neither shown nor sent again. */
  clubIds: string[];
};
export type ClubsStatus = 'loading' | 'error' | 'ready';

export const CLUBS_TIMEOUT_MS = 15_000;

/** The API client has no timeout of its own: an unanswered request is aborted, and rejects. */
async function withTimeout<T>(request: (signal: AbortSignal) => Promise<T>): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), CLUBS_TIMEOUT_MS);
  try {
    return await request(controller.signal);
  } finally {
    clearTimeout(timer);
  }
}

// The save in progress. It outlives the screen (leaving mid-save must not lose the last
// change), and a load waits for it, so whoever opens next reads what was just saved.
// It never rejects.
let activeSave: Promise<void> | null = null;

/** The available clubs and the marked ones. Rejects when either request fails. */
export async function loadClubs(): Promise<ClubsData> {
  await activeSave;
  const [clubs, mine] = await withTimeout((signal) =>
    Promise.all([api.GET('/v1/clubs', { signal }), api.GET('/v1/me/clubs', { signal })]),
  );
  if (!clubs.data || !mine.data) throw new Error('clubs_load_failed');
  const known = new Set(clubs.data.map((club) => club.id));
  return { clubs: clubs.data, clubIds: mine.data.club_ids.filter((id) => known.has(id)) };
}

function sameSet(a: ReadonlySet<string>, b: ReadonlySet<string>): boolean {
  return a.size === b.size && [...a].every((id) => b.has(id));
}

/**
 * The clubs screen's state. A toggle shows at once and saves the whole set. At most one
 * request runs at a time; when it ends, the latest state is sent if it differs. If a save
 * fails, the switches go back to the last saved state and saveFailed is set.
 */
export function useClubs() {
  const [status, setStatus] = useState<ClubsStatus>('loading');
  const [clubs, setClubs] = useState<Club[]>([]);
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [saveFailed, setSaveFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  const desired = useRef<ReadonlySet<string>>(new Set());
  const saved = useRef<ReadonlySet<string>>(new Set());
  const saving = useRef(false);

  useEffect(() => {
    let current = true;
    loadClubs().then(
      (data) => {
        if (!current) return;
        const ids = new Set(data.clubIds);
        desired.current = ids;
        saved.current = ids;
        setClubs(data.clubs);
        setSelected(ids);
        setStatus('ready');
      },
      () => {
        if (current) setStatus('error');
      },
    );
    return () => {
      current = false;
    };
  }, [attempt]);

  const reload = useCallback(() => {
    setStatus('loading');
    setAttempt((n) => n + 1);
  }, []);

  const persist = useCallback(async () => {
    saving.current = true;
    try {
      for (;;) {
        const sending = desired.current;
        const { data } = await withTimeout((signal) =>
          api.PUT('/v1/me/clubs', { body: { club_ids: [...sending] }, signal }),
        );
        if (!data) throw new Error('clubs_save_failed');
        saved.current = sending;
        if (sameSet(desired.current, sending)) return;
      }
    } catch {
      desired.current = saved.current;
      setSelected(saved.current);
      setSaveFailed(true);
    } finally {
      saving.current = false;
    }
  }, []);

  const toggle = useCallback(
    (clubId: string) => {
      const next = new Set(desired.current);
      if (!next.delete(clubId)) next.add(clubId);
      desired.current = next;
      setSelected(next);
      setSaveFailed(false);
      if (saving.current) return; // the running save sends the latest state when it ends
      const save = persist().finally(() => {
        if (activeSave === save) activeSave = null;
      });
      activeSave = save;
    },
    [persist],
  );

  return { status, clubs, selected, saveFailed, toggle, reload };
}
