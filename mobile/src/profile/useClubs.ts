import { useCallback, useEffect, useState } from 'react';

import { api } from '../api/client';
import type { components } from '../api/schema';
import {
  createSelectionSaver,
  loadAfterSave,
  REQUEST_TIMEOUT_MS,
  useSavedSelection,
} from './savedSelection';

export type Club = components['schemas']['ClubOut'];
export type ClubsData = {
  clubs: Club[];
  /** Only ids of clubs that still exist. A stale mark is neither shown nor sent again. */
  clubIds: string[];
};
export type ClubsStatus = 'loading' | 'error' | 'ready';

export const CLUBS_TIMEOUT_MS = REQUEST_TIMEOUT_MS;

const NOTHING_SELECTED: ReadonlySet<string> = new Set();

function sameSet(a: ReadonlySet<string>, b: ReadonlySet<string>): boolean {
  return a.size === b.size && [...a].every((id) => b.has(id));
}

const saver = createSelectionSaver<ReadonlySet<string>>(async (clubIds, signal) => {
  const { data } = await api.PUT('/v1/me/clubs', { body: { club_ids: [...clubIds] }, signal });
  if (!data) throw new Error('clubs_save_failed');
}, sameSet);

/** The available clubs and the marked ones. Rejects when either request fails. */
export async function loadClubs(): Promise<ClubsData> {
  const [clubs, mine] = await loadAfterSave(saver, (signal) =>
    Promise.all([api.GET('/v1/clubs', { signal }), api.GET('/v1/me/clubs', { signal })]),
  );
  if (!clubs.data || !mine.data) throw new Error('clubs_load_failed');
  const known = new Set(clubs.data.map((club) => club.id));
  return { clubs: clubs.data, clubIds: mine.data.club_ids.filter((id) => known.has(id)) };
}

/** The clubs screen's state. See useSavedSelection for how a toggle is saved. */
export function useClubs() {
  const [status, setStatus] = useState<ClubsStatus>('loading');
  const [clubs, setClubs] = useState<Club[]>([]);
  const [attempt, setAttempt] = useState(0);
  const { value: selected, saveFailed, reset, change } = useSavedSelection(saver, NOTHING_SELECTED);

  useEffect(() => {
    let current = true;
    loadClubs().then(
      (data) => {
        if (!current) return;
        reset(new Set(data.clubIds));
        setClubs(data.clubs);
        setStatus('ready');
      },
      () => {
        if (current) setStatus('error');
      },
    );
    return () => {
      current = false;
    };
  }, [attempt, reset]);

  const reload = useCallback(() => {
    setStatus('loading');
    setAttempt((n) => n + 1);
  }, []);

  const toggle = useCallback(
    (clubId: string) => {
      change((current) => {
        const next = new Set(current);
        if (!next.delete(clubId)) next.add(clubId);
        return next;
      });
    },
    [change],
  );

  return { status, clubs, selected, saveFailed, toggle, reload };
}
