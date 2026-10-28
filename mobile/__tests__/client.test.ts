// jest.mock calls are hoisted above the imports.
const mockEnsure = jest.fn<Promise<string | null>, []>();
const mockClear = jest.fn<Promise<void>, [string?]>(() => Promise.resolve());

jest.mock('../src/identity/device', () => ({
  ensureDeviceToken: () => mockEnsure(),
  clearDeviceToken: (rejected?: string) => mockClear(rejected),
}));

type ClientModule = typeof import('../src/api/client');

function loadClient(): ClientModule {
  let mod!: ClientModule;
  jest.isolateModules(() => {
    mod = require('../src/api/client');
  });
  return mod;
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const unauthorized = (code: string) => json(401, { error: { code, message_he: 'x', details: {} } });

describe('api client', () => {
  const original = process.env.EXPO_PUBLIC_API_URL;

  afterEach(() => {
    if (original === undefined) delete process.env.EXPO_PUBLIC_API_URL;
    else process.env.EXPO_PUBLIC_API_URL = original;
    jest.resetModules();
  });

  it('defaults to the Android emulator host', () => {
    delete process.env.EXPO_PUBLIC_API_URL;
    const { API_URL, DEFAULT_API_URL } = loadClient();
    expect(DEFAULT_API_URL).toBe('http://10.0.2.2:8000');
    expect(API_URL).toBe('http://10.0.2.2:8000');
  });

  it('uses EXPO_PUBLIC_API_URL when set', () => {
    process.env.EXPO_PUBLIC_API_URL = 'http://192.168.1.5:8000';
    const { API_URL } = loadClient();
    expect(API_URL).toBe('http://192.168.1.5:8000');
  });
});

describe('api client auth', () => {
  let fetchMock: jest.Mock;

  beforeEach(() => {
    mockEnsure.mockReset();
    mockClear.mockClear();
    fetchMock = jest.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
  });

  const authOf = (call: number) =>
    (fetchMock.mock.calls[call][0] as Request).headers.get('Authorization');

  it('adds the device token as a Bearer header', async () => {
    mockEnsure.mockResolvedValue('tok');
    fetchMock.mockResolvedValueOnce(json(200, { kind: 'device', id: 'd1' }));
    const { api } = loadClient();

    const { data } = await api.GET('/v1/me');
    expect(data).toEqual({ kind: 'device', id: 'd1' });
    expect(authOf(0)).toBe('Bearer tok');
  });

  it('sends the request without a header when there is no token', async () => {
    mockEnsure.mockResolvedValue(null);
    fetchMock.mockResolvedValueOnce(json(200, { kind: 'device', id: 'd1' }));
    const { api } = loadClient();

    await api.GET('/v1/me');
    expect(authOf(0)).toBeNull();
  });

  it('still sends the request when getting a token throws', async () => {
    mockEnsure.mockRejectedValue(new Error('boom'));
    fetchMock.mockResolvedValueOnce(json(200, { kind: 'device', id: 'd1' }));
    const { api } = loadClient();

    const { response } = await api.GET('/v1/me');
    expect(response.status).toBe(200);
    expect(authOf(0)).toBeNull();
  });

  it.each([
    ['/v1/health', (c: ClientModule) => c.api.GET('/v1/health')],
    [
      '/v1/devices',
      (c: ClientModule) =>
        c.api.POST('/v1/devices', { body: { install_id: 'abcdefghijklmnop' } }),
    ],
  ])('%s does not wait for a device token', async (_path, call) => {
    mockEnsure.mockReturnValue(new Promise(() => {})); // would hang if awaited
    fetchMock.mockResolvedValueOnce(json(200, {}));
    await call(loadClient());
    expect(mockEnsure).not.toHaveBeenCalled();
    expect(authOf(0)).toBeNull();
  });

  it('on 401 invalid_token: clears that token, re-registers and retries once', async () => {
    mockEnsure.mockResolvedValueOnce('stale').mockResolvedValueOnce('fresh');
    fetchMock
      .mockResolvedValueOnce(unauthorized('invalid_token'))
      .mockResolvedValueOnce(json(200, { kind: 'device', id: 'd1' }));
    const { api } = loadClient();

    const { data } = await api.GET('/v1/me');
    expect(data).toEqual({ kind: 'device', id: 'd1' });
    expect(mockClear).toHaveBeenCalledTimes(1);
    expect(mockClear).toHaveBeenCalledWith('stale');
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(authOf(0)).toBe('Bearer stale');
    expect(authOf(1)).toBe('Bearer fresh');
  });

  it('retries only once', async () => {
    mockEnsure.mockResolvedValue('tok');
    fetchMock.mockImplementation(async () => unauthorized('invalid_token'));
    const { api } = loadClient();

    const { error, response } = await api.GET('/v1/me');
    expect(response.status).toBe(401);
    expect(error).toEqual({ error: { code: 'invalid_token', message_he: 'x', details: {} } });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('on 401 auth_required after sending a token: re-registers and retries', async () => {
    mockEnsure.mockResolvedValueOnce('stale').mockResolvedValueOnce('fresh');
    fetchMock
      .mockResolvedValueOnce(unauthorized('auth_required'))
      .mockResolvedValueOnce(json(200, { kind: 'device', id: 'd1' }));
    const { api } = loadClient();

    const { data } = await api.GET('/v1/me');
    expect(data).toEqual({ kind: 'device', id: 'd1' });
    expect(authOf(1)).toBe('Bearer fresh');
  });

  it('does not retry (or clone) a request sent without a token', async () => {
    mockEnsure.mockResolvedValue(null);
    fetchMock.mockResolvedValueOnce(unauthorized('auth_required'));
    const clone = jest.spyOn(Request.prototype, 'clone');
    const { api } = loadClient();

    const { response } = await api.GET('/v1/me');
    expect(response.status).toBe(401);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(mockEnsure).toHaveBeenCalledTimes(1);
    expect(mockClear).not.toHaveBeenCalled();
    expect(clone).not.toHaveBeenCalled();
    clone.mockRestore();
  });

  it('does not retry when re-registration fails', async () => {
    mockEnsure.mockResolvedValueOnce('stale').mockResolvedValueOnce(null);
    fetchMock.mockResolvedValueOnce(unauthorized('invalid_token'));
    const { api } = loadClient();

    const { response } = await api.GET('/v1/me');
    expect(response.status).toBe(401);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('does not retry other errors', async () => {
    mockEnsure.mockResolvedValue('tok');
    fetchMock.mockResolvedValueOnce(unauthorized('something_else'));
    const { api } = loadClient();

    await api.GET('/v1/me');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(mockClear).not.toHaveBeenCalled();
  });

  it('a network error does not break later requests', async () => {
    mockEnsure.mockResolvedValue('tok');
    fetchMock
      .mockRejectedValueOnce(new TypeError('Network request failed'))
      .mockResolvedValueOnce(json(200, { kind: 'device', id: 'd1' }));
    const { api } = loadClient();

    await expect(api.GET('/v1/me')).rejects.toThrow('Network request failed');
    const { data } = await api.GET('/v1/me');
    expect(data).toEqual({ kind: 'device', id: 'd1' });
  });

  it('resends the request body on retry', async () => {
    mockEnsure.mockResolvedValueOnce('stale').mockResolvedValueOnce('fresh');
    fetchMock.mockResolvedValueOnce(unauthorized('invalid_token')).mockResolvedValueOnce(json(200, {}));
    const { authMiddleware } = loadClient();
    // No POST endpoint takes a token yet, so drive the middleware with an untyped client.
    const createClient = require('openapi-fetch').default;
    const raw = createClient({
      baseUrl: 'http://api.test',
      fetch: (r: Request) => globalThis.fetch(r),
    });
    raw.use(authMiddleware);

    await raw.POST('/v1/things', { body: { name: 'abc' } });
    const retried = fetchMock.mock.calls[1][0] as Request;
    expect(retried.headers.get('Authorization')).toBe('Bearer fresh');
    expect(JSON.parse(await retried.text())).toEqual({ name: 'abc' });
  });
});
