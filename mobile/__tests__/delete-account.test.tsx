// deleteAccount() (Story 1.7): DELETE /v1/me, then the Firebase user, then signOut.
// jest.mock calls are hoisted above the imports.
const mockStore = new Map<string, string>();
const mockExtra: { googleWebClientId?: string } = {};

const mockGoogle = {
  configure: jest.fn(),
  hasPlayServices: jest.fn(async () => true),
  signIn: jest.fn(),
  signOut: jest.fn(async () => null),
};
const mockFirebaseUser = { uid: 'fb-uid' };
const mockAuthInstance: { currentUser: unknown } = { currentUser: null };
const mockFirebase = {
  getAuth: jest.fn(() => mockAuthInstance),
  credential: jest.fn((idToken: string) => ({
    providerId: 'google.com',
    token: idToken,
  })),
  getIdToken: jest.fn(async (_user: unknown, force?: boolean) =>
    force ? 'firebase-id-token-fresh' : 'firebase-id-token',
  ),
  signOut: jest.fn(async (_auth?: unknown) => {
    mockAuthInstance.currentUser = null;
  }),
  deleteUser: jest.fn(async (_user: unknown) => {
    mockAuthInstance.currentUser = null;
  }),
  reauthenticateWithCredential: jest.fn(async (_user: unknown, _credential: unknown) => ({
    user: mockFirebaseUser,
  })),
};

jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn(async (k: string) => mockStore.get(k) ?? null),
  setItemAsync: jest.fn(async (k: string, v: string) => {
    mockStore.set(k, v);
  }),
  deleteItemAsync: jest.fn(async (k: string) => {
    mockStore.delete(k);
  }),
}));
jest.mock('expo-constants', () => ({
  __esModule: true,
  default: { expoConfig: { extra: mockExtra } },
}));
jest.mock('../src/identity/device', () => ({
  ensureDeviceToken: async () => 'device-token',
}));
jest.mock('@react-native-google-signin/google-signin', () => ({
  GoogleSignin: mockGoogle,
  statusCodes: { SIGN_IN_CANCELLED: 'SIGN_IN_CANCELLED' },
  isCancelledResponse: (r: { type: string }) => r.type === 'cancelled',
}));
jest.mock('@react-native-firebase/auth', () => ({
  getAuth: () => mockFirebase.getAuth(),
  GoogleAuthProvider: { credential: (t: string) => mockFirebase.credential(t) },
  getIdToken: (u: unknown, f?: boolean) => mockFirebase.getIdToken(u, f),
  signOut: (a: unknown) => mockFirebase.signOut(a),
  deleteUser: (u: unknown) => mockFirebase.deleteUser(u),
  reauthenticateWithCredential: (u: unknown, c: unknown) =>
    mockFirebase.reauthenticateWithCredential(u, c),
  onAuthStateChanged: () => () => {},
}));

type SessionModule = typeof import('../src/identity/session');

const SESSION_KEY = 'cartwise.session';
const USER_ID = '0190f0e0-0000-7000-8000-0000000000aa';
const RECENT_LOGIN = Object.assign(new Error('recent login'), {
  code: 'auth/requires-recent-login',
});

function load(): SessionModule {
  let mod!: SessionModule;
  jest.isolateModules(() => {
    mod = require('../src/identity/session');
  });
  return mod;
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const noContent = () => new Response(null, { status: 204 });
const apiError = (status: number, code: string) =>
  json(status, { error: { code, message_he: 'x', details: {} } });

const googleSuccess = {
  type: 'success',
  data: { idToken: 'google-id-token', user: { givenName: 'דנה' } },
};

describe('deleteAccount', () => {
  let fetchMock: jest.Mock;

  beforeEach(() => {
    jest.clearAllMocks();
    mockStore.clear();
    mockStore.set(SESSION_KEY, JSON.stringify({ userId: USER_ID, firstName: 'דנה' }));
    mockExtra.googleWebClientId = 'web-client.apps.googleusercontent.com';
    mockAuthInstance.currentUser = mockFirebaseUser;
    mockFirebase.getAuth.mockImplementation(() => mockAuthInstance);
    mockGoogle.signIn.mockReset().mockResolvedValue(googleSuccess);
    fetchMock = jest.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    jest.spyOn(console, 'warn').mockImplementation(() => {});
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  const request = (i = 0) => fetchMock.mock.calls[i][0] as Request;

  it('204: DELETE with the ID token, then deleteUser, then signOut (guest again)', async () => {
    fetchMock.mockResolvedValueOnce(noContent());
    const s = load();
    const changes: unknown[] = [];
    s.onSessionChange((x) => changes.push(x));

    expect(await s.deleteAccount()).toEqual({ status: 'deleted' });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(request().method).toBe('DELETE');
    expect(request().url).toMatch(/\/v1\/me$/);
    expect(request().headers.get('Authorization')).toBe('Bearer firebase-id-token');
    expect(mockFirebase.deleteUser).toHaveBeenCalledWith(mockFirebaseUser);
    expect(mockFirebase.deleteUser.mock.invocationCallOrder[0]).toBeLessThan(
      mockFirebase.signOut.mock.invocationCallOrder[0],
    );
    expect(mockGoogle.signOut).toHaveBeenCalled();
    expect(mockStore.has(SESSION_KEY)).toBe(false); // the session and the first name
    expect(changes).toEqual([null]);
    expect(await s.isSignedIn()).toBe(false);
    expect(mockGoogle.signIn).not.toHaveBeenCalled();
  });

  it('Firebase wants a recent sign-in: Google again, reauthenticate, then deleteUser', async () => {
    fetchMock.mockResolvedValueOnce(noContent());
    mockFirebase.deleteUser.mockRejectedValueOnce(RECENT_LOGIN);
    const s = load();

    expect(await s.deleteAccount()).toEqual({ status: 'deleted' });

    expect(mockGoogle.signIn).toHaveBeenCalledTimes(1);
    expect(mockFirebase.credential).toHaveBeenCalledWith('google-id-token');
    expect(mockFirebase.reauthenticateWithCredential).toHaveBeenCalledWith(mockFirebaseUser, {
      providerId: 'google.com',
      token: 'google-id-token',
    });
    expect(mockFirebase.deleteUser).toHaveBeenCalledTimes(2);
    expect(mockStore.has(SESSION_KEY)).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(1); // the server is not asked again
  });

  it.each([
    ['cancelled in Google', () => mockGoogle.signIn.mockResolvedValue({ type: 'cancelled' })],
    [
      'a SIGN_IN_CANCELLED error',
      () =>
        mockGoogle.signIn.mockRejectedValue(
          Object.assign(new Error('x'), { code: 'SIGN_IN_CANCELLED' }),
        ),
    ],
    [
      'reauthenticate fails',
      () => mockFirebase.reauthenticateWithCredential.mockRejectedValueOnce(new Error('mismatch')),
    ],
  ])('recent sign-in %s: still deleted and signed out, no error', async (_name, arrange) => {
    fetchMock.mockResolvedValueOnce(noContent());
    mockFirebase.deleteUser.mockRejectedValueOnce(RECENT_LOGIN);
    arrange();
    const s = load();

    expect(await s.deleteAccount()).toEqual({ status: 'deleted' });
    expect(mockFirebase.deleteUser).toHaveBeenCalledTimes(1);
    expect(mockFirebase.signOut).toHaveBeenCalled();
    expect(mockStore.has(SESSION_KEY)).toBe(false);
  });

  it('another Firebase error: no new sign-in, still deleted and signed out', async () => {
    fetchMock.mockResolvedValueOnce(noContent());
    mockFirebase.deleteUser.mockRejectedValueOnce(
      Object.assign(new Error('x'), { code: 'auth/network-request-failed' }),
    );
    const s = load();
    expect(await s.deleteAccount()).toEqual({ status: 'deleted' });
    expect(mockGoogle.signIn).not.toHaveBeenCalled();
    expect(mockStore.has(SESSION_KEY)).toBe(false);
  });

  it.each([
    ['500', () => fetchMock.mockResolvedValueOnce(json(500, 'oops'))],
    ['503', () => fetchMock.mockResolvedValueOnce(apiError(503, 'db_unavailable'))],
    [
      '403 account_required',
      () => fetchMock.mockResolvedValueOnce(apiError(403, 'account_required')),
    ],
    ['200 (not 204)', () => fetchMock.mockResolvedValueOnce(json(200, {}))],
    ['no network', () => fetchMock.mockRejectedValueOnce(new TypeError('Network request failed'))],
  ])('server fails (%s): failed, still signed in, Firebase untouched', async (_name, arrange) => {
    arrange();
    const s = load();
    expect(await s.deleteAccount()).toEqual({ status: 'failed' });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(mockFirebase.deleteUser).not.toHaveBeenCalled();
    expect(mockFirebase.signOut).not.toHaveBeenCalled();
    expect(mockStore.has(SESSION_KEY)).toBe(true);
    expect(await s.isSignedIn()).toBe(true);
  });

  it('401 invalid_token: one forced refresh and one retry', async () => {
    fetchMock
      .mockResolvedValueOnce(apiError(401, 'invalid_token'))
      .mockResolvedValueOnce(noContent());
    const s = load();
    expect(await s.deleteAccount()).toEqual({ status: 'deleted' });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(request(1).headers.get('Authorization')).toBe('Bearer firebase-id-token-fresh');
  });

  it('401 invalid_token twice: failed, still signed in', async () => {
    fetchMock
      .mockResolvedValueOnce(apiError(401, 'invalid_token'))
      .mockResolvedValueOnce(apiError(401, 'invalid_token'));
    const s = load();
    expect(await s.deleteAccount()).toEqual({ status: 'failed' });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(mockStore.has(SESSION_KEY)).toBe(true);
  });

  it('timeout: aborted after DELETE_TIMEOUT_MS -> failed, still signed in', async () => {
    jest.useFakeTimers();
    try {
      fetchMock.mockImplementation(
        (req: Request) =>
          new Promise((_resolve, reject) => {
            req.signal.addEventListener('abort', () =>
              reject(Object.assign(new Error('aborted'), { name: 'AbortError' })),
            );
          }),
      );
      const s = load();
      const pending = s.deleteAccount();
      for (let i = 0; i < 100 && fetchMock.mock.calls.length === 0; i++) await Promise.resolve();
      expect(fetchMock).toHaveBeenCalledTimes(1);
      jest.advanceTimersByTime(s.DELETE_TIMEOUT_MS - 1);
      await Promise.resolve();
      expect(request().signal.aborted).toBe(false);
      jest.advanceTimersByTime(1);
      expect(await pending).toEqual({ status: 'failed' });
      expect(mockStore.has(SESSION_KEY)).toBe(true);
    } finally {
      jest.useRealTimers();
    }
  });

  it('401 not_linked (deleted already, the answer was lost): deleted, Firebase, signOut', async () => {
    fetchMock.mockResolvedValueOnce(apiError(401, 'not_linked'));
    const s = load();
    expect(await s.deleteAccount()).toEqual({ status: 'deleted' });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(mockFirebase.deleteUser).toHaveBeenCalledWith(mockFirebaseUser);
    expect(mockStore.has(SESSION_KEY)).toBe(false);
    expect(await s.isSignedIn()).toBe(false);
  });

  it('getAuth throws after the 204: warned, still deleted and signed out', async () => {
    fetchMock.mockResolvedValueOnce(noContent());
    const s = load();
    mockFirebase.getAuth.mockImplementation(() => {
      throw new Error('auth broken');
    });
    // getUserIdToken inside deleteAccount must still work: let the first read through.
    mockFirebase.getAuth.mockImplementationOnce(() => mockAuthInstance);

    expect(await s.deleteAccount()).toEqual({ status: 'deleted' });
    expect(mockFirebase.deleteUser).not.toHaveBeenCalled();
    expect(console.warn).toHaveBeenCalledWith(
      '[identity] reading the Firebase user failed:',
      'auth broken',
    );
    expect(mockStore.has(SESSION_KEY)).toBe(false);
    expect(await s.isSignedIn()).toBe(false);
  });

  it('no session (a guest): failed, no request', async () => {
    mockStore.clear();
    const s = load();
    expect(await s.deleteAccount()).toEqual({ status: 'failed' });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('a second call while one runs: one request, the same result', async () => {
    let answer!: (r: Response) => void;
    fetchMock.mockImplementationOnce(() => new Promise<Response>((r) => (answer = r)));
    const s = load();
    const first = s.deleteAccount();
    const second = s.deleteAccount();
    for (let i = 0; i < 100 && fetchMock.mock.calls.length === 0; i++) await Promise.resolve();
    answer(noContent());
    expect(await first).toEqual({ status: 'deleted' });
    expect(await second).toEqual({ status: 'deleted' });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
