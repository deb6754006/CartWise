import { act, fireEvent, render, screen } from '@testing-library/react-native';
import * as SecureStore from 'expo-secure-store';
import { BackHandler } from 'react-native';

import OnboardingScreen from '../app/onboarding';

// jest.mock calls are hoisted above the imports.
const mockRouter = { push: jest.fn(), replace: jest.fn(), canGoBack: jest.fn(), back: jest.fn() };
jest.mock('expo-router', () => ({ useRouter: () => mockRouter }));
jest.mock('expo-location', () => ({
  requestForegroundPermissionsAsync: jest.fn(),
}));
jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn(),
  setItemAsync: jest.fn(),
}));
const mockGet = jest.fn();
const mockPut = jest.fn();
jest.mock('../src/api/client', () => ({
  api: {
    GET: (path: string, init: unknown) => mockGet(path, init),
    PUT: (path: string, init: unknown) => mockPut(path, init),
  },
}));

const setItem = SecureStore.setItemAsync as jest.Mock;
const { requestForegroundPermissionsAsync: requestPermission } = jest.requireMock('expo-location');

const WELCOME = 'איפה הכי משתלם לקנות?';
const ORIGIN = 'איפה אתם?';
const RANGE = 'כמה אתם מוכנים לנסוע?';
const CLUBS = 'באילו מועדונים אתם חברים?';
const CLUBS_RESPONSES: Record<string, unknown> = {
  '/v1/clubs': [{ id: 'a', name: 'מועדון רשת א׳', chain_id: 'c1', chain_name: 'רשת א׳' }],
  '/v1/me/clubs': { club_ids: [] },
  '/v1/me/prefs': { default_mode: 'car', default_minutes: 15 },
};

let now = 0;
const tap = async (name: string) => {
  await act(async () => fireEvent.press(screen.getByRole('button', { name })));
};
/** A press well after the previous one, unlike the second tap of a double tap. */
const press = async (name: string) => {
  now += 1000;
  await tap(name);
};
const skip = () => press('דלג');
const header = (name: string) => screen.queryByRole('header', { name });

async function goToStep(step: number) {
  for (let i = 0; i < step; i++) await skip();
}

function pressAndroidBack(): boolean | null | undefined {
  // The newest listener runs first, as on a device.
  const calls = addListener.mock.calls;
  return calls[calls.length - 1][1]();
}

let addListener: jest.SpyInstance;
let removeListener: jest.Mock;
let clock: jest.SpyInstance;

describe('the onboarding screen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    setItem.mockReset();
    setItem.mockResolvedValue(undefined);
    requestPermission.mockReset();
    mockGet.mockImplementation(async (path: string) => ({ data: CLUBS_RESPONSES[path] }));
    mockPut.mockImplementation(async (_path: string, init: { body: unknown }) => ({
      data: init.body,
    }));
    now = 1_000_000;
    clock = jest.spyOn(Date, 'now').mockImplementation(() => now);
    removeListener = jest.fn();
    addListener = jest
      .spyOn(BackHandler, 'addEventListener')
      .mockReturnValue({ remove: removeListener });
  });

  afterEach(() => {
    addListener.mockRestore();
    clock.mockRestore();
  });

  it('starts on the first of four steps, with the character, and no sign-in', () => {
    render(<OnboardingScreen />);
    expect(header(WELCOME)).toBeTruthy();
    expect(screen.getByTestId('mascot')).toBeTruthy();
    expect(screen.getByRole('progressbar', { name: 'שלב 1 מתוך 4' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'דלג' })).toBeTruthy();
    expect(screen.queryByText('המשך עם Google')).toBeNull();
  });

  it('"start" and "continue" move forward, with "skip" on every step', async () => {
    render(<OnboardingScreen />);
    await press('מתחילים');
    expect(header(ORIGIN)).toBeTruthy();
    expect(screen.getByRole('progressbar', { name: 'שלב 2 מתוך 4' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'דלג' })).toBeTruthy();

    await skip();
    expect(header(RANGE)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'דלג' })).toBeTruthy();

    await press('המשך');
    expect(header(CLUBS)).toBeTruthy();
    expect(screen.getByRole('progressbar', { name: 'שלב 4 מתוך 4' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'דלג' })).toBeTruthy();
    expect(screen.queryByText('המשך עם Google')).toBeNull();
  });

  it.each([
    ['skip', 'דלג'],
    ['the step button', 'מתחילים'],
  ])('a double tap on %s moves one step, not two', async (_name, label) => {
    render(<OnboardingScreen />);
    await press(label);
    expect(header(ORIGIN)).toBeTruthy();
    await tap('דלג');
    expect(header(ORIGIN)).toBeTruthy();

    await press('דלג');
    expect(header(RANGE)).toBeTruthy();
  });

  it('two taps with no render between them move one step', async () => {
    render(<OnboardingScreen />);
    now += 1000;
    const skipButton = screen.getByRole('button', { name: 'דלג' });
    await act(async () => {
      fireEvent.press(skipButton);
      fireEvent.press(skipButton);
    });
    expect(header(ORIGIN)).toBeTruthy();
  });

  it('skipping all the way changes nothing, and finishes on the last step', async () => {
    render(<OnboardingScreen />);
    await goToStep(4);

    expect(mockPut).not.toHaveBeenCalled();
    expect(requestPermission).not.toHaveBeenCalled();
    expect(setItem).toHaveBeenCalledTimes(1);
    expect(setItem).toHaveBeenCalledWith('cartwise.onboarding_done', '1');
    expect(mockRouter.replace).toHaveBeenCalledTimes(1);
    expect(mockRouter.replace).toHaveBeenCalledWith('/');
  });

  it('skipping before the last step does not finish', async () => {
    render(<OnboardingScreen />);
    await goToStep(3);
    expect(setItem).not.toHaveBeenCalled();
    expect(mockRouter.replace).not.toHaveBeenCalled();
  });

  it('"finish" saves the flag and replaces the screen with home', async () => {
    render(<OnboardingScreen />);
    await goToStep(3);
    await press('סיום');
    expect(setItem).toHaveBeenCalledWith('cartwise.onboarding_done', '1');
    expect(mockRouter.replace).toHaveBeenCalledWith('/');
    expect(mockRouter.back).not.toHaveBeenCalled();
  });

  it('a second press on "finish" does nothing more', async () => {
    render(<OnboardingScreen />);
    await goToStep(3);
    await press('סיום');
    await press('סיום');
    expect(mockRouter.replace).toHaveBeenCalledTimes(1);
  });

  it('if saving the flag fails, home opens all the same', async () => {
    setItem.mockRejectedValue(new Error('keystore'));
    render(<OnboardingScreen />);
    await goToStep(3);
    await press('סיום');
    expect(mockRouter.replace).toHaveBeenCalledWith('/');
  });

  it('Android back: the previous step, and the system on the first', async () => {
    render(<OnboardingScreen />);
    await goToStep(2);
    expect(header(RANGE)).toBeTruthy();

    let handled: boolean | null | undefined;
    await act(async () => {
      handled = pressAndroidBack();
    });
    expect(handled).toBe(true);
    expect(header(ORIGIN)).toBeTruthy();

    await act(async () => {
      handled = pressAndroidBack();
    });
    expect(handled).toBe(true);
    expect(header(WELCOME)).toBeTruthy();

    expect(pressAndroidBack()).toBe(false);
    expect(header(WELCOME)).toBeTruthy();
  });

  it('stops listening to Android back when it closes', async () => {
    const { unmount } = render(<OnboardingScreen />);
    unmount();
    expect(removeListener).toHaveBeenCalled();
  });

  it('allowing location moves to the next step', async () => {
    requestPermission.mockResolvedValue({ granted: true });
    render(<OnboardingScreen />);
    await goToStep(1);
    await press('אישור מיקום');
    expect(header(RANGE)).toBeTruthy();
    expect(mockGet).toHaveBeenCalledWith('/v1/me/prefs', expect.anything());
    for (const [, init] of mockPut.mock.calls) expect(JSON.stringify(init)).not.toContain('lat');
  });

  it('range: a choice is saved through the same request as the range screen', async () => {
    render(<OnboardingScreen />);
    await goToStep(2);
    await act(async () => fireEvent.press(screen.getByRole('radio', { name: 'הליכה' })));
    expect(mockPut).toHaveBeenCalledWith(
      '/v1/me/prefs',
      expect.objectContaining({ body: { default_mode: 'walk', default_minutes: 15 } }),
    );
  });

  it('range: no options before it loads', async () => {
    mockGet.mockReturnValue(new Promise(() => {}));
    render(<OnboardingScreen />);
    await goToStep(2);
    expect(screen.getByTestId('range-skeleton')).toBeTruthy();
    expect(screen.queryAllByRole('radio')).toHaveLength(0);
  });

  it('range: a failed load shows a message and a retry, and can be skipped', async () => {
    mockGet.mockRejectedValue(new TypeError('Network request failed'));
    render(<OnboardingScreen />);
    await goToStep(2);
    expect(screen.getByRole('alert')).toHaveTextContent('לא הצלחנו לטעון את הטווח');
    expect(screen.getByRole('button', { name: 'נסו שוב' })).toBeTruthy();
    expect(screen.queryAllByRole('radio')).toHaveLength(0);

    await skip();
    expect(header(CLUBS)).toBeTruthy();
  });

  it('clubs: the switches are there', async () => {
    render(<OnboardingScreen />);
    await goToStep(3);
    expect(screen.getByRole('switch', { name: 'מועדון רשת א׳' })).toBeTruthy();
    await act(async () => fireEvent(screen.getByRole('switch'), 'valueChange', true));
    expect(mockPut).toHaveBeenCalledWith(
      '/v1/me/clubs',
      expect.objectContaining({ body: { club_ids: ['a'] } }),
    );
  });

  it('clubs: no clubs do not block "finish"', async () => {
    mockGet.mockImplementation(async (path: string) => ({
      data: path === '/v1/clubs' ? [] : CLUBS_RESPONSES[path],
    }));
    render(<OnboardingScreen />);
    await goToStep(3);
    expect(screen.getByText('עוד אין מועדונים זמינים. הם יופיעו כאן כשנוסיף רשתות')).toBeTruthy();
    await press('סיום');
    expect(mockRouter.replace).toHaveBeenCalledWith('/');
  });

  it('clubs: a failed load does not block "finish"', async () => {
    mockGet.mockImplementation(async (path: string) => {
      if (path === '/v1/me/prefs') return { data: CLUBS_RESPONSES[path] };
      throw new TypeError('Network request failed');
    });
    render(<OnboardingScreen />);
    await goToStep(3);
    expect(screen.getByRole('alert')).toHaveTextContent('לא הצלחנו לטעון את המועדונים');
    await press('סיום');
    expect(mockRouter.replace).toHaveBeenCalledWith('/');
  });

  it('the privacy link opens the summary, and stays on the same step', async () => {
    render(<OnboardingScreen />);
    fireEvent.press(screen.getByRole('link', { name: 'סיכום הפרטיות' }));
    expect(mockRouter.push).toHaveBeenCalledWith('/privacy');
    expect(header(WELCOME)).toBeTruthy();
  });
});
