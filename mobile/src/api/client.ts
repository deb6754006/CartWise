import createClient, { type Middleware } from 'openapi-fetch';

import { clearDeviceToken, ensureDeviceToken } from '../identity/device';
import { API_URL } from './config';
import type { paths } from './schema';

export { API_URL, DEFAULT_API_URL } from './config';

/** 401 codes after which the device registers again and the request is retried once. */
const REREGISTER_CODES = new Set(['invalid_token', 'auth_required']);

/** Paths that never wait for (or carry) a device token. */
const NO_AUTH_PATHS = new Set(['/v1/health', '/v1/devices']);

// For requests sent with a token: a copy (a sent body cannot be read twice) and the token,
// for the one retry. Keyed weakly by the request, so nothing leaks if a callback never runs.
const pending = new WeakMap<Request, { copy: Request; token: string }>();

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

/** Adds `Authorization: Bearer <device_token>`; on a 401 re-registers and retries once. */
export const authMiddleware: Middleware = {
  async onRequest({ request, schemaPath }) {
    if (NO_AUTH_PATHS.has(schemaPath)) return undefined;
    const token = await deviceToken();
    if (!token) return undefined;
    request.headers.set('Authorization', `Bearer ${token}`);
    pending.set(request, { copy: request.clone(), token });
    return request;
  },
  async onResponse({ request, response, options }) {
    const entry = pending.get(request);
    pending.delete(request);
    if (response.status !== 401 || !entry) return undefined;
    if (!REREGISTER_CODES.has((await errorCode(response)) ?? '')) return undefined;

    // Clears only if no concurrent request has already replaced the rejected token.
    await clearDeviceToken(entry.token).catch(() => {});
    const token = await deviceToken();
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
