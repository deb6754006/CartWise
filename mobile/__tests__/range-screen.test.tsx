import { act, fireEvent, render, screen } from '@testing-library/react-native';

import RangeScreen from '../app/range';

// jest.mock calls are hoisted above the imports.
const mockRouter = { canGoBack: jest.fn(() => true), back: jest.fn(), replace: jest.fn() };
jest.mock('expo-router', () => ({ useRouter: () => mockRouter }));
const mockGet = jest.fn();
const mockPut = jest.fn();
jest.mock('../src/api/client', () => ({
  api: {
    GET: (path: string, init: unknown) => mockGet(path, init),
    PUT: (path: string, init: unknown) => mockPut(path, init),
  },
}));

const LOAD_FAILED = 'לא הצלחנו לטעון את הטווח';
const SAVE_FAILED = 'לא הצלחנו לשמור. נסו שוב';
const HINT = '💡 זמן הנסיעה לא משנה את הדירוג. הוא רק קובע אילו חנויות נכנסות להשוואה.';

const radio = (name: string, checked?: boolean) =>
  screen.queryByRole('radio', checked === undefined ? { name } : { name, checked });

async function renderScreen() {
  render(<RangeScreen />);
  await act(async () => {});
}

describe('the default range screen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockRouter.canGoBack.mockReturnValue(true);
    mockGet.mockResolvedValue({ data: { default_mode: 'car', default_minutes: 15 } });
    mockPut.mockImplementation(async (_path: string, init: { body: unknown }) => ({
      data: init.body,
    }));
  });

  it('has its title, the choice from the server, the explanation, and no sign-in', async () => {
    mockGet.mockResolvedValue({ data: { default_mode: 'walk', default_minutes: 10 } });
    await renderScreen();
    expect(screen.getByRole('header', { name: 'טווח ברירת מחדל' })).toBeTruthy();
    expect(radio('הליכה', true)).toBeTruthy();
    expect(radio('10 דקות', true)).toBeTruthy();
    expect(screen.getByText(HINT)).toBeTruthy();
    expect(screen.queryByText('המשך עם Google')).toBeNull();
    expect(mockPut).not.toHaveBeenCalled();
  });

  it('loading: a skeleton, with no options', () => {
    mockGet.mockReturnValue(new Promise(() => {}));
    render(<RangeScreen />);
    expect(screen.getByTestId('range-skeleton')).toBeTruthy();
    expect(screen.queryAllByRole('radio')).toHaveLength(0);
  });

  it('load failed: a message and a retry, with no options, and retry recovers', async () => {
    mockGet.mockRejectedValue(new TypeError('Network request failed'));
    await renderScreen();
    expect(screen.getByRole('alert')).toHaveTextContent(LOAD_FAILED);
    expect(screen.getByRole('alert').props.accessibilityLiveRegion).toBe('polite');
    expect(screen.queryAllByRole('radio')).toHaveLength(0);
    expect(screen.queryByText(HINT)).toBeNull();

    mockGet.mockResolvedValue({ data: { default_mode: 'walk', default_minutes: 5 } });
    await act(async () => fireEvent.press(screen.getByRole('button', { name: 'נסו שוב' })));
    expect(screen.queryByText(LOAD_FAILED)).toBeNull();
    expect(radio('5 דקות', true)).toBeTruthy();
  });

  it('a choice shows at once and sends both values, keeping the minutes', async () => {
    await renderScreen();
    await act(async () => fireEvent.press(radio('הליכה')!));
    expect(radio('הליכה', true)).toBeTruthy();
    expect(radio('15 דקות', true)).toBeTruthy();
    expect(mockPut).toHaveBeenCalledTimes(1);
    expect(mockPut).toHaveBeenCalledWith(
      '/v1/me/prefs',
      expect.objectContaining({ body: { default_mode: 'walk', default_minutes: 15 } }),
    );

    await act(async () => fireEvent.press(radio('10 דקות')!));
    expect(radio('10 דקות', true)).toBeTruthy();
    expect(radio('הליכה', true)).toBeTruthy();
    expect(mockPut).toHaveBeenLastCalledWith(
      '/v1/me/prefs',
      expect.objectContaining({ body: { default_mode: 'walk', default_minutes: 10 } }),
    );
  });

  it('save failed: back to the saved choice, with a message', async () => {
    mockPut.mockRejectedValue(new TypeError('Network request failed'));
    await renderScreen();
    await act(async () => fireEvent.press(radio('הליכה')!));
    expect(screen.getByRole('alert')).toHaveTextContent(SAVE_FAILED);
    expect(radio('רכב', true)).toBeTruthy();
    expect(radio('הליכה', true)).toBeNull();
  });

  it('public transport: nothing happens', async () => {
    await renderScreen();
    await act(async () => fireEvent.press(radio('ציבורית, בקרוב')!));
    expect(mockPut).not.toHaveBeenCalled();
    expect(radio('רכב', true)).toBeTruthy();
  });

  it('back goes back, or to the profile when there is nowhere to go back to', async () => {
    await renderScreen();
    fireEvent.press(screen.getByRole('button', { name: 'חזרה' }));
    expect(mockRouter.back).toHaveBeenCalledTimes(1);

    mockRouter.canGoBack.mockReturnValue(false);
    fireEvent.press(screen.getByRole('button', { name: 'חזרה' }));
    expect(mockRouter.replace).toHaveBeenCalledWith('/(tabs)/profile');
  });
});
