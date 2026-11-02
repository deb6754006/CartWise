import * as SecureStore from 'expo-secure-store';

import { getSavedOrigin, resolveAddress, saveOrigin } from '../src/onboarding/origin';
import { REQUEST_TIMEOUT_MS } from '../src/profile/savedSelection';

// jest.mock calls are hoisted above the imports.
const mockGet = jest.fn();
jest.mock('../src/api/client', () => ({
  api: { GET: (path: string, init: unknown) => mockGet(path, init) },
}));
jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn(),
  setItemAsync: jest.fn(),
}));

const getItem = SecureStore.getItemAsync as jest.Mock;
const setItem = SecureStore.setItemAsync as jest.Mock;

const ADDRESS = 'הרצל 1, תל אביב';
const FOUND = { data: { lat: 32.06, lng: 34.77 }, response: { status: 200 } };
const ORIGIN = { label: ADDRESS, lat: 32.06, lng: 34.77 };

describe('the starting point', () => {
  beforeEach(() => {
    jest.resetAllMocks();
  });

  describe('resolveAddress', () => {
    it('found: the entered text with the coordinates, and saves nothing', async () => {
      mockGet.mockResolvedValue(FOUND);
      await expect(resolveAddress(`  ${ADDRESS} `)).resolves.toEqual(ORIGIN);
      expect(mockGet).toHaveBeenCalledWith(
        '/v1/geo/geocode',
        expect.objectContaining({ params: { query: { q: ADDRESS } } }),
      );
      expect(setItem).not.toHaveBeenCalled();
    });

    it('404: not found', async () => {
      mockGet.mockResolvedValue({
        error: { error: { code: 'address_not_found' } },
        response: { status: 404 },
      });
      await expect(resolveAddress(ADDRESS)).resolves.toBeNull();
    });

    it('any other 404 is a failure, not "not found": a missing route, for one', async () => {
      mockGet.mockResolvedValue({
        error: { error: { code: 'not_found' } },
        response: { status: 404 },
      });
      await expect(resolveAddress(ADDRESS)).rejects.toThrow('geocode_failed');

      mockGet.mockResolvedValue({ error: '<html>', response: { status: 404 } });
      await expect(resolveAddress(ADDRESS)).rejects.toThrow('geocode_failed');
    });

    it('spaces only: null, with no request', async () => {
      await expect(resolveAddress('   ')).resolves.toBeNull();
      expect(mockGet).not.toHaveBeenCalled();
    });

    it.each([401, 422, 429, 500, 503])('%i rejects: it is not "not found"', async (status) => {
      mockGet.mockResolvedValue({ error: {}, response: { status } });
      await expect(resolveAddress(ADDRESS)).rejects.toThrow('geocode_failed');
    });

    it('an answer without usable coordinates rejects', async () => {
      mockGet.mockResolvedValue({ data: { lat: null, lng: 34 }, response: { status: 200 } });
      await expect(resolveAddress(ADDRESS)).rejects.toThrow('geocode_failed');
    });

    it('a network failure rejects', async () => {
      mockGet.mockRejectedValue(new TypeError('Network request failed'));
      await expect(resolveAddress(ADDRESS)).rejects.toThrow('Network request failed');
    });

    it('a request that gets no answer is aborted', async () => {
      jest.useFakeTimers();
      try {
        mockGet.mockImplementation(
          (_path: string, init: { signal: AbortSignal }) =>
            new Promise((_, reject) => {
              init.signal.addEventListener('abort', () => reject(new Error('aborted')));
            }),
        );
        const rejected = expect(resolveAddress(ADDRESS)).rejects.toThrow('aborted');
        await jest.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS);
        await rejected;
      } finally {
        jest.useRealTimers();
      }
    });
  });

  describe('saving and reading', () => {
    it('what was saved is what getSavedOrigin returns', async () => {
      await saveOrigin(ORIGIN);
      expect(setItem).toHaveBeenCalledWith('cartwise.origin', expect.any(String));

      getItem.mockImplementation(async () => setItem.mock.calls[0][1]);
      await expect(getSavedOrigin()).resolves.toEqual(ORIGIN);
      expect(getItem).toHaveBeenCalledWith('cartwise.origin');
    });

    it('a failed save rejects', async () => {
      setItem.mockRejectedValue(new Error('keystore'));
      await expect(saveOrigin(ORIGIN)).rejects.toThrow('keystore');
    });

    it('nothing saved: null', async () => {
      getItem.mockResolvedValue(null);
      await expect(getSavedOrigin()).resolves.toBeNull();
    });

    it('a failed read, or a damaged value: null', async () => {
      getItem.mockRejectedValue(new Error('keystore'));
      await expect(getSavedOrigin()).resolves.toBeNull();

      getItem.mockReset();
      getItem.mockResolvedValue('{not json');
      await expect(getSavedOrigin()).resolves.toBeNull();

      getItem.mockResolvedValue(JSON.stringify({ label: ADDRESS, lat: 'x', lng: 1 }));
      await expect(getSavedOrigin()).resolves.toBeNull();
    });
  });
});
