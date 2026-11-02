import { useCallback, useRef, useState } from 'react';

export const REQUEST_TIMEOUT_MS = 15_000;

/** The API client has no timeout of its own: an unanswered request is aborted, and rejects. */
export async function withTimeout<T>(request: (signal: AbortSignal) => Promise<T>): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    return await request(controller.signal);
  } finally {
    clearTimeout(timer);
  }
}

/** How one kind of selection is saved, and the save of it now in progress. */
export type SelectionSaver<T> = {
  /** Saves the whole selection. Rejects when it was not saved. */
  send: (value: T, signal: AbortSignal) => Promise<void>;
  same: (a: T, b: T) => boolean;
  // It outlives the screen (leaving mid-save must not lose the last change), and a load waits
  // for it, so whoever opens next reads what was just saved. It never rejects.
  activeSave: Promise<void> | null;
};

export function createSelectionSaver<T>(
  send: SelectionSaver<T>['send'],
  same: SelectionSaver<T>['same'],
): SelectionSaver<T> {
  return { send, same, activeSave: null };
}

/** Runs a load after the save in progress, if any, with the request timeout. */
export async function loadAfterSave<T, R>(
  saver: SelectionSaver<T>,
  request: (signal: AbortSignal) => Promise<R>,
): Promise<R> {
  await saver.activeSave;
  return withTimeout(request);
}

/**
 * A selection the server keeps. A change shows at once and saves the whole selection. At most
 * one request runs at a time; when it ends, the latest state is sent if it differs. If a save
 * fails, the selection goes back to the last saved state and saveFailed is set.
 */
export function useSavedSelection<T>(saver: SelectionSaver<T>, initial: T) {
  const [value, setValue] = useState<T>(initial);
  const [saveFailed, setSaveFailed] = useState(false);

  const desired = useRef<T>(initial);
  const saved = useRef<T>(initial);
  const saving = useRef(false);

  /** Takes what was loaded from the server as the saved state. */
  const reset = useCallback((loaded: T) => {
    desired.current = loaded;
    saved.current = loaded;
    setValue(loaded);
  }, []);

  const persist = useCallback(async () => {
    saving.current = true;
    try {
      for (;;) {
        const sending = desired.current;
        await withTimeout((signal) => saver.send(sending, signal));
        saved.current = sending;
        if (saver.same(desired.current, sending)) return;
      }
    } catch {
      desired.current = saved.current;
      setValue(saved.current);
      setSaveFailed(true);
    } finally {
      saving.current = false;
    }
  }, [saver]);

  /** Applies update to the latest state. An update returning its input changes nothing. */
  const change = useCallback(
    (update: (current: T) => T) => {
      const next = update(desired.current);
      if (next === desired.current) return;
      desired.current = next;
      setValue(next);
      setSaveFailed(false);
      if (saving.current) return; // the running save sends the latest state when it ends
      const save = persist().finally(() => {
        if (saver.activeSave === save) saver.activeSave = null;
      });
      saver.activeSave = save;
    },
    [persist, saver],
  );

  return { value, saveFailed, reset, change };
}
