// Opens SHEET-SIGNIN on demand (Story 1.2): from the scan tab now, and from SHEET-QUOTA
// later (Epic 8). <SignInHost /> renders the sheet for whatever request is open here.
import { useSyncExternalStore } from 'react';

import { type Session, isSignedIn } from './session';

export type SignInReason = 'scan' | 'quota';

export type SignInRequest = {
  reason: SignInReason;
  resolve: (signedIn: boolean) => void;
};

let current: SignInRequest | null = null;
const listeners = new Set<() => void>();

function set(next: SignInRequest | null): void {
  current = next;
  for (const fn of listeners) fn();
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

/**
 * Resolves true when the user is (or becomes) signed in, false when they cancel.
 * Already signed in: resolves true without opening the sheet. A second call while the
 * sheet is open joins the open request (never a sheet on top of a sheet).
 */
export async function requireSignIn(reason: SignInReason): Promise<boolean> {
  if (await isSignedIn()) return true;
  if (current) {
    const open = current;
    return new Promise((resolve) => {
      const prev = open.resolve;
      open.resolve = (ok) => {
        prev(ok);
        resolve(ok);
      };
    });
  }
  return new Promise((resolve) => set({ reason, resolve }));
}

/** Close the open request: signed in (with the new session) or cancelled. */
export function settleSignIn(session: Session | null): void {
  const open = current;
  if (!open) return;
  set(null);
  open.resolve(session !== null);
}

/** The open sign-in request, if any (for SignInHost). */
export function useSignInRequest(): SignInRequest | null {
  return useSyncExternalStore(subscribe, () => current, () => current);
}
