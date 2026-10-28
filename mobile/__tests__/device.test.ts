// jest.mock calls are hoisted above the imports.
const mockStore = new Map<string, string>();
const mockRandomUUID = jest.fn(() => 'install-0000-1111-2222-333344445555');
const mockSetItemFail = { keys: new Set<string>() };

jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn(async (k: string) => mockStore.get(k) ?? null),
  setItemAsync: jest.fn(async (k: string, v: string) => {
    if (mockSetItemFail.keys.has(k)) throw new Error('keystore unavailable');
    mockStore.set(k, v);
  }),
  deleteItemAsync: jest.fn(async (k: string) => {
    mockStore.delete(k);
  }),
}));
jest.mock('expo-crypto', () => ({ randomUUID: () => mockRandomUUID() }));

type DeviceModule = typeof import('../src/identity/device');

const DAY = 24 * 60 * 60 * 1000;
const KEYS = {
  installId: 'cartwise.install_id',
  token: 'cartwise.device_token',
  meta: 'cartwise.device_token_meta',
};
const T0 = Date.UTC(2026, 9, 28, 12, 0, 0);

let now = T0;

function b64url(obj: unknown): string {
  return btoa(JSON.stringify(obj)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/** A JWT-shaped token (unsigned; the app never verifies it). `serverNow` may be skewed. */
function jwtFor(name: string, lifetimeMs = 30 * DAY, serverNow = now): string {
  const iat = Math.floor(serverNow / 1000);
  const payload = { sub: name, typ: 'device', iat, exp: iat + lifetimeMs / 1000 };
  return `${b64url({ alg: 'HS256', typ: 'JWT' })}.${b64url(payload)}.sig`;
}

function registered(token: string, opts: { lifetimeMs?: number; serverNow?: number } = {}) {
  const { lifetimeMs = 30 * DAY, serverNow = now } = opts;
  return new Response(
    JSON.stringify({
      device_id: '0190f0e0-0000-7000-8000-000000000001',
      device_token: token,
      expires_at: new Date(serverNow + lifetimeMs).toISOString(),
    }),
    { status: 201, headers: { 'Content-Type': 'application/json' } },
  );
}

/** Fresh module state (in-memory cache) per test; the store mock is shared. */
function load(): DeviceModule {
  let mod!: DeviceModule;
  jest.isolateModules(() => {
    mod = require('../src/identity/device');
  });
  return mod;
}

/** A token received `ageMs` ago with the given lifetime. */
function storeToken(token: string, ageMs: number, lifetimeMs = 30 * DAY): void {
  mockStore.set(KEYS.installId, 'existing-install-id-0123456789');
  mockStore.set(KEYS.token, token);
  mockStore.set(
    KEYS.meta,
    JSON.stringify({ expiresAt: 'ignored', receivedAt: now - ageMs, lifetimeMs }),
  );
}

async function sentBody(fetchMock: jest.Mock, call = 0): Promise<unknown> {
  const req = fetchMock.mock.calls[call][0] as Request;
  return JSON.parse(await req.clone().text());
}

const offline = () => Promise.reject(new TypeError('Network request failed'));

describe('device identity', () => {
  let fetchMock: jest.Mock;
  let warn: jest.SpyInstance;

  beforeEach(() => {
    now = T0;
    jest.spyOn(Date, 'now').mockImplementation(() => now);
    mockStore.clear();
    mockSetItemFail.keys.clear();
    mockRandomUUID.mockClear();
    fetchMock = jest.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
  });

  afterEach(() => {
    jest.restoreAllMocks();
    jest.useRealTimers();
  });

  it('first launch: creates an install id, registers and stores the token', async () => {
    const tok = jwtFor('tok-1');
    fetchMock.mockResolvedValueOnce(registered(tok));
    const { ensureDeviceToken } = load();

    await expect(ensureDeviceToken()).resolves.toBe(tok);

    expect(mockRandomUUID).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const req = fetchMock.mock.calls[0][0] as Request;
    expect(req.method).toBe('POST');
    expect(req.url).toMatch(/\/v1\/devices$/);
    expect(req.headers.get('Authorization')).toBeNull();
    expect(await sentBody(fetchMock)).toEqual({
      install_id: 'install-0000-1111-2222-333344445555',
    });
    expect(mockStore.get(KEYS.installId)).toBe('install-0000-1111-2222-333344445555');
    expect(mockStore.get(KEYS.token)).toBe(tok);
    const meta = JSON.parse(mockStore.get(KEYS.meta)!);
    expect(meta.receivedAt).toBe(T0);
    expect(meta.lifetimeMs).toBe(30 * DAY);
    expect(Date.parse(meta.expiresAt)).toBe(T0 + 30 * DAY);
  });

  it('uses a stored token with more than 3 days left, without the network', async () => {
    storeToken('stored', 20 * DAY);
    const { ensureDeviceToken, getDeviceToken } = load();

    await expect(ensureDeviceToken()).resolves.toBe('stored');
    await expect(getDeviceToken()).resolves.toBe('stored');
    expect(fetchMock).not.toHaveBeenCalled();
    expect(mockRandomUUID).not.toHaveBeenCalled();
  });

  it('re-registers with the same install id when under 3 days are left', async () => {
    storeToken('old', 28 * DAY);
    const tok = jwtFor('new');
    fetchMock.mockResolvedValueOnce(registered(tok));
    const { ensureDeviceToken } = load();

    await expect(ensureDeviceToken()).resolves.toBe(tok);
    expect(await sentBody(fetchMock)).toEqual({ install_id: 'existing-install-id-0123456789' });
    expect(mockRandomUUID).not.toHaveBeenCalled();
    expect(mockStore.get(KEYS.token)).toBe(tok);
  });

  it('short lifetimes refresh at 20% before the end, not on every call', async () => {
    // 2-day token: margin is min(3 days, 20%) = 9.6 h, so it is fresh for 38.4 h.
    storeToken('short', 38 * 60 * 60 * 1000, 2 * DAY);
    const { ensureDeviceToken } = load();
    await expect(ensureDeviceToken()).resolves.toBe('short');
    expect(fetchMock).not.toHaveBeenCalled();

    now += 60 * 60 * 1000; // 39 h old
    fetchMock.mockResolvedValueOnce(registered(jwtFor('next', 2 * DAY)));
    await ensureDeviceToken();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('judges expiry on the local clock only (server clock skewed)', async () => {
    // The server's clock is 10 days ahead: its expires_at is 40 days from local "now".
    const ahead = jwtFor('ahead', 30 * DAY, T0 + 10 * DAY);
    fetchMock.mockResolvedValueOnce(registered(ahead, { serverNow: T0 + 10 * DAY }));
    const { ensureDeviceToken, getDeviceToken } = load();
    await expect(ensureDeviceToken()).resolves.toBe(ahead);

    now = T0 + 26 * DAY; // fresh by local elapsed time
    await expect(ensureDeviceToken()).resolves.toBe(ahead);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    now = T0 + 30 * DAY; // lifetime used up locally, though server expires_at is later
    await expect(getDeviceToken()).resolves.toBeNull();
  });

  it('a server clock behind does not cause a refresh on every call', async () => {
    const behind = jwtFor('behind', 30 * DAY, T0 - 29 * DAY);
    fetchMock.mockResolvedValueOnce(registered(behind, { serverNow: T0 - 29 * DAY }));
    const { ensureDeviceToken } = load();
    await ensureDeviceToken();
    now += 60_000;
    await expect(ensureDeviceToken()).resolves.toBe(behind);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('offline on first launch: null, warns in dev, backs off, then retries', async () => {
    fetchMock.mockImplementationOnce(offline);
    const { ensureDeviceToken } = load();

    await expect(ensureDeviceToken()).resolves.toBeNull();
    expect(warn).toHaveBeenCalledWith(
      expect.stringContaining('[identity]'),
      'Network request failed',
    );
    expect(mockStore.get(KEYS.token)).toBeUndefined();

    // Within the backoff: no new attempt.
    now += 29_000;
    await expect(ensureDeviceToken()).resolves.toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    now += 2_000;
    const tok = jwtFor('later');
    fetchMock.mockResolvedValueOnce(registered(tok));
    await expect(ensureDeviceToken()).resolves.toBe(tok);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    // The same install id is reused for the retry.
    expect(await sentBody(fetchMock, 1)).toEqual(await sentBody(fetchMock, 0));
  });

  it('times out a hanging registration after 10 s', async () => {
    jest.useFakeTimers({ doNotFake: ['Date'] });
    fetchMock.mockImplementation(
      (req: Request) =>
        new Promise((_resolve, reject) => {
          req.signal.addEventListener('abort', () => reject(new Error('aborted')));
        }),
    );
    const { ensureDeviceToken } = load();

    const result = ensureDeviceToken();
    await jest.advanceTimersByTimeAsync(9_999);
    let settled = false;
    void result.then(() => {
      settled = true;
    });
    await Promise.resolve();
    expect(settled).toBe(false);

    await jest.advanceTimersByTimeAsync(1);
    await expect(result).resolves.toBeNull();
  });

  it('offline with a token close to expiry: keeps using it', async () => {
    storeToken('old', 29 * DAY);
    fetchMock.mockImplementationOnce(offline);
    const { ensureDeviceToken } = load();

    await expect(ensureDeviceToken()).resolves.toBe('old');
  });

  it('offline with an expired token: resolves to null', async () => {
    storeToken('expired', 31 * DAY);
    fetchMock.mockImplementationOnce(offline);
    const { ensureDeviceToken, getDeviceToken } = load();

    await expect(ensureDeviceToken()).resolves.toBeNull();
    await expect(getDeviceToken()).resolves.toBeNull();
  });

  it('server error: resolves to null without throwing', async () => {
    fetchMock.mockResolvedValueOnce(new Response('{}', { status: 500 }));
    const { ensureDeviceToken } = load();
    await expect(ensureDeviceToken()).resolves.toBeNull();
  });

  it('still registers when the install id cannot be saved', async () => {
    mockSetItemFail.keys.add(KEYS.installId);
    const tok = jwtFor('tok');
    fetchMock.mockResolvedValueOnce(registered(tok));
    const { ensureDeviceToken } = load();

    await expect(ensureDeviceToken()).resolves.toBe(tok);
    expect(warn).toHaveBeenCalledWith(expect.stringContaining('[identity]'), 'keystore unavailable');
    expect(await sentBody(fetchMock)).toEqual({
      install_id: 'install-0000-1111-2222-333344445555',
    });
  });

  it('does not warn outside dev', async () => {
    const g = globalThis as { __DEV__?: boolean };
    const saved = g.__DEV__;
    g.__DEV__ = false;
    try {
      fetchMock.mockImplementationOnce(offline);
      const { ensureDeviceToken } = load();
      await expect(ensureDeviceToken()).resolves.toBeNull();
      expect(warn).not.toHaveBeenCalled();
    } finally {
      g.__DEV__ = saved;
    }
  });

  it('concurrent calls share one registration', async () => {
    const tok = jwtFor('shared');
    fetchMock.mockResolvedValueOnce(registered(tok));
    const { ensureDeviceToken } = load();

    const results = await Promise.all([ensureDeviceToken(), ensureDeviceToken()]);
    expect(results).toEqual([tok, tok]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('clearDeviceToken forgets the token but keeps the install id', async () => {
    storeToken('stored', 1 * DAY);
    const { clearDeviceToken, getDeviceToken, ensureDeviceToken } = load();

    await clearDeviceToken();
    await expect(getDeviceToken()).resolves.toBeNull();
    expect(mockStore.has(KEYS.token)).toBe(false);
    expect(mockStore.has(KEYS.meta)).toBe(false);
    expect(mockStore.get(KEYS.installId)).toBe('existing-install-id-0123456789');

    const tok = jwtFor('fresh');
    fetchMock.mockResolvedValueOnce(registered(tok));
    await expect(ensureDeviceToken()).resolves.toBe(tok);
    expect(await sentBody(fetchMock)).toEqual({ install_id: 'existing-install-id-0123456789' });
  });

  it('clearDeviceToken(rejected) keeps a token that already replaced the rejected one', async () => {
    storeToken('current', 1 * DAY);
    const { clearDeviceToken, getDeviceToken } = load();

    await clearDeviceToken('older');
    await expect(getDeviceToken()).resolves.toBe('current');
    expect(mockStore.get(KEYS.token)).toBe('current');

    await clearDeviceToken('current');
    await expect(getDeviceToken()).resolves.toBeNull();
  });

  it('a clear during an in-flight run does not hand back the cleared token', async () => {
    storeToken('stale', 1 * DAY);
    const { clearDeviceToken, ensureDeviceToken } = load();

    const before = ensureDeviceToken(); // in flight, will resolve to the stale token
    await clearDeviceToken('stale');
    const tok = jwtFor('fresh');
    fetchMock.mockResolvedValueOnce(registered(tok));

    await expect(ensureDeviceToken()).resolves.toBe(tok);
    await before;
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('two parallel requests rejected with 401: one registration, both retried', async () => {
    storeToken('stale', 1 * DAY);
    let device!: DeviceModule;
    let client!: typeof import('../src/api/client');
    jest.isolateModules(() => {
      device = require('../src/identity/device');
      client = require('../src/api/client');
    });
    const fresh = jwtFor('fresh');
    const jsonRes = (status: number, body: unknown) =>
      new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      });
    fetchMock.mockImplementation(async (req: Request) => {
      if (req.url.endsWith('/v1/devices')) return registered(fresh);
      return req.headers.get('Authorization') === `Bearer ${fresh}`
        ? jsonRes(200, { kind: 'device', id: '0190f0e0-0000-7000-8000-000000000001' })
        : jsonRes(401, { error: { code: 'invalid_token', message_he: 'x', details: {} } });
    });

    const [a, b] = await Promise.all([client.api.GET('/v1/me'), client.api.GET('/v1/me')]);
    expect(a.response.status).toBe(200);
    expect(b.response.status).toBe(200);

    const calls = fetchMock.mock.calls.map(([r]) => r as Request);
    expect(calls.filter((r) => r.url.endsWith('/v1/devices'))).toHaveLength(1);
    const retried = calls.filter((r) => r.url.endsWith('/v1/me')).slice(2);
    expect(retried.map((r) => r.headers.get('Authorization'))).toEqual([
      `Bearer ${fresh}`,
      `Bearer ${fresh}`,
    ]);
    expect(mockStore.get(KEYS.token)).toBe(fresh);
    await expect(device.getDeviceToken()).resolves.toBe(fresh);
  });

  it('never logs the token', async () => {
    storeToken('secret-token-value', 29 * DAY);
    fetchMock.mockImplementationOnce(offline);
    const { ensureDeviceToken } = load();
    await ensureDeviceToken();
    expect(JSON.stringify(warn.mock.calls)).not.toContain('secret-token-value');
  });
});
