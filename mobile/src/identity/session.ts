// Registered-user session (Story 1.2, AD-12): Google sign-in through Firebase Auth, then
// POST /v1/auth/link with the guest's device token, so nothing made as a guest is lost.
// The server keeps only the firebase_uid; the first name stays on this device (greeting).
import Constants from 'expo-constants';
import * as SecureStore from 'expo-secure-store';
import createClient from 'openapi-fetch';

import { API_URL } from '../api/config';
import type { paths } from '../api/schema';
import { ensureDeviceToken } from './device';

export const SESSION_KEY = 'cartwise.session';
/** Give up on the link request after this long. */
export const LINK_TIMEOUT_MS = 15_000;

export type Session = { userId: string; firstName: string | null };

export type SignInResult =
  | { status: 'success'; session: Session }
  | { status: 'cancelled' }
  | { status: 'unavailable' }
  /** `code`: the server's error code (e.g. device_already_linked), or 'network' / 'google'. */
  | { status: 'error'; code: string };

type GoogleSigninModule = typeof import('@react-native-google-signin/google-signin');
type FirebaseAuthModule = typeof import('@react-native-firebase/auth');
type Native = { google: GoogleSigninModule; auth: FirebaseAuthModule };

let native: Native | null | undefined; // undefined: not loaded yet
let configuredClientId: string | null = null;
let cached: Session | null | undefined; // undefined: not read from secure-store yet
const listeners = new Set<(s: Session | null) => void>();

// No auth middleware here: the link request carries the Firebase ID token, set explicitly.
const linkClient = createClient<paths>({
  baseUrl: API_URL,
  fetch: (request) => globalThis.fetch(request),
});

function warn(what: string, err: unknown): void {
  if (__DEV__) {
    const message = err instanceof Error ? err.message : String(err);
    console.warn(`[identity] ${what}:`, message);
  }
}

/** The web OAuth client id from app.config.ts; empty when Firebase is not set up. */
function webClientId(): string {
  const value = Constants.expoConfig?.extra?.googleWebClientId;
  return typeof value === 'string' ? value : '';
}

/** The native libraries, loaded lazily so a build without Firebase still runs as a guest. */
function loadNative(): Native | null {
  if (native !== undefined) return native;
  try {
    /* eslint-disable @typescript-eslint/no-require-imports */
    native = {
      google: require('@react-native-google-signin/google-signin'),
      auth: require('@react-native-firebase/auth'),
    };
    /* eslint-enable @typescript-eslint/no-require-imports */
  } catch (err) {
    warn('sign-in libraries unavailable', err);
    native = null;
  }
  return native;
}

/** True when Google sign-in can be offered (config and native libraries present). */
export function isSignInAvailable(): boolean {
  return webClientId() !== '' && loadNative() !== null;
}

function notify(s: Session | null): void {
  for (const fn of listeners) fn(s);
}

/** Subscribe to sign-in / sign-out. Returns the unsubscribe function. */
export function onSessionChange(fn: (s: Session | null) => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

/** The session as last read (undefined until loadSession has run once). No I/O. */
export function getCachedSession(): Session | null | undefined {
  return cached;
}

export async function loadSession(): Promise<Session | null> {
  if (cached !== undefined) return cached;
  try {
    const raw = await SecureStore.getItemAsync(SESSION_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    cached =
      parsed && typeof parsed.userId === 'string' && parsed.userId
        ? {
            userId: parsed.userId,
            firstName: typeof parsed.firstName === 'string' ? parsed.firstName : null,
          }
        : null;
  } catch (err) {
    warn('reading the session failed', err);
    cached = null;
  }
  return cached;
}

export async function isSignedIn(): Promise<boolean> {
  return (await loadSession()) !== null;
}

async function nativeSignOut(n: Native): Promise<void> {
  await Promise.allSettled([
    n.google.GoogleSignin.signOut(),
    n.auth.signOut(n.auth.getAuth()),
  ]);
}

async function clearLocalSession(): Promise<void> {
  cached = null;
  await SecureStore.deleteItemAsync(SESSION_KEY).catch((err) => warn('sign-out', err));
  notify(null);
}

/** Forget the session on this device and sign out of Google / Firebase. */
export async function signOut(): Promise<void> {
  const n = loadNative();
  if (n) await nativeSignOut(n);
  await clearLocalSession();
}

let syncStarted = false;

/**
 * App start (root layout, in the background): read the stored session, then keep it in
 * step with Firebase. When Firebase reports no user (signed out natively, or its state was
 * lost) while a local session exists, the local session is dropped, so the app is a guest
 * again instead of sending device-token requests while the scan gate thinks it is signed in.
 * Never throws.
 */
export async function startSessionSync(): Promise<void> {
  await loadSession();
  if (syncStarted) return;
  syncStarted = true;
  const n = webClientId() ? loadNative() : null;
  if (!n) return;
  try {
    n.auth.onAuthStateChanged(n.auth.getAuth(), (user) => {
      if (!user && cached) clearLocalSession().catch(() => {});
    });
  } catch (err) {
    warn('watching Firebase auth state failed', err);
  }
}

/**
 * A Firebase ID token for the signed-in user (refreshed by Firebase when it is near expiry;
 * `forceRefresh` gets a new one regardless). Null when there is no session or no Firebase
 * user. Never throws.
 */
export async function getUserIdToken(forceRefresh = false): Promise<string | null> {
  if (!(await loadSession())) return null;
  const n = loadNative();
  if (!n) return null;
  try {
    const user = n.auth.getAuth().currentUser;
    return user ? await n.auth.getIdToken(user, forceRefresh) : null;
  } catch (err) {
    warn('getting the ID token failed', err);
    return null;
  }
}

function isCancel(n: Native, err: unknown): boolean {
  const code = (err as { code?: unknown } | null)?.code;
  return code === n.google.statusCodes.SIGN_IN_CANCELLED;
}

type LinkOutcome = { userId: string } | { code: string };

async function link(idToken: string): Promise<LinkOutcome> {
  const deviceToken = await ensureDeviceToken().catch(() => null);
  const first = await postLink(idToken, deviceToken);
  // This device belongs to another account: sign this account in anyway (created or found
  // on the server); the device and the guest data stay with their owner.
  if (deviceToken && 'code' in first && first.code === 'device_already_linked') {
    return postLink(idToken, null);
  }
  return first;
}

async function postLink(idToken: string, deviceToken: string | null): Promise<LinkOutcome> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), LINK_TIMEOUT_MS);
  try {
    const { data, error } = await linkClient.POST('/v1/auth/link', {
      headers: { Authorization: `Bearer ${idToken}` },
      body: deviceToken ? { device_token: deviceToken } : {},
      signal: controller.signal,
    });
    if (data) return { userId: data.user_id };
    const code = (error as { error?: { code?: unknown } } | undefined)?.error?.code;
    return { code: typeof code === 'string' ? code : 'server' };
  } catch (err) {
    warn('link failed', err);
    return { code: 'network' };
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Google -> Firebase credential -> ID token -> POST /v1/auth/link (with the device token).
 * On success the session ({userId, firstName}) is saved in secure-store. Cancelling in
 * Google makes no server call and changes nothing. Any failure after Google signs out of
 * Firebase / Google again and saves nothing. Never throws.
 */
export async function signInWithGoogle(): Promise<SignInResult> {
  const clientId = webClientId();
  const n = clientId ? loadNative() : null;
  if (!n) return { status: 'unavailable' };
  const { GoogleSignin, isCancelledResponse } = n.google;

  let idToken: string;
  let firstName: string | null;
  try {
    if (configuredClientId !== clientId) {
      GoogleSignin.configure({ webClientId: clientId });
      configuredClientId = clientId;
    }
    await GoogleSignin.hasPlayServices({ showPlayServicesUpdateDialog: true });
    const response = await GoogleSignin.signIn();
    if (isCancelledResponse(response)) return { status: 'cancelled' };
    if (!response.data.idToken) throw new Error('Google returned no ID token');
    firstName = response.data.user.givenName ?? null;

    const auth = n.auth.getAuth();
    const credential = n.auth.GoogleAuthProvider.credential(response.data.idToken);
    const { user } = await n.auth.signInWithCredential(auth, credential);
    idToken = await n.auth.getIdToken(user);
  } catch (err) {
    if (isCancel(n, err)) return { status: 'cancelled' };
    warn('Google sign-in failed', err);
    await nativeSignOut(n);
    return { status: 'error', code: 'google' };
  }

  const linked = await link(idToken);
  if ('code' in linked) {
    await nativeSignOut(n);
    return { status: 'error', code: linked.code };
  }

  const session: Session = { userId: linked.userId, firstName };
  cached = session;
  try {
    await SecureStore.setItemAsync(SESSION_KEY, JSON.stringify(session));
  } catch (err) {
    warn('saving the session failed', err); // Still signed in for this run.
  }
  notify(session);
  return { status: 'success', session };
}
