import { act, renderHook, waitFor } from '@testing-library/react-native';

import { REQUEST_TIMEOUT_MS } from '../src/profile/savedSelection';
import { loadRange, useRange } from '../src/profile/useRange';

// jest.mock calls are hoisted above the imports.
const mockGet = jest.fn();
const mockPut = jest.fn();
jest.mock('../src/api/client', () => ({
  api: {
    GET: (path: string, init: unknown) => mockGet(path, init),
    PUT: (path: string, init: unknown) => mockPut(path, init),
  },
}));

const range = (default_mode: 'walk' | 'car', default_minutes: 5 | 10 | 15 | 20 | 30) => ({
  default_mode,
  default_minutes,
});

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

const sent = () => mockPut.mock.calls.map(([, init]) => init.body);

async function ready(loaded = range('car', 15)) {
  mockGet.mockResolvedValue({ data: loaded });
  const view = renderHook(() => useRange());
  await waitFor(() => expect(view.result.current.status).toBe('ready'));
  return view;
}

describe('useRange: loading', () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPut.mockReset();
  });
  afterEach(() => jest.useRealTimers());

  it('starts loading, then has what the server answered, sending nothing', async () => {
    mockGet.mockResolvedValue({ data: range('walk', 10) });
    const { result } = renderHook(() => useRange());
    expect(result.current.status).toBe('loading');
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.range).toEqual(range('walk', 10));
    expect(mockGet).toHaveBeenCalledWith('/v1/me/prefs', expect.anything());
    expect(mockPut).not.toHaveBeenCalled();
  });

  it('a failed load is an error, and reload recovers', async () => {
    mockGet.mockResolvedValue({ error: { error: { code: 'x' } } });
    const { result } = renderHook(() => useRange());
    await waitFor(() => expect(result.current.status).toBe('error'));

    mockGet.mockResolvedValue({ data: range('walk', 5) });
    await act(async () => result.current.reload());
    expect(result.current.status).toBe('ready');
    expect(result.current.range).toEqual(range('walk', 5));
  });

  it('a network failure on load is an error', async () => {
    mockGet.mockRejectedValue(new TypeError('Network request failed'));
    const { result } = renderHook(() => useRange());
    await waitFor(() => expect(result.current.status).toBe('error'));
  });

  it('a GET that never answers ends in the load error', async () => {
    jest.useFakeTimers();
    mockGet.mockImplementation(unanswered);
    const { result } = renderHook(() => useRange());
    await act(async () => jest.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS - 1));
    expect(result.current.status).toBe('loading');
    await act(async () => jest.advanceTimersByTimeAsync(1));
    expect(result.current.status).toBe('error');
  });

  it('loadRange rejects when the server answers with an error', async () => {
    mockGet.mockResolvedValue({ error: { error: { code: 'x' } } });
    await expect(loadRange()).rejects.toThrow('range_load_failed');
  });
});

describe('useRange: saving', () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPut.mockReset();
  });
  afterEach(() => jest.useRealTimers());

  it('a mode shows at once, and both values are sent', async () => {
    const { result } = await ready();
    const put = deferred();
    mockPut.mockReturnValue(put.promise);

    act(() => result.current.setMode('walk'));
    expect(result.current.range).toEqual(range('walk', 15));
    expect(sent()).toEqual([range('walk', 15)]);

    await act(async () => put.resolve({ data: range('walk', 15) }));
    expect(result.current.saveFailed).toBe(false);
  });

  it('minutes show at once, and both values are sent', async () => {
    const { result } = await ready(range('walk', 10));
    mockPut.mockResolvedValue({ data: range('walk', 30) });
    await act(async () => result.current.setMinutes(30));
    expect(result.current.range).toEqual(range('walk', 30));
    expect(sent()).toEqual([range('walk', 30)]);
  });

  it('changing the mode keeps the minutes', async () => {
    const { result } = await ready(range('car', 20));
    mockPut.mockResolvedValue({ data: {} });
    await act(async () => result.current.setMode('walk'));
    expect(result.current.range.default_minutes).toBe(20);
    await act(async () => result.current.setMode('car'));
    expect(result.current.range).toEqual(range('car', 20));
  });

  it('choosing what is already chosen sends nothing', async () => {
    const { result } = await ready(range('car', 15));
    await act(async () => {
      result.current.setMode('car');
      result.current.setMinutes(15);
    });
    expect(mockPut).not.toHaveBeenCalled();
  });

  it('quick changes: at most one request runs, and the last state is sent when it ends', async () => {
    const { result } = await ready();
    const first = deferred();
    const second = deferred();
    mockPut.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);

    act(() => result.current.setMode('walk'));
    act(() => result.current.setMinutes(5));
    act(() => result.current.setMinutes(10));
    expect(sent()).toEqual([range('walk', 15)]);
    expect(result.current.range).toEqual(range('walk', 10));

    await act(async () => first.resolve({ data: {} }));
    expect(sent()).toEqual([range('walk', 15), range('walk', 10)]);

    await act(async () => second.resolve({ data: {} }));
    expect(sent()).toHaveLength(2);
    expect(result.current.range).toEqual(range('walk', 10));
    expect(result.current.saveFailed).toBe(false);
  });

  it('changing back while saving ends with what the server was last sent', async () => {
    const { result } = await ready(range('car', 15));
    const first = deferred();
    mockPut.mockReturnValueOnce(first.promise).mockResolvedValue({ data: {} });

    act(() => result.current.setMode('walk'));
    act(() => result.current.setMode('car'));
    await act(async () => first.resolve({ data: {} }));

    expect(sent()).toEqual([range('walk', 15), range('car', 15)]);
    expect(result.current.range).toEqual(range('car', 15));
  });

  it('a failed save goes back to the last saved state, and says so', async () => {
    const { result } = await ready(range('car', 15));
    mockPut.mockResolvedValue({ error: { error: { code: 'x' } } });
    await act(async () => result.current.setMode('walk'));
    expect(result.current.range).toEqual(range('car', 15));
    expect(result.current.saveFailed).toBe(true);
  });

  it('a save that fails after an earlier one succeeded goes back to the one that succeeded', async () => {
    const { result } = await ready(range('car', 15));
    mockPut.mockResolvedValueOnce({ data: {} });
    await act(async () => result.current.setMinutes(20));
    mockPut.mockRejectedValueOnce(new TypeError('Network request failed'));
    await act(async () => result.current.setMode('walk'));
    expect(result.current.range).toEqual(range('car', 20));
    expect(result.current.saveFailed).toBe(true);
  });

  it('the next change clears the failure', async () => {
    const { result } = await ready();
    mockPut.mockResolvedValueOnce({ error: {} });
    await act(async () => result.current.setMode('walk'));
    expect(result.current.saveFailed).toBe(true);

    mockPut.mockResolvedValue({ data: {} });
    await act(async () => result.current.setMinutes(5));
    expect(result.current.saveFailed).toBe(false);
    expect(result.current.range).toEqual(range('car', 5));
  });

  it('a PUT that never answers ends in the save error', async () => {
    const { result } = await ready();
    jest.useFakeTimers();
    mockPut.mockImplementation(unanswered);
    act(() => result.current.setMode('walk'));
    await act(async () => jest.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS));
    expect(result.current.range).toEqual(range('car', 15));
    expect(result.current.saveFailed).toBe(true);
  });

  it('a load waits for the save in progress, so it reads what was just saved', async () => {
    const { result, unmount } = await ready();
    const put = deferred();
    mockPut.mockReturnValue(put.promise);
    act(() => result.current.setMode('walk'));
    unmount();

    mockGet.mockClear();
    mockGet.mockResolvedValue({ data: range('walk', 15) });
    const loading = loadRange();
    await act(async () => {});
    expect(mockGet).not.toHaveBeenCalled();

    await act(async () => put.resolve({ data: {} }));
    await expect(loading).resolves.toEqual(range('walk', 15));
  });
});
