import createClient, { type Middleware } from 'openapi-fetch';

import { clearDeviceToken, ensureDeviceToken } from '../identity/device';
import { getUserIdToken, signOut } from '../identity/session';
import { API_URL } from './config';
import type { paths } from './schema';

export { API_URL, DEFAULT_API_URL } from './config';

/** 401 codes after which the device registers again and the request is retried once. */
const REREGISTER_CODES = new Set(['invalid_token', 'auth_required']);

/** Paths that never wait for (or carry) a token. /v1/auth/link sets its own (session.ts). */
const NO_AUTH_PATHS = new Set(['/v1/health', '/v1/devices', '/v1/auth/link']);

// For requests sent with a token: a copy (a sent body cannot be read twice), the token and
// its kind, for the one retry. Keyed weakly by the request, so nothing leaks if a callback
// never runs.
type Pending = { copy: Request; token: string; kind: 'user' | 'device' };
const pending = new WeakMap<Request, Pending>();

async function errorCode(response: Response): Promise<string | undefined> {
  try {
    const body = await response.clone().json();
    return body?.error?.code;
  } catch {
    return undefined;
  }
}

async function deviceToken(): Promise<string | null> {
  return ensureDeviceToken().catch(() => null);
}

async function userToken(forceRefresh = false): Promise<string | null> {
  return getUserIdToken(forceRefresh).catch(() => null);
}

/** 401 codes on a user request after which the user path is retried / abandoned. */
const USER_RETRY_CODES = new Set(['invalid_token', 'not_linked']);

/**
 * Adds `Authorization: Bearer <token>`: the Firebase ID token when signed in, otherwise the
 * device token. On a 401:
 * - device: re-registers and retries once;
 * - user, invalid_token: one forced ID-token refresh and one retry. If the server still
 *   answers 401 (any code), or the first answer was not_linked, the account is no longer
 *   usable here: sign out (the app is a guest again) and retry once with the device token.
 * Other statuses (e.g. 503 auth_unavailable) are returned as they are.
 */
export const authMiddleware: Middleware = {
  async onRequest({ request, schemaPath }) {
    if (NO_AUTH_PATHS.has(schemaPath)) return undefined;
    let kind: Pending['kind'] = 'user';
    let token = await userToken();
    if (!token) {
      kind = 'device';
      token = await deviceToken();
    }
    if (!token) return undefined;
    request.headers.set('Authorization', `Bearer ${token}`);
    pending.set(request, { copy: request.clone(), token, kind });
    return request;
  },
  async onResponse({ request, response, options }) {
    const entry = pending.get(request);
    pending.delete(request);
    if (response.status !== 401 || !entry) return undefined;
    const code = (await errorCode(response)) ?? '';

    let token: string | null;
    if (entry.kind === 'user') {
      if (!USER_RETRY_CODES.has(code)) return undefined;
      let last = response;
      if (code === 'invalid_token') {
        // One forced refresh (e.g. the token expired in flight), then one retry.
        const fresh = await userToken(true);
        // No token at all (e.g. offline refresh): keep the session, surface the 401.
        if (!fresh) return undefined;
        if (fresh !== entry.token) {
          const retry = entry.copy.clone(); // entry.copy stays unsent for the fallback
          retry.headers.set('Authorization', `Bearer ${fresh}`);
          last = await options.fetch(retry);
          if (last.status !== 401) return last;
        }
      }
      await signOut().catch(() => {});
      token = await deviceToken();
      if (!token) return last;
    } else {
      if (!REREGISTER_CODES.has(code)) return undefined;
      // Clears only if no concurrent request has already replaced the rejected token.
      await clearDeviceToken(entry.token).catch(() => {});
      token = await deviceToken();
    }
    if (!token) return undefined;
    entry.copy.headers.set('Authorization', `Bearer ${token}`);
    // Sent with plain fetch, so it does not pass through this middleware again.
    return options.fetch(entry.copy);
  },
  onError({ request }) {
    pending.delete(request);
  },
};

// fetch is looked up per call, so it can be replaced (e.g. in tests) after import.
export const api = createClient<paths>({
  baseUrl: API_URL,
  fetch: (request) => globalThis.fetch(request),
});
api.use(authMiddleware);
