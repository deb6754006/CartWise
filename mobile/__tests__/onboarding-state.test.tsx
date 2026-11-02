import * as SecureStore from 'expo-secure-store';

// jest.mock calls are hoisted above the imports.
jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn(),
  setItemAsync: jest.fn(),
}));

const getItem = SecureStore.getItemAsync as jest.Mock;
const setItem = SecureStore.setItemAsync as jest.Mock;

/** A fresh copy of the module: "this launch" starts over. */
function freshState() {
  let state!: typeof import('../src/onboarding/state');
  jest.isolateModules(() => {
    state = require('../src/onboarding/state');
  });
  return state;
}

describe('the onboarding flag', () => {
  beforeEach(() => {
    getItem.mockReset();
    setItem.mockReset();
    setItem.mockResolvedValue(undefined);
  });

  it('no flag: not done', async () => {
    getItem.mockResolvedValue(null);
    await expect(freshState().isOnboardingDone()).resolves.toBe(false);
    expect(getItem).toHaveBeenCalledWith('cartwise.onboarding_done');
  });

  it('a saved flag: done', async () => {
    getItem.mockResolvedValue('1');
    await expect(freshState().isOnboardingDone()).resolves.toBe(true);
  });

  it('a failed read does not block: it counts as done, and does not throw', async () => {
    getItem.mockRejectedValue(new Error('keystore'));
    await expect(freshState().isOnboardingDone()).resolves.toBe(true);
  });

  it('a read that throws at once counts as done as well', async () => {
    getItem.mockImplementation(() => {
      throw new Error('keystore');
    });
    await expect(freshState().isOnboardingDone()).resolves.toBe(true);
  });

  it('a read that hangs does not leave the app waiting', async () => {
    jest.useFakeTimers();
    try {
      getItem.mockReturnValue(new Promise(() => {}));
      const state = freshState();
      const result = state.isOnboardingDone();
      await jest.advanceTimersByTimeAsync(state.FLAG_READ_TIMEOUT_MS);
      await expect(result).resolves.toBe(true);
    } finally {
      jest.useRealTimers();
    }
  });

  it('marking saves the flag, so the next launch reads it as done', async () => {
    const state = freshState();
    await state.markOnboardingDone();
    expect(setItem).toHaveBeenCalledWith('cartwise.onboarding_done', '1');

    getItem.mockImplementation(async () => setItem.mock.calls[0][1]);
    await expect(freshState().isOnboardingDone()).resolves.toBe(true);
  });

  it('a failed save does not throw, and this launch still counts as done', async () => {
    setItem.mockRejectedValue(new Error('keystore'));
    getItem.mockResolvedValue(null);
    const state = freshState();
    await expect(state.markOnboardingDone()).resolves.toBeUndefined();
    await expect(state.isOnboardingDone()).resolves.toBe(true);
    // Nothing was saved: the next launch starts onboarding again.
    await expect(freshState().isOnboardingDone()).resolves.toBe(false);
  });

  it('marking counts at once, before the save has finished', async () => {
    setItem.mockReturnValue(new Promise(() => {}));
    getItem.mockResolvedValue(null);
    const state = freshState();
    void state.markOnboardingDone();
    await expect(state.isOnboardingDone()).resolves.toBe(true);
  });
});
