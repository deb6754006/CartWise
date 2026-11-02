import { act, renderHook, waitFor } from '@testing-library/react-native';

import { REQUEST_TIMEOUT_MS } from '../src/profile/savedSelection';
import { loadBrands, SEARCH_DEBOUNCE_MS, useBrands } from '../src/profile/useBrands';

// jest.mock calls are hoisted above the imports.
const mockGet = jest.fn();
const mockPut = jest.fn();
jest.mock('../src/api/client', () => ({
  api: {
    GET: (path: string, init: unknown) => mockGet(path, init),
    PUT: (path: string, init: unknown) => mockPut(path, init),
  },
}));

const brand = (id: string) => ({ id, name: `מותג ${id}` });
const [A, B, C] = [brand('a'), brand('b'), brand('c')];

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

const ok = (ids: string[]) => ({ data: { brands: ids.map(brand) } });
const sent = () => mockPut.mock.calls.map(([, init]) => init.body.brand_ids);
const ids = (brands: readonly { id: string }[]) => brands.map((b) => b.id);
const searches = () =>
  mockGet.mock.calls
    .filter(([path]) => path === '/v1/brands/search')
    .map(([, init]) => init.params.query.q);

function server(mine: { id: string; name: string }[] = [], found: unknown = []) {
  mockGet.mockImplementation(async (path: string) =>
    path === '/v1/me/brands' ? { data: { brands: mine } } : { data: found },
  );
}

async function ready(mine: { id: string; name: string }[] = [], found: unknown = []) {
  server(mine, found);
  const view = renderHook(() => useBrands());
  await waitFor(() => expect(view.result.current.status).toBe('ready'));
  return view;
}

describe('useBrands: loading', () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPut.mockReset();
  });
  afterEach(() => jest.useRealTimers());

  it('starts loading, then has the chosen brands', async () => {
    const { result } = await ready([A, B]);
    expect(ids(result.current.selected)).toEqual(['a', 'b']);
    expect(mockPut).not.toHaveBeenCalled();
  });

  it('a failed load is an error, and reload recovers', async () => {
    mockGet.mockResolvedValue({ error: { error: { code: 'x' } } });
    const { result } = renderHook(() => useBrands());
    await waitFor(() => expect(result.current.status).toBe('error'));

    server([A]);
    await act(async () => result.current.reload());
    expect(result.current.status).toBe('ready');
    expect(ids(result.current.selected)).toEqual(['a']);
  });

  it('a network failure on load is an error', async () => {
    mockGet.mockRejectedValue(new TypeError('Network request failed'));
    const { result } = renderHook(() => useBrands());
    await waitFor(() => expect(result.current.status).toBe('error'));
  });

  it('a GET that never answers ends in the load error', async () => {
    jest.useFakeTimers();
    mockGet.mockImplementation(unanswered);
    const { result } = renderHook(() => useBrands());
    await act(async () => jest.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS - 1));
    expect(result.current.status).toBe('loading');
    await act(async () => jest.advanceTimersByTimeAsync(1));
    expect(result.current.status).toBe('error');
  });
});

describe('useBrands: saving', () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPut.mockReset();
  });
  afterEach(() => jest.useRealTimers());

  it('add shows at once and sends the whole set', async () => {
    const { result } = await ready([A]);
    const put = deferred();
    mockPut.mockReturnValue(put.promise);

    act(() => result.current.add(B));
    expect(ids(result.current.selected)).toEqual(['a', 'b']);
    expect(sent()).toEqual([['a', 'b']]);

    await act(async () => put.resolve(ok(['a', 'b'])));
    expect(ids(result.current.selected)).toEqual(['a', 'b']);
    expect(result.current.saveFailed).toBe(false);
  });

  it('adding a brand that is already chosen sends nothing', async () => {
    const { result } = await ready([A]);
    act(() => result.current.add(A));
    expect(ids(result.current.selected)).toEqual(['a']);
    expect(mockPut).not.toHaveBeenCalled();
  });

  it('remove shows at once and sends the set without it', async () => {
    const { result } = await ready([A, B]);
    const put = deferred();
    mockPut.mockReturnValue(put.promise);

    act(() => result.current.remove('a'));
    expect(ids(result.current.selected)).toEqual(['b']);
    expect(sent()).toEqual([['b']]);
    await act(async () => put.resolve(ok(['b'])));
  });

  it('rapid changes: one request at a time, then only the latest state', async () => {
    const { result } = await ready();
    const first = deferred();
    const second = deferred();
    mockPut.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);

    act(() => result.current.add(A));
    act(() => result.current.add(B));
    act(() => result.current.add(C));
    act(() => result.current.remove('b'));
    expect(mockPut).toHaveBeenCalledTimes(1);
    expect(ids(result.current.selected)).toEqual(['a', 'c']);

    await act(async () => first.resolve(ok(['a'])));
    expect(sent()).toEqual([['a'], ['a', 'c']]);

    await act(async () => second.resolve(ok(['a', 'c'])));
    expect(mockPut).toHaveBeenCalledTimes(2);
  });

  it('changed back to what is being sent: no further request', async () => {
    const { result } = await ready();
    const put = deferred();
    mockPut.mockReturnValueOnce(put.promise);

    act(() => result.current.add(A));
    act(() => result.current.add(B));
    act(() => result.current.remove('b'));
    await act(async () => put.resolve(ok(['a'])));
    expect(mockPut).toHaveBeenCalledTimes(1);
  });

  it.each([
    ['a server error', async () => ({ error: { error: { code: 'unknown_brand' } } })],
    [
      'a network failure',
      async () => {
        throw new TypeError('Network request failed');
      },
    ],
  ])('%s: back to the last saved state, with saveFailed', async (_, failure) => {
    const { result } = await ready([A]);
    mockPut.mockImplementationOnce(failure);
    await act(async () => result.current.add(B));
    expect(ids(result.current.selected)).toEqual(['a']);
    expect(result.current.saveFailed).toBe(true);

    // The next change clears the message and saves from the saved state.
    mockPut.mockResolvedValue(ok(['a', 'c']));
    await act(async () => result.current.add(C));
    expect(result.current.saveFailed).toBe(false);
    expect(sent().at(-1)).toEqual(['a', 'c']);
  });

  it('a failed removal brings the brand back, with its name', async () => {
    const { result } = await ready([A, B]);
    mockPut.mockRejectedValueOnce(new TypeError('Network request failed'));
    await act(async () => result.current.remove('a'));
    expect(result.current.selected).toEqual([A, B]);
    expect(result.current.saveFailed).toBe(true);
  });

  it('a PUT that never answers fails the save, and blocks nothing after it', async () => {
    const { result } = await ready([A]);
    jest.useFakeTimers();
    mockPut.mockImplementationOnce(unanswered);

    act(() => result.current.add(B));
    await act(async () => jest.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS));
    expect(ids(result.current.selected)).toEqual(['a']);
    expect(result.current.saveFailed).toBe(true);

    server([A]);
    await expect(loadBrands()).resolves.toEqual([A]);
  });

  it('the save survives leaving the screen, and the next load waits for it', async () => {
    const { result, unmount } = await ready();
    const first = deferred();
    const second = deferred();
    mockPut.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    act(() => result.current.add(A));
    act(() => result.current.add(B));
    unmount();
    mockGet.mockClear();

    let loaded = false;
    const load = loadBrands().then((data) => {
      loaded = true;
      return data;
    });
    await act(async () => first.resolve(ok(['a'])));
    expect(sent()).toEqual([['a'], ['a', 'b']]);
    expect(loaded).toBe(false);
    expect(mockGet).not.toHaveBeenCalled();

    server([A, B]);
    await act(async () => second.resolve(ok(['a', 'b'])));
    await expect(load).resolves.toEqual([A, B]);
  });
});

describe('useBrands: search', () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPut.mockReset();
  });
  afterEach(() => jest.useRealTimers());

  /** Past loading, and on fake timers. */
  async function searching(mine: { id: string; name: string }[] = [], found: unknown = []) {
    const view = await ready(mine, found);
    jest.useFakeTimers();
    return view.result;
  }

  const typed = (result: { current: ReturnType<typeof useBrands> }, text: string) =>
    act(() => result.current.search(text));
  const elapse = (ms: number) => act(async () => jest.advanceTimersByTimeAsync(ms));

  it('one request after 300ms with no typing', async () => {
    const result = await searching([], [A, B]);
    typed(result, 'מו');
    await elapse(SEARCH_DEBOUNCE_MS - 1);
    typed(result, 'מות');
    await elapse(SEARCH_DEBOUNCE_MS - 1);
    expect(searches()).toEqual([]);
    expect(result.current.searchStatus).toBe('searching');

    await elapse(1);
    expect(searches()).toEqual(['מות']);
    expect(result.current.query).toBe('מות');
    expect(ids(result.current.results)).toEqual(['a', 'b']);
    expect(result.current.noResults).toBe(false);
  });

  it.each(['', 'מ', ' מ ', '   '])('%j is too short: no request and no results', async (text) => {
    const result = await searching([], [A]);
    typed(result, 'מות');
    await elapse(SEARCH_DEBOUNCE_MS);
    typed(result, text);
    expect(result.current.results).toEqual([]);
    expect(result.current.searchStatus).toBe('idle');
    mockGet.mockClear();
    await elapse(SEARCH_DEBOUNCE_MS * 2);
    expect(searches()).toEqual([]);
  });

  it('shortening the text before the wait ends cancels the request', async () => {
    const result = await searching([], [A]);
    typed(result, 'מות');
    typed(result, 'מ');
    await elapse(SEARCH_DEBOUNCE_MS * 2);
    expect(searches()).toEqual([]);
  });

  it('a chosen brand is not offered', async () => {
    const result = await searching([A], [A, B]);
    typed(result, 'מות');
    await elapse(SEARCH_DEBOUNCE_MS);
    expect(ids(result.current.results)).toEqual(['b']);
  });

  it('all the answers are chosen already: not called "not found"', async () => {
    const result = await searching([A], [A]);
    typed(result, 'מות');
    await elapse(SEARCH_DEBOUNCE_MS);
    expect(result.current.results).toEqual([]);
    expect(result.current.noResults).toBe(false);
  });

  it('an empty answer is "not found"', async () => {
    const result = await searching([], []);
    typed(result, 'מות');
    expect(result.current.noResults).toBe(false);
    await elapse(SEARCH_DEBOUNCE_MS);
    expect(result.current.noResults).toBe(true);
  });

  it('an old answer that arrives after a new one is not shown', async () => {
    const result = await searching();
    const old = deferred();
    const fresh = deferred();
    mockGet.mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise);

    typed(result, 'ישן');
    await elapse(SEARCH_DEBOUNCE_MS);
    typed(result, 'חדש');
    await elapse(SEARCH_DEBOUNCE_MS);
    expect(searches()).toEqual(['ישן', 'חדש']);

    await act(async () => fresh.resolve({ data: [B] }));
    expect(ids(result.current.results)).toEqual(['b']);
    await act(async () => old.resolve({ data: [A] }));
    expect(ids(result.current.results)).toEqual(['b']);
  });

  it('an old failure that arrives after a new answer is not shown', async () => {
    const result = await searching();
    const old = deferred();
    mockGet.mockReturnValueOnce(old.promise).mockResolvedValueOnce({ data: [B] });

    typed(result, 'ישן');
    await elapse(SEARCH_DEBOUNCE_MS);
    typed(result, 'חדש');
    await elapse(SEARCH_DEBOUNCE_MS);
    await act(async () => old.reject(new TypeError('Network request failed')));
    expect(result.current.searchStatus).toBe('done');
    expect(ids(result.current.results)).toEqual(['b']);
  });

  it('an answer to text that was cleared meanwhile is not shown', async () => {
    const result = await searching();
    const old = deferred();
    mockGet.mockReturnValueOnce(old.promise);
    typed(result, 'מות');
    await elapse(SEARCH_DEBOUNCE_MS);
    typed(result, '');
    await act(async () => old.resolve({ data: [A] }));
    expect(result.current.results).toEqual([]);
    expect(result.current.searchStatus).toBe('idle');
  });

  it.each([
    ['a server error', async () => ({ error: { error: { code: 'x' } } })],
    [
      'a network failure',
      async () => {
        throw new TypeError('Network request failed');
      },
    ],
  ])('%s: the search failed, and the chosen brands stay', async (_, failure) => {
    const result = await searching([A]);
    mockGet.mockImplementationOnce(failure);
    typed(result, 'מות');
    await elapse(SEARCH_DEBOUNCE_MS);
    expect(result.current.searchStatus).toBe('error');
    expect(ids(result.current.selected)).toEqual(['a']);
    expect(mockPut).not.toHaveBeenCalled();
  });

  it('a search that never answers ends in the failure, and the next one works', async () => {
    const result = await searching([A]);
    mockGet.mockImplementationOnce(unanswered);
    typed(result, 'מות');
    await elapse(SEARCH_DEBOUNCE_MS + REQUEST_TIMEOUT_MS - 1);
    expect(result.current.searchStatus).toBe('searching');
    await elapse(1);
    expect(result.current.searchStatus).toBe('error');
    expect(ids(result.current.selected)).toEqual(['a']);

    mockGet.mockResolvedValueOnce({ data: [B] });
    typed(result, 'מותג');
    await elapse(SEARCH_DEBOUNCE_MS);
    expect(result.current.searchStatus).toBe('done');
    expect(ids(result.current.results)).toEqual(['b']);
  });

  it('adding clears the field and the results, and cancels nothing that was saved', async () => {
    const result = await searching([], [A, B]);
    mockPut.mockResolvedValue(ok(['a']));
    typed(result, 'מות');
    await elapse(SEARCH_DEBOUNCE_MS);
    await act(async () => result.current.add(A));
    expect(result.current.query).toBe('');
    expect(result.current.results).toEqual([]);
    expect(result.current.searchStatus).toBe('idle');
    expect(ids(result.current.selected)).toEqual(['a']);
  });

  it('a search waiting when the screen closes is not sent', async () => {
    server();
    const view = renderHook(() => useBrands());
    await waitFor(() => expect(view.result.current.status).toBe('ready'));
    jest.useFakeTimers();
    act(() => view.result.current.search('מות'));
    view.unmount();
    await act(async () => jest.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS * 2));
    expect(searches()).toEqual([]);
  });
});
