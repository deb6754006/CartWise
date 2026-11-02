// Whether this device finished Onboarding. Neither function ever throws: a problem with the
// secure store must not keep anyone out of the app.
import * as SecureStore from 'expo-secure-store';

export const ONBOARDING_DONE_KEY = 'cartwise.onboarding_done';
/** A slow read counts as done: the tabs open, and Onboarding waits for the next launch. */
export const FLAG_READ_TIMEOUT_MS = 1500;

// Kept in memory as well: if saving the flag fails, the tabs must not send the user straight back.
let doneThisSession = false;

/** True once Onboarding is finished, and also when the flag cannot be read in time. */
export async function isOnboardingDone(): Promise<boolean> {
  if (doneThisSession) return true;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<boolean>((resolve) => {
    timer = setTimeout(() => resolve(true), FLAG_READ_TIMEOUT_MS);
  });
  try {
    const read = SecureStore.getItemAsync(ONBOARDING_DONE_KEY).then((value) => value !== null);
    return await Promise.race([read, timeout]);
  } catch {
    return true;
  } finally {
    clearTimeout(timer);
  }
}

/** Takes effect at once for this launch. If saving fails, Onboarding returns next launch. */
export async function markOnboardingDone(): Promise<void> {
  doneThisSession = true;
  try {
    await SecureStore.setItemAsync(ONBOARDING_DONE_KEY, '1');
  } catch {
    // Nothing to tell the user: the app works either way.
  }
}
