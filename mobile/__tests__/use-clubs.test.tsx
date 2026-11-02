import { act, renderHook, waitFor } from '@testing-library/react-native';

import { CLUBS_TIMEOUT_MS, loadClubs, useClubs } from '../src/profile/useClubs';

// jest.mock calls are hoisted above the imports.
const mockGet = jest.fn();
const mockPut = jest.fn();
jest.mock('../src/api/client', () => ({
  api: {
    GET: (path: string, init: { signal: AbortSignal }) => mockGet(path, init),
    PUT: (path: string, init: { body: { club_ids: string[] }; signal: AbortSignal }) =>
      mockPut(path, init),
  },
}));

const club = (id: string) => ({ id, name: `מועדון ${id}`, chain_id: `c-${id}`, chain_name: id });
const CLUBS = [club('a'), club('b'), club('c')];

function server(clubs: unknown[] = CLUBS, clubIds: string[] = []) {
  mockGet.mockImplementation(async (path: string) =>
    path === '/v1/clubs' ? { data: clubs } : { data: { club_ids: clubIds } },
  );
}

function deferred() {
  let resolve!: (value: unknown) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/** A request nobody answers: it ends only when it is aborted, as fetch does. */
const unanswered = (_path: string, { signal }: { signal: AbortSignal }) =>
  new Promise((_resolve, reject) => {
    signal.addEventListener('abort', () => reject(new Error('Aborted')));
  });

const ok = (ids: string[]) => ({ data: { club_ids: ids } });
const sent = () => mockPut.mock.calls.map(([, init]) => [...init.body.club_ids].sort());
const ids = (selected: ReadonlySet<string>) => [...selected].sort();

async function ready(clubIds: string[] = []) {
  server(CLUBS, clubIds);
  const view = renderHook(() => useClubs());
  await waitFor(() => expect(view.result.current.status).toBe('ready'));
  return view;
}

describe('useClubs', () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPut.mockReset();
  });
  afterEach(() => jest.useRealTimers());

  it.each(['/v1/clubs', '/v1/me/clubs'])(
    'a GET of %s that never answers ends in the load error, and reload recovers',
    async (path) => {
      jest.useFakeTimers();
      mockGet.mockImplementation((requested, init) =>
        requested === path
          ? unanswered(requested, init)
          : Promise.resolve({ data: requested === '/v1/clubs' ? [] : { club_ids: [] } }),
      );
      const { result } = renderHook(() => useClubs());
      await act(async () => jest.advanceTimersByTimeAsync(CLUBS_TIMEOUT_MS - 1));
      expect(result.current.status).toBe('loading');
      await act(async () => jest.advanceTimersByTimeAsync(1));
      expect(result.current.status).toBe('error');

      server(CLUBS, ['a']);
      await act(async () => result.current.reload());
      expect(result.current.status).toBe('ready');
    },
  );

  it('a PUT that never answers fails the save, and blocks nothing after it', async () => {
    const { result } = await ready(['a']);
    jest.useFakeTimers();
    mockPut.mockImplementationOnce(unanswered);

    act(() => result.current.toggle('b'));
    await act(async () => jest.advanceTimersByTimeAsync(CLUBS_TIMEOUT_MS - 1));
    expect(ids(result.current.selected)).toEqual(['a', 'b']);
    expect(result.current.saveFailed).toBe(false);
    await act(async () => jest.advanceTimersByTimeAsync(1));
    expect(ids(result.current.selected)).toEqual(['a']);
    expect(result.current.saveFailed).toBe(true);

    // A later load does not wait for it...
    server(CLUBS, ['a']);
    await expect(loadClubs()).resolves.toEqual({ clubs: CLUBS, clubIds: ['a'] });
    // ...and a later toggle sends again.
    mockPut.mockResolvedValue(ok(['a', 'c']));
    await act(async () => result.current.toggle('c'));
    expect(sent().at(-1)).toEqual(['a', 'c']);
    expect(result.current.saveFailed).toBe(false);
  });

  it('starts loading, then has the clubs and the marks', async () => {
    const { result } = await ready(['b']);
    expect(result.current.clubs).toEqual(CLUBS);
    expect(ids(result.current.selected)).toEqual(['b']);
    expect(mockPut).not.toHaveBeenCalled();
  });

  it.each([
    ['clubs', '/v1/clubs'],
    ['marks', '/v1/me/clubs'],
  ])('a failed load of the %s is an error, and reload recovers', async (_, failing) => {
    mockGet.mockImplementation(async (path: string) =>
      path === failing ? { error: { error: { code: 'x' } } } : { data: [] },
    );
    const { result } = renderHook(() => useClubs());
    await waitFor(() => expect(result.current.status).toBe('error'));

    server(CLUBS, ['a']);
    await act(async () => result.current.reload());
    expect(result.current.status).toBe('ready');
    expect(ids(result.current.selected)).toEqual(['a']);
  });

  it('a network failure on load is an error', async () => {
    mockGet.mockRejectedValue(new TypeError('Network request failed'));
    const { result } = renderHook(() => useClubs());
    await waitFor(() => expect(result.current.status).toBe('error'));
  });

  it('a toggle shows at once and sends the whole set', async () => {
    const { result } = await ready(['a']);
    const put = deferred();
    mockPut.mockReturnValue(put.promise);

    act(() => result.current.toggle('b'));
    expect(ids(result.current.selected)).toEqual(['a', 'b']);
    expect(sent()).toEqual([['a', 'b']]);

    await act(async () => put.resolve(ok(['a', 'b'])));
    expect(ids(result.current.selected)).toEqual(['a', 'b']);
    expect(result.current.saveFailed).toBe(false);
  });

  it('toggling off sends the set without it', async () => {
    const { result } = await ready(['a', 'b']);
    mockPut.mockResolvedValue(ok(['b']));
    await act(async () => result.current.toggle('a'));
    expect(sent()).toEqual([['b']]);
  });

  it('rapid toggles: one request at a time, then only the latest state', async () => {
    const { result } = await ready();
    const first = deferred();
    const second = deferred();
    mockPut.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);

    act(() => result.current.toggle('a'));
    act(() => result.current.toggle('b'));
    act(() => result.current.toggle('c'));
    expect(mockPut).toHaveBeenCalledTimes(1);
    expect(ids(result.current.selected)).toEqual(['a', 'b', 'c']);

    await act(async () => first.resolve(ok(['a'])));
    expect(sent()).toEqual([['a'], ['a', 'b', 'c']]);

    await act(async () => second.resolve(ok(['a', 'b', 'c'])));
    expect(mockPut).toHaveBeenCalledTimes(2);
  });

  it('toggled back to what is being sent: no further request', async () => {
    const { result } = await ready();
    const put = deferred();
    mockPut.mockReturnValueOnce(put.promise);

    act(() => result.current.toggle('a'));
    act(() => result.current.toggle('b'));
    act(() => result.current.toggle('b'));
    await act(async () => put.resolve(ok(['a'])));
    expect(mockPut).toHaveBeenCalledTimes(1);
  });

  it('a toggle after the save ended starts a new one', async () => {
    const { result } = await ready();
    mockPut.mockResolvedValue(ok([]));
    await act(async () => result.current.toggle('a'));
    await act(async () => result.current.toggle('b'));
    expect(sent()).toEqual([['a'], ['a', 'b']]);
  });

  it.each([
    ['a server error', async () => ({ error: { error: { code: 'x' } } })],
    [
      'a network failure',
      async () => {
        throw new TypeError('Network request failed');
      },
    ],
  ])('%s: back to the last saved state, with saveFailed', async (_, failure) => {
    const { result } = await ready(['a']);
    mockPut.mockImplementationOnce(failure);
    await act(async () => result.current.toggle('b'));
    expect(ids(result.current.selected)).toEqual(['a']);
    expect(result.current.saveFailed).toBe(true);

    // The next toggle clears the message and saves from the saved state.
    mockPut.mockResolvedValue(ok(['a', 'c']));
    await act(async () => result.current.toggle('c'));
    expect(result.current.saveFailed).toBe(false);
    expect(sent().at(-1)).toEqual(['a', 'c']);
  });

  it('a failure after a success goes back to what the success saved', async () => {
    const { result } = await ready();
    const first = deferred();
    const second = deferred();
    mockPut.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);

    act(() => result.current.toggle('a'));
    act(() => result.current.toggle('b'));
    await act(async () => first.resolve(ok(['a'])));
    await act(async () => second.reject(new TypeError('Network request failed')));
    expect(ids(result.current.selected)).toEqual(['a']);
    expect(result.current.saveFailed).toBe(true);
  });

  it('a stale mark is not selected and not sent', async () => {
    const { result } = await ready(['a', 'gone']);
    expect(ids(result.current.selected)).toEqual(['a']);
    mockPut.mockResolvedValue(ok(['a', 'b']));
    await act(async () => result.current.toggle('b'));
    expect(sent()).toEqual([['a', 'b']]);
  });

  it('the save survives leaving the screen, and the next load waits for it', async () => {
    const { result, unmount } = await ready();
    const first = deferred();
    const second = deferred();
    mockPut.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    act(() => result.current.toggle('a'));
    act(() => result.current.toggle('b'));
    unmount();
    mockGet.mockClear();

    let loaded = false;
    const load = loadClubs().then((data) => {
      loaded = true;
      return data;
    });
    await act(async () => first.resolve(ok(['a'])));
    expect(sent()).toEqual([['a'], ['a', 'b']]); // the latest state was still sent
    expect(loaded).toBe(false);
    expect(mockGet).not.toHaveBeenCalled();

    server(CLUBS, ['a', 'b']);
    await act(async () => second.resolve(ok(['a', 'b'])));
    await expect(load).resolves.toEqual({ clubs: CLUBS, clubIds: ['a', 'b'] });
  });
});
