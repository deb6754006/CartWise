// jest.mock calls are hoisted above the imports.
const mockSignedIn = { value: false };
jest.mock('../src/identity/session', () => ({
  isSignedIn: async () => mockSignedIn.value,
}));

import { act, renderHook } from '@testing-library/react-native';

import { requireSignIn, settleSignIn, useSignInRequest } from '../src/identity/requireSignIn';

describe('requireSignIn', () => {
  afterEach(() => settleSignIn(null));

  it('already signed in: resolves true without opening a request', async () => {
    mockSignedIn.value = true;
    const { result } = renderHook(() => useSignInRequest());
    await act(async () => {
      await expect(requireSignIn('quota')).resolves.toBe(true);
    });
    expect(result.current).toBeNull();
  });

  it('guest: opens a request, resolved by the sheet', async () => {
    mockSignedIn.value = false;
    const { result } = renderHook(() => useSignInRequest());
    let pending!: Promise<boolean>;
    await act(async () => {
      pending = requireSignIn('scan');
    });
    expect(result.current?.reason).toBe('scan');

    act(() => settleSignIn({ userId: 'u1', firstName: null }));
    await expect(pending).resolves.toBe(true);
    expect(result.current).toBeNull();
  });

  it('a second call joins the open request (no sheet on a sheet); cancel resolves both false', async () => {
    mockSignedIn.value = false;
    let first!: Promise<boolean>;
    let second!: Promise<boolean>;
    await act(async () => {
      first = requireSignIn('scan');
    });
    await act(async () => {
      second = requireSignIn('quota');
    });
    act(() => settleSignIn(null));
    await expect(first).resolves.toBe(false);
    await expect(second).resolves.toBe(false);
  });
});
