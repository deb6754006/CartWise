// jest.mock calls are hoisted above the imports.
const mockStore = new Map<string, string>();
const mockExtra: { googleWebClientId?: string } = {};
const mockEnsureDevice = jest.fn<Promise<string | null>, []>();

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
  credential: jest.fn((idToken: string) => ({ providerId: 'google.com', token: idToken })),
  signInWithCredential: jest.fn(async (_auth: unknown, _credential: unknown) => {
    mockAuthInstance.currentUser = mockFirebaseUser;
    return { user: mockFirebaseUser };
  }),
  getIdToken: jest.fn(async (_user: unknown, force?: boolean) =>
    force ? 'firebase-id-token-fresh' : 'firebase-id-token',
  ),
  signOut: jest.fn(async (_auth?: unknown) => {
    mockAuthInstance.currentUser = null;
  }),
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
  ensureDeviceToken: () => mockEnsureDevice(),
}));
jest.mock('@react-native-google-signin/google-signin', () => ({
  GoogleSignin: mockGoogle,
  statusCodes: { SIGN_IN_CANCELLED: 'SIGN_IN_CANCELLED' },
  isCancelledResponse: (r: { type: string }) => r.type === 'cancelled',
}));
const mockNativeMissing = { value: false };
const mockAuthListeners: ((user: unknown) => void)[] = [];
jest.mock('@react-native-firebase/auth', () => {
  if (mockNativeMissing.value) throw new Error('native module RNFBAuthModule not found');
  return {
  getAuth: () => mockFirebase.getAuth(),
  GoogleAuthProvider: { credential: (t: string) => mockFirebase.credential(t) },
  signInWithCredential: (a: unknown, c: unknown) => mockFirebase.signInWithCredential(a, c),
  getIdToken: (u: unknown, f?: boolean) => mockFirebase.getIdToken(u, f),
  signOut: (a: unknown) => mockFirebase.signOut(a),
  onAuthStateChanged: (_a: unknown, fn: (user: unknown) => void) => {
    mockAuthListeners.push(fn);
    return () => {};
  },
  };
});

type SessionModule = typeof import('../src/identity/session');

const SESSION_KEY = 'cartwise.session';
const USER_ID = '0190f0e0-0000-7000-8000-0000000000aa';

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

const googleSuccess = {
  type: 'success',
  data: {
    idToken: 'google-id-token',
    user: { givenName: 'דנה', name: 'דנה כהן', email: 'dana@example.com' },
  },
};

describe('session', () => {
  let fetchMock: jest.Mock;

  beforeEach(() => {
    mockStore.clear();
    mockAuthListeners.length = 0;
    mockExtra.googleWebClientId = 'web-client.apps.googleusercontent.com';
    mockAuthInstance.currentUser = null;
    mockEnsureDevice.mockReset().mockResolvedValue('device-token');
    mockGoogle.signIn.mockReset().mockResolvedValue(googleSuccess);
    jest.clearAllMocks();
    fetchMock = jest.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
  });

  const linkRequest = () => fetchMock.mock.calls[0][0] as Request;

  it('success: Google -> Firebase -> link with the device token; saves the session', async () => {
    fetchMock.mockResolvedValueOnce(json(201, { user_id: USER_ID }));
    const s = load();
    const changes: unknown[] = [];
    s.onSessionChange((x) => changes.push(x));

    const result = await s.signInWithGoogle();

    expect(result).toEqual({ status: 'success', session: { userId: USER_ID, firstName: 'דנה' } });
    expect(mockGoogle.configure).toHaveBeenCalledWith({
      webClientId: 'web-client.apps.googleusercontent.com',
    });
    expect(mockFirebase.credential).toHaveBeenCalledWith('google-id-token');
    const req = linkRequest();
    expect(req.method).toBe('POST');
    expect(req.url).toMatch(/\/v1\/auth\/link$/);
    expect(req.headers.get('Authorization')).toBe('Bearer firebase-id-token');
    expect(await req.clone().json()).toEqual({ device_token: 'device-token' });
    // Only the user id and first name are kept, and only on this device.
    expect(JSON.parse(mockStore.get(SESSION_KEY)!)).toEqual({ userId: USER_ID, firstName: 'דנה' });
    expect(mockStore.get(SESSION_KEY)).not.toContain('dana@example.com');
    expect(changes).toEqual([{ userId: USER_ID, firstName: 'דנה' }]);
    expect(await s.isSignedIn()).toBe(true);
    expect(await s.getUserIdToken()).toBe('firebase-id-token');
    expect(await s.getUserIdToken(true)).toBe('firebase-id-token-fresh');
  });

  it('links without a device token when the device has none', async () => {
    mockEnsureDevice.mockResolvedValue(null);
    fetchMock.mockResolvedValueOnce(json(200, { user_id: USER_ID }));
    const result = await load().signInWithGoogle();
    expect(result.status).toBe('success');
    expect(await linkRequest().clone().json()).toEqual({});
  });

  it.each([
    ['a cancelled response', () => mockGoogle.signIn.mockResolvedValue({ type: 'cancelled' })],
    [
      'a SIGN_IN_CANCELLED error',
      () => mockGoogle.signIn.mockRejectedValue(Object.assign(new Error('x'), { code: 'SIGN_IN_CANCELLED' })),
    ],
  ])('cancel (%s): no server call, nothing saved', async (_name, arrange) => {
    arrange();
    const s = load();
    expect(await s.signInWithGoogle()).toEqual({ status: 'cancelled' });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(mockStore.has(SESSION_KEY)).toBe(false);
    expect(await s.isSignedIn()).toBe(false);
  });

  it.each([
    [503, { error: { code: 'auth_unavailable', message_he: 'x', details: {} } }, 'auth_unavailable'],
    [500, 'oops', 'server'],
  ])('link fails with %i: error, session not saved, signed out of Firebase', async (status, body, code) => {
    fetchMock.mockResolvedValueOnce(json(status, body));
    const s = load();
    expect(await s.signInWithGoogle()).toEqual({ status: 'error', code });
    expect(mockStore.has(SESSION_KEY)).toBe(false);
    expect(mockFirebase.signOut).toHaveBeenCalledTimes(1);
    expect(mockGoogle.signOut).toHaveBeenCalledTimes(1);
    expect(await s.isSignedIn()).toBe(false);
  });

  it('link network failure: error "network", signed out', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('Network request failed'));
    const s = load();
    expect(await s.signInWithGoogle()).toEqual({ status: 'error', code: 'network' });
    expect(mockFirebase.signOut).toHaveBeenCalled();
    expect(mockStore.has(SESSION_KEY)).toBe(false);
  });

  it('Google failure: error "google", no server call', async () => {
    mockGoogle.signIn.mockRejectedValue(Object.assign(new Error('x'), { code: 'DEVELOPER_ERROR' }));
    expect(await load().signInWithGoogle()).toEqual({ status: 'error', code: 'google' });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('not configured: unavailable, nothing called', async () => {
    mockExtra.googleWebClientId = '';
    const s = load();
    expect(s.isSignInAvailable()).toBe(false);
    expect(await s.signInWithGoogle()).toEqual({ status: 'unavailable' });
    expect(mockGoogle.signIn).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('libraries missing: unavailable', async () => {
    jest.spyOn(console, 'warn').mockImplementation(() => {});
    mockNativeMissing.value = true;
    // The libraries are required lazily, from the shared registry: drop cached copies.
    jest.resetModules();
    try {
      const s = load();
      expect(s.isSignInAvailable()).toBe(false);
      expect(await s.signInWithGoogle()).toEqual({ status: 'unavailable' });
      expect(mockGoogle.signIn).not.toHaveBeenCalled();
    } finally {
      mockNativeMissing.value = false;
      jest.resetModules();
    }
  });

  it('a stored session is read back; signOut clears it', async () => {
    mockStore.set(SESSION_KEY, JSON.stringify({ userId: USER_ID, firstName: null }));
    mockAuthInstance.currentUser = mockFirebaseUser;
    const s = load();
    expect(await s.loadSession()).toEqual({ userId: USER_ID, firstName: null });
    expect(s.getCachedSession()).toEqual({ userId: USER_ID, firstName: null });

    await s.signOut();
    expect(mockStore.has(SESSION_KEY)).toBe(false);
    expect(await s.isSignedIn()).toBe(false);
    expect(await s.getUserIdToken()).toBeNull();
  });

  it('no session: no ID token, even with a Firebase user', async () => {
    mockAuthInstance.currentUser = mockFirebaseUser;
    expect(await load().getUserIdToken()).toBeNull();
    expect(mockFirebase.getIdToken).not.toHaveBeenCalled();
  });

  it('a corrupt stored session counts as signed out', async () => {
    mockStore.set(SESSION_KEY, '{not json');
    jest.spyOn(console, 'warn').mockImplementation(() => {});
    expect(await load().isSignedIn()).toBe(false);
  });

  it('stored firstName that is not a string is ignored', async () => {
    mockStore.set(SESSION_KEY, JSON.stringify({ userId: USER_ID, firstName: { evil: true } }));
    expect(await load().loadSession()).toEqual({ userId: USER_ID, firstName: null });
  });

  it('device linked to another account (409): links again without the device token', async () => {
    fetchMock
      .mockResolvedValueOnce(
        json(409, { error: { code: 'device_already_linked', message_he: 'x', details: {} } }),
      )
      .mockResolvedValueOnce(json(200, { user_id: USER_ID }));
    const result = await load().signInWithGoogle();

    expect(result).toEqual({ status: 'success', session: { userId: USER_ID, firstName: 'דנה' } });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const second = fetchMock.mock.calls[1][0] as Request;
    expect(second.headers.get('Authorization')).toBe('Bearer firebase-id-token');
    expect(await second.clone().json()).toEqual({});
  });

  it('409 again without the device token: error, not saved', async () => {
    const conflict = () =>
      json(409, { error: { code: 'device_already_linked', message_he: 'x', details: {} } });
    fetchMock.mockResolvedValueOnce(conflict()).mockResolvedValueOnce(conflict());
    expect(await load().signInWithGoogle()).toEqual({
      status: 'error',
      code: 'device_already_linked',
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(mockStore.has(SESSION_KEY)).toBe(false);
  });

  it('link timeout: aborted after LINK_TIMEOUT_MS -> "network", signed out', async () => {
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
      const pending = s.signInWithGoogle();
      for (let i = 0; i < 100 && fetchMock.mock.calls.length === 0; i++) await Promise.resolve();
      expect(fetchMock).toHaveBeenCalledTimes(1);
      jest.advanceTimersByTime(s.LINK_TIMEOUT_MS - 1);
      await Promise.resolve();
      expect((fetchMock.mock.calls[0][0] as Request).signal.aborted).toBe(false);
      jest.advanceTimersByTime(1);
      expect(await pending).toEqual({ status: 'error', code: 'network' });
      expect(mockFirebase.signOut).toHaveBeenCalled();
      expect(mockStore.has(SESSION_KEY)).toBe(false);
    } finally {
      jest.useRealTimers();
    }
  });

  it('Google response without an ID token: error "google", no server call', async () => {
    mockGoogle.signIn.mockResolvedValue({
      type: 'success',
      data: { idToken: null, user: { givenName: 'דנה' } },
    });
    expect(await load().signInWithGoogle()).toEqual({ status: 'error', code: 'google' });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(mockFirebase.signInWithCredential).not.toHaveBeenCalled();
  });

  it('Play Services missing: error "google", Google sign-in not started', async () => {
    mockGoogle.hasPlayServices.mockRejectedValueOnce(
      Object.assign(new Error('no play services'), { code: 'PLAY_SERVICES_NOT_AVAILABLE' }),
    );
    expect(await load().signInWithGoogle()).toEqual({ status: 'error', code: 'google' });
    expect(mockGoogle.signIn).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  describe('startSessionSync', () => {
    const stored = { userId: USER_ID, firstName: 'דנה' };

    it('loads the stored session', async () => {
      mockStore.set(SESSION_KEY, JSON.stringify(stored));
      const s = load();
      expect(s.getCachedSession()).toBeUndefined();
      await s.startSessionSync();
      expect(s.getCachedSession()).toEqual(stored);
    });

    it('Firebase reports no user: the local session is dropped (guest again)', async () => {
      mockStore.set(SESSION_KEY, JSON.stringify(stored));
      const s = load();
      const changes: unknown[] = [];
      s.onSessionChange((x) => changes.push(x));
      await s.startSessionSync();
      expect(mockAuthListeners).toHaveLength(1);

      mockAuthListeners[0](null);
      await Promise.resolve();
      await Promise.resolve();
      expect(s.getCachedSession()).toBeNull();
      expect(mockStore.has(SESSION_KEY)).toBe(false);
      expect(await s.isSignedIn()).toBe(false);
      expect(changes).toEqual([null]);
    });

    it('Firebase reports a user: the session is kept', async () => {
      mockStore.set(SESSION_KEY, JSON.stringify(stored));
      const s = load();
      await s.startSessionSync();
      mockAuthListeners[0](mockFirebaseUser);
      await Promise.resolve();
      expect(s.getCachedSession()).toEqual(stored);
      expect(mockStore.has(SESSION_KEY)).toBe(true);
    });

    it('subscribes once, and not at all when Firebase is not set up', async () => {
      const s = load();
      await s.startSessionSync();
      await s.startSessionSync();
      expect(mockAuthListeners).toHaveLength(1);

      mockExtra.googleWebClientId = '';
      mockAuthListeners.length = 0;
      await load().startSessionSync();
      expect(mockAuthListeners).toHaveLength(0);
    });
  });
});
