import { Stack } from 'expo-router';
import { act, fireEvent, renderRouter, screen } from 'expo-router/testing-library';

import TabsLayout from '../app/(tabs)/_layout';
import HomeScreen from '../app/(tabs)/index';
import OnboardingScreen from '../app/onboarding';

// The real layout, the real flag code and a real router: only the store and the network are fake.
// jest.mock calls are hoisted above the imports.
const mockGetItem = jest.fn();
const mockSetItem = jest.fn();
jest.mock('expo-secure-store', () => ({
  getItemAsync: (key: string) => mockGetItem(key),
  setItemAsync: (key: string, value: string) => mockSetItem(key, value),
}));
jest.mock('expo-location', () => ({ requestForegroundPermissionsAsync: jest.fn() }));
jest.mock('../src/identity/session', () => ({
  getCachedSession: () => null,
  isSignedIn: async () => false,
  isSignInAvailable: () => true,
  signInWithGoogle: jest.fn(),
}));
jest.mock('../src/api/client', () => ({
  api: {
    GET: (path: string) =>
      Promise.resolve({
        data:
          path === '/v1/clubs'
            ? []
            : path === '/v1/me/clubs'
              ? { club_ids: [] }
              : { default_mode: 'car', default_minutes: 15 },
      }),
    PUT: jest.fn(),
  },
}));
// Each launch loads a fresh copy of the real module: what it keeps in memory ends with the launch.
let mockState: typeof import('../src/onboarding/state');
jest.mock('../src/onboarding/state', () => ({
  isOnboardingDone: () => mockState.isOnboardingDone(),
  markOnboardingDone: () => mockState.markOnboardingDone(),
}));

const SKIP = 'דלג';

async function launch() {
  jest.isolateModules(() => {
    mockState = jest.requireActual('../src/onboarding/state');
  });
  const router = renderRouter(
    {
      // As in the app: the same root navigator, with its replace behavior.
      _layout: () => <Stack screenOptions={{ headerShown: false }} />,
      onboarding: OnboardingScreen,
      '(tabs)/_layout': TabsLayout,
      '(tabs)/index': HomeScreen,
    },
    { initialUrl: '/' },
  );
  await act(async () => {});
  return router;
}

async function skipToTheEnd() {
  for (let i = 0; i < 4; i++) {
    // renderRouter turns on fake timers, Date included. Past the double-tap guard.
    act(() => {
      jest.advanceTimersByTime(1000);
    });
    await act(async () => {
      fireEvent.press(screen.getByRole('button', { name: SKIP }));
    });
  }
}

function expectHome(router: Awaited<ReturnType<typeof launch>>) {
  expect(router.getPathname()).toBe('/');
  expect(screen.getByText('מסך הבית')).toBeTruthy();
  expect(screen.queryByRole('button', { name: SKIP })).toBeNull();
}

let saved: Map<string, string>;

describe('onboarding, from launch to home', () => {
  beforeEach(() => {
    saved = new Map();
    mockGetItem.mockReset();
    mockGetItem.mockImplementation(async (key: string) => saved.get(key) ?? null);
    mockSetItem.mockReset();
    mockSetItem.mockImplementation(async (key: string, value: string) => {
      saved.set(key, value);
    });
  });

  it('no flag: goes to onboarding', async () => {
    const router = await launch();
    expect(router.getPathname()).toBe('/onboarding');
    expect(screen.getByRole('header', { name: 'איפה הכי משתלם לקנות?' })).toBeTruthy();
    expect(screen.queryAllByRole('tab')).toHaveLength(0);
  });

  it('finishing lands on the tabs, and stays there', async () => {
    const router = await launch();
    await skipToTheEnd();
    await act(async () => {});
    expectHome(router);
    expect(saved.get('cartwise.onboarding_done')).toBeDefined();
  });

  it('the next launch opens the tabs directly', async () => {
    await launch();
    await skipToTheEnd();
    await act(async () => {});

    const router = await launch();
    expectHome(router);
  });

  it('if saving the flag fails: still the tabs, with no redirect back', async () => {
    mockSetItem.mockRejectedValue(new Error('keystore'));
    const router = await launch();
    await skipToTheEnd();
    await act(async () => {});
    expectHome(router);
  });

  it('if saving the flag failed, the next launch starts onboarding again', async () => {
    mockSetItem.mockRejectedValue(new Error('keystore'));
    await launch();
    await skipToTheEnd();
    await act(async () => {});

    const router = await launch();
    expect(router.getPathname()).toBe('/onboarding');
  });

  it('if reading the flag fails: the tabs, with no onboarding', async () => {
    mockGetItem.mockRejectedValue(new Error('keystore'));
    const router = await launch();
    expectHome(router);
  });
});
