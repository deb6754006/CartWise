import { Stack } from 'expo-router';
import { act, fireEvent, renderRouter, screen } from 'expo-router/testing-library';

import ProfileScreen from '../app/(tabs)/profile';
import ClubsScreen from '../app/clubs';

// A small fake server, jest.mock calls are hoisted above the imports.
const mockServer: {
  clubs: unknown[];
  marks: string[];
  fail: boolean;
  /** While set, answers wait for it. They carry the data as it was when asked. */
  hold: Promise<void> | null;
} = {
  clubs: [],
  marks: [],
  fail: false,
  hold: null,
};
const mockPut = jest.fn();
jest.mock('../src/api/client', () => ({
  api: {
    GET: async (path: string) => {
      if (mockServer.fail) throw new TypeError('Network request failed');
      const answer =
        path === '/v1/clubs'
          ? { data: mockServer.clubs }
          : { data: { club_ids: mockServer.marks } };
      await mockServer.hold;
      return answer;
    },
    PUT: async (path: string, init: { body: { club_ids: string[] } }) => {
      mockPut(path, init);
      mockServer.marks = init.body.club_ids;
      return { data: { club_ids: init.body.club_ids } };
    },
  },
}));

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
    mockServer.fail = false;
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
