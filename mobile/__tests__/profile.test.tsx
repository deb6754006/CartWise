import { Stack } from 'expo-router';
import { act, fireEvent, renderRouter, screen } from 'expo-router/testing-library';

import ProfileScreen from '../app/(tabs)/profile';
import { SEARCH_DEBOUNCE_MS } from '../src/profile/useBrands';
import BrandsScreen from '../app/brands';
import ClubsScreen from '../app/clubs';

// A small fake server, jest.mock calls are hoisted above the imports.
const mockServer: {
  clubs: unknown[];
  marks: string[];
  brands: { id: string; name: string }[];
  fail: boolean;
  brandsFail: boolean;
  /** While set, answers wait for it. They carry the data as it was when asked. */
  hold: Promise<void> | null;
} = {
  clubs: [],
  marks: [],
  brands: [],
  fail: false,
  brandsFail: false,
  hold: null,
};
const mockPut = jest.fn();
jest.mock('../src/api/client', () => ({
  api: {
    GET: async (path: string) => {
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
    PUT: async (path: string, init: { body: { club_ids?: string[]; brand_ids?: string[] } }) => {
      mockPut(path, init);
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
    mockServer.fail = false;
    mockServer.brandsFail = false;
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
    expect(rows).toEqual(['המועדונים שלי: 0', 'מותגים רצויים: 7']);
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
