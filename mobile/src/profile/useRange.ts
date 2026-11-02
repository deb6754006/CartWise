import { useCallback, useEffect, useState } from 'react';

import { api } from '../api/client';
import type { components } from '../api/schema';
import { createSelectionSaver, loadAfterSave, useSavedSelection } from './savedSelection';

export type Range = components['schemas']['PrefsOut'];
export type TravelMode = Range['default_mode'];
export type TravelMinutes = Range['default_minutes'];
export type RangeStatus = 'loading' | 'error' | 'ready';

// Replaced by what the server answers before anything is shown: it is the server that decides
// what a user who saved no range gets.
const NOT_LOADED: Range = { default_mode: 'car', default_minutes: 15 };

function sameRange(a: Range, b: Range): boolean {
  return a.default_mode === b.default_mode && a.default_minutes === b.default_minutes;
}

const saver = createSelectionSaver<Range>(async (range, signal) => {
  const { data } = await api.PUT('/v1/me/prefs', { body: range, signal });
  if (!data) throw new Error('range_save_failed');
}, sameRange);

/** The saved default range, or the system's. Rejects when the request fails. */
export async function loadRange(): Promise<Range> {
  const { data } = await loadAfterSave(saver, (signal) => api.GET('/v1/me/prefs', { signal }));
  if (!data) throw new Error('range_load_failed');
  return data;
}

/** The default range screen's state. See useSavedSelection for how a change is saved. */
export function useRange() {
  const [status, setStatus] = useState<RangeStatus>('loading');
  const [attempt, setAttempt] = useState(0);
  const { value: range, saveFailed, reset, change } = useSavedSelection(saver, NOT_LOADED);

  useEffect(() => {
    let current = true;
    loadRange().then(
      (loaded) => {
        if (!current) return;
        reset(loaded);
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

  const setMode = useCallback(
    (mode: TravelMode) => {
      change((current) =>
        current.default_mode === mode ? current : { ...current, default_mode: mode },
      );
    },
    [change],
  );

  const setMinutes = useCallback(
    (minutes: TravelMinutes) => {
      change((current) =>
        current.default_minutes === minutes ? current : { ...current, default_minutes: minutes },
      );
    },
    [change],
  );

  return { status, range, saveFailed, reload, setMode, setMinutes };
}
