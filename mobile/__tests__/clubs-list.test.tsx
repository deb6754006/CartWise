import { act, fireEvent, render, screen } from '@testing-library/react-native';
import { TextInput } from 'react-native';

import { ClubsList } from '../src/components/ClubsList';

// jest.mock calls are hoisted above the imports.
const mockGet = jest.fn();
const mockPut = jest.fn();
jest.mock('../src/api/client', () => ({
  api: {
    GET: (path: string) => mockGet(path),
    PUT: (path: string, init: unknown) => mockPut(path, init),
  },
}));

const CLUBS = [
  { id: 'a', name: 'מועדון רשת א׳', chain_id: 'c1', chain_name: 'רשת א׳' },
  { id: 'b', name: 'מועדון רשת ב׳', chain_id: 'c2', chain_name: 'רשת ב׳' },
];
const LOAD_ERROR = 'לא הצלחנו לטעון את המועדונים';
const SAVE_ERROR = 'לא הצלחנו לשמור. נסו שוב';
const PRIVACY = '🔒 לא נבקש מספר מועדון או פרטים אישיים';

function server(clubs: unknown[] = CLUBS, clubIds: string[] = []) {
  mockGet.mockImplementation(async (path: string) =>
    path === '/v1/clubs' ? { data: clubs } : { data: { club_ids: clubIds } },
  );
}

async function renderList() {
  render(<ClubsList />);
  await act(async () => {});
}

const toggle = (name: string) => screen.getByRole('switch', { name });

describe('ClubsList', () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPut.mockReset();
  });

  it('loading: a skeleton of cards, with no switches', () => {
    mockGet.mockReturnValue(new Promise(() => {}));
    render(<ClubsList />);
    expect(screen.getByTestId('clubs-skeleton')).toBeTruthy();
    expect(screen.getByRole('progressbar', { name: 'טוענים את המועדונים' })).toBeTruthy();
    expect(screen.queryAllByRole('switch')).toHaveLength(0);
  });

  it('loading for over 3 seconds also says "one moment"', () => {
    jest.useFakeTimers();
    try {
      mockGet.mockReturnValue(new Promise(() => {}));
      render(<ClubsList />);
      expect(screen.queryByText('עוד רגע...')).toBeNull();
      act(() => jest.advanceTimersByTime(3000));
      expect(screen.getByText('עוד רגע...')).toBeTruthy();
    } finally {
      jest.useRealTimers();
    }
  });

  it('shows a named switch per club, with its state, and the privacy note', async () => {
    server(CLUBS, ['b']);
    await renderList();
    expect(screen.queryByTestId('clubs-skeleton')).toBeNull();
    expect(screen.getByText('מועדון רשת א׳')).toBeTruthy();
    expect(toggle('מועדון רשת א׳').props.accessibilityState.checked).toBe(false);
    expect(toggle('מועדון רשת ב׳').props.accessibilityState.checked).toBe(true);
    expect(screen.getByText(PRIVACY)).toBeTruthy();
  });

  it('asks for nothing: no input field, and no member number in what is sent', async () => {
    server();
    mockPut.mockResolvedValue({ data: { club_ids: ['a'] } });
    await renderList();
    expect(screen.UNSAFE_queryAllByType(TextInput)).toHaveLength(0);
    await act(async () => fireEvent(toggle('מועדון רשת א׳'), 'valueChange', true));
    expect(mockPut).toHaveBeenCalledWith(
      '/v1/me/clubs',
      expect.objectContaining({ body: { club_ids: ['a'] } }),
    );
  });

  it('toggling flips the switch at once and sends the set', async () => {
    server();
    let finish!: (value: unknown) => void;
    mockPut.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    await renderList();
    fireEvent(toggle('מועדון רשת א׳'), 'valueChange', true);
    expect(toggle('מועדון רשת א׳').props.accessibilityState.checked).toBe(true);
    expect(mockPut).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(SAVE_ERROR)).toBeNull();
    await act(async () => finish({ data: { club_ids: ['a'] } }));
  });

  it('empty: the message, with no switches', async () => {
    server([], []);
    await renderList();
    expect(screen.getByText('עוד אין מועדונים זמינים. הם יופיעו כאן כשנוסיף רשתות')).toBeTruthy();
    expect(screen.queryAllByRole('switch')).toHaveLength(0);
  });

  it('load failed: a Hebrew message and "try again", with no switches', async () => {
    mockGet.mockRejectedValue(new TypeError('Network request failed'));
    await renderList();
    expect(screen.getByText(LOAD_ERROR)).toBeTruthy();
    expect(screen.queryAllByRole('switch')).toHaveLength(0);

    server();
    await act(async () => fireEvent.press(screen.getByRole('button', { name: 'נסו שוב' })));
    expect(screen.queryByText(LOAD_ERROR)).toBeNull();
    expect(screen.getAllByRole('switch')).toHaveLength(2);
  });

  it('save failed: the switch goes back, and the message shows', async () => {
    server(CLUBS, ['a']);
    mockPut.mockResolvedValue({ error: { error: { code: 'x' } } });
    await renderList();
    await act(async () => fireEvent(toggle('מועדון רשת ב׳'), 'valueChange', true));
    expect(toggle('מועדון רשת ב׳').props.accessibilityState.checked).toBe(false);
    expect(toggle('מועדון רשת א׳').props.accessibilityState.checked).toBe(true);
    expect(screen.getByRole('alert')).toHaveTextContent(SAVE_ERROR);
  });

  it('a stale mark is not shown', async () => {
    server(CLUBS, ['gone']);
    await renderList();
    expect(screen.getAllByRole('switch')).toHaveLength(2);
    expect(toggle('מועדון רשת א׳').props.accessibilityState.checked).toBe(false);
    expect(toggle('מועדון רשת ב׳').props.accessibilityState.checked).toBe(false);
  });
});
