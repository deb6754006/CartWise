// Guest identity (Story 1.1, AD-12): registers this installation with the server and keeps
// its device token. Runs in the background; the app works without it.
import * as Crypto from 'expo-crypto';
import * as SecureStore from 'expo-secure-store';
import createClient from 'openapi-fetch';

import { API_URL } from '../api/config';
import type { paths } from '../api/schema';

export const STORE_KEYS = {
  installId: 'cartwise.install_id',
  token: 'cartwise.device_token',
  /** JSON: { expiresAt (server ISO time), receivedAt (local ms), lifetimeMs }. */
  meta: 'cartwise.device_token_meta',
} as const;

/** Refresh this long before the token's lifetime runs out (capped at 20% of the lifetime). */
export const REFRESH_MARGIN_MS = 3 * 24 * 60 * 60 * 1000;
/** Give up on a registration request after this long. */
export const REGISTER_TIMEOUT_MS = 10_000;
/** After a failed registration, do not try again for this long. */
export const RETRY_BACKOFF_MS = 30_000;

type StoredToken = {
  token: string;
  expiresAt: string;
  /** Local clock (Date.now()) when the token was received. */
  receivedAt: number;
  /** exp - iat from the token, so expiry is judged on the local clock only (no skew). */
  lifetimeMs: number;
};

let cached: StoredToken | null | undefined; // undefined: not read from secure-store yet
let sessionInstallId: string | null = null; // kept in memory if secure-store cannot save it
let inflight: Promise<string | null> | null = null;
let lastFailureAt: number | null = null;

// A separate client without the auth middleware (that middleware calls back into here).
const registrationClient = createClient<paths>({
  baseUrl: API_URL,
  fetch: (request) => globalThis.fetch(request),
});

function warn(err: unknown): void {
  if (__DEV__) {
    const message = err instanceof Error ? err.message : String(err);
    console.warn('[identity] device registration failed:', message);
  }
}

function elapsed(t: StoredToken, now: number): number {
  return now - t.receivedAt;
}

function isUsable(t: StoredToken, now: number): boolean {
  const e = elapsed(t, now);
  return e >= 0 && e < t.lifetimeMs;
}

function isFresh(t: StoredToken, now: number): boolean {
  const margin = Math.min(REFRESH_MARGIN_MS, 0.2 * t.lifetimeMs);
  const e = elapsed(t, now);
  return e >= 0 && e <= t.lifetimeMs - margin;
}

/** Token lifetime (exp - iat) from the JWT payload, read without verifying it. */
function lifetimeFromJwt(token: string): number | null {
  try {
    const part = token.split('.')[1];
    const b64 = part.replace(/-/g, '+').replace(/_/g, '/');
    const claims = JSON.parse(atob(b64.padEnd(Math.ceil(b64.length / 4) * 4, '=')));
    const ms = (claims.exp - claims.iat) * 1000;
    return Number.isFinite(ms) && ms > 0 ? ms : null;
  } catch {
    return null;
  }
}

async function loadToken(): Promise<StoredToken | null> {
  if (cached !== undefined) return cached;
  const [token, meta] = await Promise.all([
    SecureStore.getItemAsync(STORE_KEYS.token),
    SecureStore.getItemAsync(STORE_KEYS.meta),
  ]);
  let parsed: Omit<StoredToken, 'token'> | null = null;
  try {
    const m = meta ? JSON.parse(meta) : null;
    if (m && Number.isFinite(m.receivedAt) && Number.isFinite(m.lifetimeMs)) parsed = m;
  } catch {
    parsed = null;
  }
  cached = token && parsed ? { ...parsed, token } : null;
  return cached;
}

async function installId(): Promise<string> {
  if (sessionInstallId) return sessionInstallId;
  const existing = await SecureStore.getItemAsync(STORE_KEYS.installId);
  if (existing) {
    sessionInstallId = existing;
    return existing;
  }
  const id = Crypto.randomUUID();
  sessionInstallId = id;
  try {
    await SecureStore.setItemAsync(STORE_KEYS.installId, id);
  } catch (err) {
    warn(err); // Use the id for this session; a new one is made next launch.
  }
  return id;
}

async function register(): Promise<StoredToken> {
  const id = await installId();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REGISTER_TIMEOUT_MS);
  let result;
  try {
    result = await registrationClient.POST('/v1/devices', {
      body: { install_id: id },
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
  const { data, response } = result;
  if (!data) throw new Error(`POST /v1/devices returned ${response.status}`);

  const receivedAt = Date.now();
  const lifetimeMs = lifetimeFromJwt(data.device_token) ?? Date.parse(data.expires_at) - receivedAt;
  if (!Number.isFinite(lifetimeMs) || lifetimeMs <= 0) {
    throw new Error('POST /v1/devices: bad token lifetime');
  }

  const stored: StoredToken = {
    token: data.device_token,
    expiresAt: data.expires_at,
    receivedAt,
    lifetimeMs,
  };
  cached = stored;
  try {
    await SecureStore.setItemAsync(STORE_KEYS.token, stored.token);
    await SecureStore.setItemAsync(
      STORE_KEYS.meta,
      JSON.stringify({ expiresAt: stored.expiresAt, receivedAt, lifetimeMs }),
    );
  } catch (err) {
    warn(err); // Still usable for this session.
  }
  return stored;
}

async function run(): Promise<string | null> {
  let current: StoredToken | null = null;
  try {
    current = await loadToken();
  } catch (err) {
    warn(err);
  }
  const now = Date.now();
  if (current && isFresh(current, now)) return current.token;
  const fallback = current && isUsable(current, now) ? current.token : null;
  if (lastFailureAt !== null && now - lastFailureAt < RETRY_BACKOFF_MS) return fallback;
  try {
    const token = (await register()).token;
    lastFailureAt = null;
    return token;
  } catch (err) {
    lastFailureAt = Date.now();
    warn(err);
    // Offline: keep using a token that has not expired yet; try again later.
    return fallback;
  }
}

/**
 * Returns a usable device token, registering (or re-registering) the device when there is
 * none or it is near the end of its lifetime. Never throws; resolves to null when there is
 * no usable token. Concurrent calls share one registration; after a failure, registration
 * is not retried for RETRY_BACKOFF_MS.
 */
export function ensureDeviceToken(): Promise<string | null> {
  if (inflight) return inflight;
  const p = run().finally(() => {
    if (inflight === p) inflight = null;
  });
  inflight = p;
  return p;
}

/** The stored token if it is still within its lifetime. No network. */
export async function getDeviceToken(): Promise<string | null> {
  try {
    const current = await loadToken();
    return current && isUsable(current, Date.now()) ? current.token : null;
  } catch {
    return null;
  }
}

/**
 * Forget the token (e.g. after a 401). With `rejected`, only if the stored token is still
 * that one, so a token a concurrent request just registered is kept. The install id is kept.
 */
export async function clearDeviceToken(rejected?: string): Promise<void> {
  if (rejected !== undefined) {
    let current: string | null | undefined;
    try {
      current = (await loadToken())?.token;
    } catch {
      current = undefined;
    }
    if (current !== rejected) return;
  }
  cached = null;
  // A run started before the clear may hand back the cleared token; later callers start fresh.
  inflight = null;
  await Promise.all([
    SecureStore.deleteItemAsync(STORE_KEYS.token),
    SecureStore.deleteItemAsync(STORE_KEYS.meta),
  ]);
}
