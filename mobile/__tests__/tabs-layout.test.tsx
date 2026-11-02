import { act, fireEvent, renderRouter, screen } from 'expo-router/testing-library';
import { Text } from 'react-native';

import TabsLayout from '../app/(tabs)/_layout';
import HomeScreen from '../app/(tabs)/index';
import ListsScreen from '../app/(tabs)/lists';
import ProfileScreen from '../app/(tabs)/profile';
import ScanScreen from '../app/(tabs)/scan';
import SpendingScreen from '../app/(tabs)/spending';
import type { Session, SignInResult } from '../src/identity/session';

// jest.mock calls are hoisted above the imports.
// undefined: the stored session has not been read yet (cold start).
const mockSession: { current: Session | null | undefined } = { current: null };
const mockStored: { signedIn: boolean | null } = { signedIn: null };
const mockSignIn = jest.fn<Promise<SignInResult>, []>();
jest.mock('../src/identity/session', () => ({
  getCachedSession: () => mockSession.current,
  isSignedIn: async () => mockStored.signedIn ?? mockSession.current != null,
  isSignInAvailable: () => true,
  signInWithGoogle: () => mockSignIn(),
}));

const mockIsOnboardingDone = jest.fn<Promise<boolean>, []>();
jest.mock('../src/onboarding/state', () => ({
  isOnboardingDone: () => mockIsOnboardingDone(),
}));

const SESSION = { userId: 'u1', firstName: 'דנה' };
const SHEET_TITLE = 'כדי לסרוק ולעקוב אחרי ההוצאות, צריך להתחבר';

async function renderTabs() {
  const router = renderRouter(
    {
      onboarding: () => <Text>onboarding</Text>,
      '(tabs)/_layout': TabsLayout,
      '(tabs)/index': HomeScreen,
      '(tabs)/lists': ListsScreen,
      '(tabs)/scan': ScanScreen,
      '(tabs)/spending': SpendingScreen,
      '(tabs)/profile': ProfileScreen,
    },
    { initialUrl: '/' },
  );
  await act(async () => {}); // the Onboarding flag
  return router;
}

describe('tabs layout', () => {
  it('renders 5 tabs in order, each with a Hebrew accessibility label', async () => {
    await renderTabs();

    const tabs = screen.getAllByRole('tab');
    expect(tabs.map((tab) => tab.props.accessibilityLabel)).toEqual([
      'בית',
      'רשימות',
      'סריקה',
      'הוצאות',
      'פרופיל',
    ]);
    expect(screen.getByText('מסך הבית')).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'בית' })).toBeSelected();
    // The scan tab is the raised, round 56dp button.
    expect(screen.getByRole('tab', { name: 'סריקה' })).toHaveStyle({
      width: 56,
      height: 56,
      borderRadius: 9999,
    });
  });

  beforeEach(() => {
    mockIsOnboardingDone.mockReset();
    mockIsOnboardingDone.mockResolvedValue(true);
    mockSession.current = SESSION;
    mockStored.signedIn = null;
    mockSignIn.mockReset();
  });

  it('session not read yet but signed in: scan opens directly, no sheet', async () => {
    mockSession.current = undefined;
    mockStored.signedIn = true;
    const router = await renderTabs();
    await act(async () => fireEvent.press(screen.getByRole('tab', { name: 'סריקה' })));

    expect(router.getPathname()).toBe('/scan');
    expect(screen.getByText('סריקת קבלה')).toBeTruthy();
    expect(screen.queryByText(SHEET_TITLE)).toBeNull();
    expect(mockSignIn).not.toHaveBeenCalled();
  });

  it('switches to the scan screen when a signed-in user presses the scan tab', async () => {
    const router = await renderTabs();

    fireEvent.press(screen.getByRole('tab', { name: 'סריקה' }));

    expect(router.getPathname()).toBe('/scan');
    expect(screen.getByText('סריקת קבלה')).toBeTruthy();
    const scanTab = screen.getByRole('tab', { name: 'סריקה' });
    expect(scanTab).toBeSelected();
    expect(scanTab).toHaveStyle({ borderWidth: 3 });
    expect(screen.getByRole('tab', { name: 'בית' })).not.toBeSelected();
  });

  describe('onboarding', () => {
    it('first launch: goes to onboarding without showing the tabs first', async () => {
      mockIsOnboardingDone.mockResolvedValue(false);
      const router = renderRouter(
        {
          onboarding: () => <Text>onboarding</Text>,
          '(tabs)/_layout': TabsLayout,
          '(tabs)/index': HomeScreen,
        },
        { initialUrl: '/' },
      );
      // Before the flag is read: neither the tabs nor onboarding.
      expect(screen.queryAllByRole('tab')).toHaveLength(0);
      expect(screen.queryByText('מסך הבית')).toBeNull();
      await act(async () => {});

      expect(router.getPathname()).toBe('/onboarding');
      expect(screen.getByText('onboarding')).toBeTruthy();
      expect(screen.queryAllByRole('tab')).toHaveLength(0);
    });

    it('returning: the tabs, with no onboarding', async () => {
      const router = await renderTabs();
      expect(router.getPathname()).toBe('/');
      expect(screen.getAllByRole('tab')).toHaveLength(5);
      expect(screen.queryByText('onboarding')).toBeNull();
    });
  });

  describe('guest', () => {
    beforeEach(() => {
      mockSession.current = null;
    });

    const pressScan = async () => {
      await act(async () => fireEvent.press(screen.getByRole('tab', { name: 'סריקה' })));
    };
    const pressButton = async (name: string) => {
      await act(async () => fireEvent.press(screen.getByRole('button', { name })));
    };

    it('pressing scan opens SHEET-SIGNIN instead of the scan screen', async () => {
      const router = await renderTabs();
      await pressScan();

      expect(screen.getByText(SHEET_TITLE)).toBeTruthy();
      expect(router.getPathname()).toBe('/');
      expect(screen.queryByText('סריקת קבלה')).toBeNull();
    });

    it('"not now" closes the sheet and stays where it was', async () => {
      const router = await renderTabs();
      await pressScan();
      await pressButton('לא עכשיו');

      expect(screen.queryByText(SHEET_TITLE)).toBeNull();
      expect(router.getPathname()).toBe('/');
      expect(mockSignIn).not.toHaveBeenCalled();
    });

    it('a successful sign-in opens the scan screen', async () => {
      mockSignIn.mockImplementation(async () => {
        mockSession.current = SESSION;
        return { status: 'success', session: SESSION };
      });
      const router = await renderTabs();
      await pressScan();
      await pressButton('המשך עם Google');

      expect(router.getPathname()).toBe('/scan');
      expect(screen.getByText('סריקת קבלה')).toBeTruthy();
      expect(screen.queryByText(SHEET_TITLE)).toBeNull();
    });

    it('cancelling in Google stays where it was', async () => {
      mockSignIn.mockResolvedValue({ status: 'cancelled' });
      const router = await renderTabs();
      await pressScan();
      await pressButton('המשך עם Google');

      expect(router.getPathname()).toBe('/');
      expect(screen.queryByText(SHEET_TITLE)).toBeNull();
    });
  });
});
