import { Stack } from 'expo-router';
import { act, fireEvent, renderRouter, screen } from 'expo-router/testing-library';
import { Alert, type AlertButton } from 'react-native';

import ProfileScreen from '../app/(tabs)/profile';
import { SEARCH_DEBOUNCE_MS } from '../src/profile/useBrands';
import BrandsScreen from '../app/brands';
import ClubsScreen from '../app/clubs';
import RangeScreen from '../app/range';

// A small fake server, jest.mock calls are hoisted above the imports.
const mockServer: {
  clubs: unknown[];
  marks: string[];
  brands: { id: string; name: string }[];
  range: { default_mode: string; default_minutes: number };
  fail: boolean;
  brandsFail: boolean;
  rangeFail: boolean;
  /** While set, answers wait for it. They carry the data as it was when asked. */
  hold: Promise<void> | null;
} = {
  clubs: [],
  marks: [],
  brands: [],
  range: { default_mode: 'car', default_minutes: 15 },
  fail: false,
  brandsFail: false,
  rangeFail: false,
  hold: null,
};
const mockPut = jest.fn();
jest.mock('../src/api/client', () => ({
  api: {
    GET: async (path: string) => {
      if (path === '/v1/me/prefs') {
        if (mockServer.rangeFail) throw new TypeError('Network request failed');
        return { data: mockServer.range };
      }
      if (path.includes('brands')) {
        if (mockServer.brandsFail) throw new TypeError('Network request failed');
        if (path === '/v1/brands/search') return { data: mockBrands };
        return { data: { brands: mockServer.brands } };
      }
      if (mockServer.fail) throw new TypeError('Network request failed');
      const answer =
        path === '/v1/clubs'
          ? { data: mockServer.clubs }
          : { data: { club_ids: mockServer.marks } };
      await mockServer.hold;
      return answer;
    },
    PUT: async (
      path: string,
      init: {
        body: {
          club_ids?: string[];
          brand_ids?: string[];
          default_mode?: string;
          default_minutes?: number;
        };
      },
    ) => {
      mockPut(path, init);
      if (path === '/v1/me/prefs') {
        mockServer.range = {
          default_mode: init.body.default_mode ?? '',
          default_minutes: init.body.default_minutes ?? 0,
        };
        return { data: mockServer.range };
      }
      if (init.body.brand_ids) {
        const ids = init.body.brand_ids;
        mockServer.brands = mockBrands.filter((brand) => ids.includes(brand.id));
        return { data: { brands: mockServer.brands } };
      }
      mockServer.marks = init.body.club_ids ?? [];
      return { data: { club_ids: mockServer.marks } };
    },
  },
}));

// The session: a guest unless a test signs in. deleteAccount is controlled per test.
type MockSession = { userId: string; firstName: string | null } | null;
const mockSession: { value: MockSession; listeners: Set<(s: MockSession) => void> } = {
  value: null,
  listeners: new Set(),
};
const mockDeleteAccount = jest.fn<Promise<{ status: 'deleted' | 'failed' }>, []>();
jest.mock('../src/identity/session', () => ({
  getCachedSession: () => mockSession.value,
  loadSession: async () => mockSession.value,
  onSessionChange: (fn: (s: MockSession) => void) => {
    mockSession.listeners.add(fn);
    return () => mockSession.listeners.delete(fn);
  },
  deleteAccount: () => mockDeleteAccount(),
}));
function mockSetSession(value: MockSession) {
  mockSession.value = value;
  for (const fn of mockSession.listeners) fn(value);
}

// With as many chosen as this by default, the brands' count is never mistaken for the clubs'.
const mockBrands = Array.from({ length: 9 }, (_, i) => ({ id: `brand-${i}`, name: `מותג ${i}` }));

const CLUBS = [
  { id: 'a', name: 'מועדון רשת א׳', chain_id: 'c1', chain_name: 'רשת א׳' },
  { id: 'b', name: 'מועדון רשת ב׳', chain_id: 'c2', chain_name: 'רשת ב׳' },
];

async function renderApp() {
  const view = renderRouter(
    {
      _layout: () => <Stack screenOptions={{ headerShown: false }} />,
      profile: ProfileScreen,
      clubs: ClubsScreen,
      brands: BrandsScreen,
      range: RangeScreen,
    },
    { initialUrl: '/profile' },
  );
  await act(async () => {});
  return view;
}

const row = (name: string) => screen.getByRole('button', { name });

describe('SCR-PROFILE', () => {
  beforeEach(() => {
    mockServer.clubs = CLUBS;
    mockServer.marks = [];
    mockServer.brands = mockBrands.slice(0, 7);
    mockServer.range = { default_mode: 'car', default_minutes: 15 };
    mockServer.fail = false;
    mockServer.brandsFail = false;
    mockServer.rangeFail = false;
    mockServer.hold = null;
    mockPut.mockReset();
  });

  it('has its title, section and the clubs row with the count', async () => {
    mockServer.marks = ['a', 'b'];
    await renderApp();
    expect(screen.getByRole('header', { name: 'פרופיל' })).toBeTruthy();
    expect(screen.getByText('ההשוואה שלי')).toBeTruthy();
    expect(screen.getByText('2 ←')).toBeTruthy();
    expect(row('המועדונים שלי: 2')).toBeTruthy();
  });

  it('does not count a stale mark', async () => {
    mockServer.marks = ['a', 'gone'];
    await renderApp();
    expect(screen.getByText('1 ←')).toBeTruthy();
  });

  it('load failed: the row is shown without a number', async () => {
    mockServer.fail = true;
    await renderApp();
    expect(row('המועדונים שלי')).toBeTruthy();
    expect(screen.getByText('←')).toBeTruthy();
  });

  it('a guest opens SCR-CLUBS with no sign-in, and the count updates on return', async () => {
    const view = await renderApp();
    expect(screen.getByText('0 ←')).toBeTruthy();

    await act(async () => fireEvent.press(row('המועדונים שלי: 0')));
    expect(view.getPathname()).toBe('/clubs');
    expect(screen.queryByText('המשך עם Google')).toBeNull();

    await act(async () =>
      fireEvent(screen.getByRole('switch', { name: 'מועדון רשת ב׳' }), 'valueChange', true),
    );
    expect(mockPut).toHaveBeenCalledWith(
      '/v1/me/clubs',
      expect.objectContaining({ body: { club_ids: ['b'] } }),
    );

    await act(async () => fireEvent.press(screen.getByRole('button', { name: 'חזרה' })));
    expect(view.getPathname()).toBe('/profile');
    expect(screen.getByText('1 ←')).toBeTruthy();

    // Back in again: the mark was kept.
    await act(async () => fireEvent.press(row('המועדונים שלי: 1')));
    const toggle = screen.getByRole('switch', { name: 'מועדון רשת ב׳' });
    expect(toggle.props.accessibilityState.checked).toBe(true);
  });

  it('a double tap on the row opens one SCR-CLUBS', async () => {
    const view = await renderApp();
    const open = row('המועדונים שלי: 0');
    await act(async () => {
      fireEvent.press(open);
      fireEvent.press(open);
    });
    expect(view.getPathname()).toBe('/clubs');

    // One "back" is enough to reach the profile: there is no second screen under this one.
    const backs = screen.getAllByRole('button', { name: 'חזרה' });
    await act(async () => fireEvent.press(backs[backs.length - 1]));
    expect(view.getPathname()).toBe('/profile');
  });

  it('the brands row comes after the clubs row, with the count', async () => {
    await renderApp();
    expect(screen.getByText('7 ←')).toBeTruthy();
    const rows = screen.getAllByRole('button').map((r) => r.props.accessibilityLabel);
    expect(rows).toEqual([
      'המועדונים שלי: 0',
      'מותגים רצויים: 7',
      'טווח ברירת מחדל: רכב, 15 דקות',
    ]);
  });

  it('the range row comes after the brands row, and shows the saved range', async () => {
    mockServer.range = { default_mode: 'walk', default_minutes: 10 };
    await renderApp();
    expect(screen.getByText('🚶 10 דק׳ ←')).toBeTruthy();
    expect(row('טווח ברירת מחדל: הליכה, 10 דקות')).toBeTruthy();
  });

  it('range load failed: the row is shown without a value, and the other rows are not hurt', async () => {
    mockServer.rangeFail = true;
    await renderApp();
    expect(row('טווח ברירת מחדל')).toBeTruthy();
    expect(screen.getByText('←')).toBeTruthy();
    expect(row('המועדונים שלי: 0')).toBeTruthy();
    expect(row('מותגים רצויים: 7')).toBeTruthy();
  });

  it('a guest chooses walking, 10 minutes with no sign-in, and the profile shows it', async () => {
    const view = await renderApp();
    expect(screen.getByText('🚗 15 דק׳ ←')).toBeTruthy();

    await act(async () => fireEvent.press(row('טווח ברירת מחדל: רכב, 15 דקות')));
    expect(view.getPathname()).toBe('/range');
    expect(screen.queryByText('המשך עם Google')).toBeNull();

    await act(async () => fireEvent.press(screen.getByRole('radio', { name: 'הליכה' })));
    await act(async () => fireEvent.press(screen.getByRole('radio', { name: '10 דקות' })));
    expect(mockPut).toHaveBeenLastCalledWith(
      '/v1/me/prefs',
      expect.objectContaining({ body: { default_mode: 'walk', default_minutes: 10 } }),
    );

    await act(async () => fireEvent.press(screen.getByRole('button', { name: 'חזרה' })));
    expect(view.getPathname()).toBe('/profile');
    expect(screen.getByText('🚶 10 דק׳ ←')).toBeTruthy();

    // Back in again: the choice was kept.
    await act(async () => fireEvent.press(row('טווח ברירת מחדל: הליכה, 10 דקות')));
    expect(screen.getByRole('radio', { name: 'הליכה', checked: true })).toBeTruthy();
    expect(screen.getByRole('radio', { name: '10 דקות', checked: true })).toBeTruthy();
  });

  it('a double tap on the range row opens one range screen', async () => {
    const view = await renderApp();
    const open = row('טווח ברירת מחדל: רכב, 15 דקות');
    await act(async () => {
      fireEvent.press(open);
      fireEvent.press(open);
    });
    expect(view.getPathname()).toBe('/range');

    const backs = screen.getAllByRole('button', { name: 'חזרה' });
    await act(async () => fireEvent.press(backs[backs.length - 1]));
    expect(view.getPathname()).toBe('/profile');
  });

  it('brands load failed: the row is shown without a number, and the clubs row is not hurt', async () => {
    mockServer.brandsFail = true;
    await renderApp();
    expect(row('מותגים רצויים')).toBeTruthy();
    expect(screen.getByText('←')).toBeTruthy();
    expect(row('המועדונים שלי: 0')).toBeTruthy();
  });

  it('a guest adds a brand with no sign-in, and it is still there after leaving', async () => {
    mockServer.brands = [];
    jest.useFakeTimers();
    const view = await renderApp();
    mockServer.marks = ['a'];
    await act(async () => fireEvent.press(row('מותגים רצויים: 0')));
    expect(view.getPathname()).toBe('/brands');
    expect(screen.queryByText('המשך עם Google')).toBeNull();

    fireEvent.changeText(screen.getByLabelText('חיפוש מותג'), 'מותג');
    await act(async () => jest.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS));
    await act(async () => fireEvent.press(row('הוספת מותג 3')));
    expect(row('הסרת מותג 3')).toBeTruthy();
    expect(mockPut).toHaveBeenCalledWith(
      '/v1/me/brands',
      expect.objectContaining({ body: { brand_ids: ['brand-3'] } }),
    );

    await act(async () => fireEvent.press(screen.getByRole('button', { name: 'חזרה' })));
    expect(view.getPathname()).toBe('/profile');
    expect(row('מותגים רצויים: 1')).toBeTruthy();

    await act(async () => fireEvent.press(row('מותגים רצויים: 1')));
    expect(row('הסרת מותג 3')).toBeTruthy();
    jest.useRealTimers();
  });

  it('a double tap on the brands row opens one SCR-BRANDS', async () => {
    const view = await renderApp();
    const open = row('מותגים רצויים: 7');
    await act(async () => {
      fireEvent.press(open);
      fireEvent.press(open);
    });
    expect(view.getPathname()).toBe('/brands');

    const backs = screen.getAllByRole('button', { name: 'חזרה' });
    await act(async () => fireEvent.press(backs[backs.length - 1]));
    expect(view.getPathname()).toBe('/profile');
  });

  it('a late answer from before leaving does not overwrite the count', async () => {
    let release!: () => void;
    mockServer.hold = new Promise((resolve) => (release = resolve));
    mockServer.marks = ['a'];
    await renderApp(); // this load waits, holding the old answer: one mark

    mockServer.hold = null;
    mockServer.marks = ['a', 'b'];
    await act(async () => fireEvent.press(row('המועדונים שלי')));
    await act(async () => fireEvent.press(screen.getByRole('button', { name: 'חזרה' })));
    expect(screen.getByText('2 ←')).toBeTruthy();

    await act(async () => release());
    expect(screen.getByText('2 ←')).toBeTruthy();
    expect(screen.queryByText('1 ←')).toBeNull();
  });

  it('a failed refresh on return drops the old number', async () => {
    mockServer.marks = ['a'];
    await renderApp();
    await act(async () => fireEvent.press(row('המועדונים שלי: 1')));
    mockServer.fail = true;
    await act(async () => fireEvent.press(screen.getByRole('button', { name: 'חזרה' })));
    expect(row('המועדונים שלי')).toBeTruthy();
    expect(screen.queryByText('1 ←')).toBeNull();
  });
});

describe('SCR-PROFILE: account deletion', () => {
  let alertSpy: jest.SpyInstance;
  const SIGNED_IN = { userId: 'u1', firstName: 'דנה' };

  beforeEach(() => {
    mockServer.clubs = CLUBS;
    mockServer.marks = [];
    mockServer.brands = [];
    mockServer.range = { default_mode: 'car', default_minutes: 15 };
    mockServer.fail = false;
    mockServer.brandsFail = false;
    mockServer.rangeFail = false;
    mockServer.hold = null;
    mockSession.value = SIGNED_IN;
    mockSession.listeners.clear();
    mockDeleteAccount.mockReset().mockImplementation(async () => {
      mockSetSession(null); // what signOut does
      return { status: 'deleted' };
    });
    alertSpy = jest.spyOn(Alert, 'alert').mockImplementation(() => {});
  });

  afterEach(() => {
    alertSpy.mockRestore();
    mockSession.value = null;
  });

  /** The buttons of the last confirmation shown. */
  const alertButtons = (): AlertButton[] => alertSpy.mock.calls.at(-1)[2];
  const pressAlert = async (text: string) => {
    const button = alertButtons().find((b) => b.text === text);
    await act(async () => button?.onPress?.());
  };
  const deleteRow = () => screen.queryByRole('button', { name: 'מחיקת חשבון' });

  it('a guest has no account section and no delete row', async () => {
    mockSession.value = null;
    await renderApp();
    expect(screen.queryByText('חשבון ופרטיות')).toBeNull();
    expect(deleteRow()).toBeNull();
  });

  it('a signed-in user has the row, in the error color, after the comparison rows', async () => {
    await renderApp();
    expect(screen.getByText('חשבון ופרטיות')).toBeTruthy();
    expect(screen.getByText('מחיקת חשבון')).toHaveStyle({ color: '#B91C1C' });
    const rows = screen.getAllByRole('button').map((r) => r.props.accessibilityLabel);
    expect(rows.at(-1)).toBe('מחיקת חשבון');
    expect(rows).toHaveLength(4); // no sign-out row, nothing else
  });

  it('the press asks first, explaining what is deleted and what is kept', async () => {
    await renderApp();
    await act(async () => fireEvent.press(deleteRow()!));
    expect(alertSpy).toHaveBeenCalledTimes(1);
    const [title, body] = alertSpy.mock.calls[0];
    expect(title).toBe('למחוק את החשבון?');
    expect(body).toContain('30 יום');
    expect(body).toContain('יישארו');
    expect(alertButtons().map((b) => [b.text, b.style])).toEqual([
      ['ביטול', 'cancel'],
      ['מחיקה', 'destructive'],
    ]);
    expect(mockDeleteAccount).not.toHaveBeenCalled();
  });

  it('cancel: no request and no change', async () => {
    await renderApp();
    await act(async () => fireEvent.press(deleteRow()!));
    await pressAlert('ביטול');
    expect(mockDeleteAccount).not.toHaveBeenCalled();
    expect(deleteRow()).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('confirm and 204: "account deleted", and the row is gone', async () => {
    await renderApp();
    await act(async () => fireEvent.press(deleteRow()!));
    await pressAlert('מחיקה');
    expect(mockDeleteAccount).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('alert')).toHaveTextContent(
      'החשבון נמחק. אפשר להמשיך להשתמש באפליקציה כאורח',
    );
    expect(deleteRow()).toBeNull();
    expect(screen.queryByText('חשבון ופרטיות')).toBeNull();
    // The comparison rows are still there, for the guest.
    expect(row('המועדונים שלי: 0')).toBeTruthy();
  });

  it('server failed: "try again", and still signed in', async () => {
    mockDeleteAccount.mockResolvedValue({ status: 'failed' });
    await renderApp();
    await act(async () => fireEvent.press(deleteRow()!));
    await pressAlert('מחיקה');
    expect(screen.getByRole('alert')).toHaveTextContent('לא הצלחנו למחוק את החשבון. נסו שוב');
    expect(deleteRow()).toBeTruthy();

    // Another try may succeed.
    mockDeleteAccount.mockImplementation(async () => {
      mockSetSession(null);
      return { status: 'deleted' };
    });
    await act(async () => fireEvent.press(deleteRow()!));
    await pressAlert('מחיקה');
    expect(screen.getByRole('alert')).toHaveTextContent(/^החשבון נמחק/);
    expect(mockDeleteAccount).toHaveBeenCalledTimes(2);
  });

  it('confirm twice: one request, and the row is busy meanwhile', async () => {
    let finish!: () => void;
    mockDeleteAccount.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = () => {
            mockSetSession(null);
            resolve({ status: 'deleted' });
          };
        }),
    );
    await renderApp();
    await act(async () => fireEvent.press(deleteRow()!));
    const confirm = alertButtons().find((b) => b.text === 'מחיקה')!;
    await act(async () => {
      confirm.onPress?.();
      confirm.onPress?.();
    });
    expect(mockDeleteAccount).toHaveBeenCalledTimes(1);
    expect(screen.getByText('מוחקים את החשבון...')).toBeTruthy();
    expect(deleteRow()).toBeDisabled();

    // A press on the busy row asks nothing.
    await act(async () => fireEvent.press(deleteRow()!));
    expect(alertSpy).toHaveBeenCalledTimes(1);

    await act(async () => finish());
    expect(mockDeleteAccount).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('alert')).toHaveTextContent(/^החשבון נמחק/);
  });

  it('signing in while on the screen shows the row', async () => {
    mockSession.value = null;
    await renderApp();
    expect(deleteRow()).toBeNull();
    await act(async () => mockSetSession(SIGNED_IN));
    expect(deleteRow()).toBeTruthy();
  });

  it('deleteAccount rejects: the row is usable again, with "try again"', async () => {
    mockDeleteAccount.mockRejectedValue(new Error('unexpected'));
    await renderApp();
    await act(async () => fireEvent.press(deleteRow()!));
    await pressAlert('מחיקה');
    expect(deleteRow()).not.toBeDisabled();
    expect(screen.getByText('מחיקת חשבון')).toBeTruthy(); // not "deleting..."
    expect(screen.getByRole('alert')).toHaveTextContent('לא הצלחנו למחוק את החשבון. נסו שוב');

    // It can be pressed again.
    await act(async () => fireEvent.press(deleteRow()!));
    expect(alertSpy).toHaveBeenCalledTimes(2);
  });

  it('signing in again after a delete clears the "account deleted" notice', async () => {
    await renderApp();
    await act(async () => fireEvent.press(deleteRow()!));
    await pressAlert('מחיקה');
    expect(screen.getByRole('alert')).toHaveTextContent(/^החשבון נמחק/);

    await act(async () => mockSetSession(SIGNED_IN));
    expect(deleteRow()).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
