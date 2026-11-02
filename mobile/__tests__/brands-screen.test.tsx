import { act, fireEvent, render, screen } from '@testing-library/react-native';
import { StyleSheet } from 'react-native';

import BrandsScreen from '../app/brands';
import { SEARCH_DEBOUNCE_MS } from '../src/profile/useBrands';
import { tokens } from '../src/theme/tokens';

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

const A = { id: 'a', name: 'מותג א׳' };
const B = { id: 'b', name: 'מותג ב׳' };

const EMPTY = 'לא בחרתם מותגים. ההשוואה תכלול כל מותג';
const NOT_FOUND = 'לא מצאנו מותג בשם הזה';
const SEARCH_FAILED = 'לא הצלחנו לחפש. נסו שוב';
const SAVE_FAILED = 'לא הצלחנו לשמור. נסו שוב';

const field = () => screen.getByLabelText('חיפוש מותג');
const tag = (name: string) => screen.queryByRole('button', { name: `הסרת ${name}` });
const result = (name: string) => screen.queryByRole('button', { name: `הוספת ${name}` });

function server(mine: unknown[] = [], found: unknown[] = []) {
  mockGet.mockImplementation(async (path: string) =>
    path === '/v1/me/brands' ? { data: { brands: mine } } : { data: found },
  );
}

async function renderScreen() {
  render(<BrandsScreen />);
  await act(async () => {});
}

async function type(text: string) {
  fireEvent.changeText(field(), text);
  await act(async () => jest.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS));
}

describe('SCR-BRANDS', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockRouter.canGoBack.mockReturnValue(true);
    mockPut.mockImplementation(async (_path: string, init: { body: { brand_ids: string[] } }) => ({
      data: { brands: init.body.brand_ids },
    }));
    server();
    jest.useFakeTimers();
  });
  afterEach(() => jest.useRealTimers());

  it('has its title, explanation, search field and empty state', async () => {
    await renderScreen();
    expect(screen.getByRole('header', { name: 'מותגים רצויים' })).toBeTruthy();
    expect(
      screen.getByText(
        'כשפריט מוגדר ״מהמותגים שלי״, נשווה רק את המותגים האלה. כך אפשר לסנן גם לפי כשרות.',
      ),
    ).toBeTruthy();
    expect(screen.getByPlaceholderText('חיפוש מותג...')).toBeTruthy();
    expect(field().props.maxLength).toBe(100);
    expect(screen.getByText(EMPTY)).toBeTruthy();
    expect(screen.queryByText('המשך עם Google')).toBeNull();
  });

  it('loading: a skeleton, with no search field', () => {
    mockGet.mockReturnValue(new Promise(() => {}));
    render(<BrandsScreen />);
    expect(screen.getByTestId('brands-skeleton')).toBeTruthy();
    expect(screen.queryByLabelText('חיפוש מותג')).toBeNull();
  });

  it('shows the chosen brands as tags, each with a named removal, and no empty state', async () => {
    server([A, B]);
    await renderScreen();
    expect(screen.getByText('מותג א׳')).toBeTruthy();
    expect(tag('מותג א׳')).toBeTruthy();
    expect(tag('מותג ב׳')).toBeTruthy();
    expect(screen.getAllByText('✕')).toHaveLength(2);
    expect(screen.queryByText(EMPTY)).toBeNull();
  });

  it('the ✕ of a tag is a full touch target, with no hitSlop', async () => {
    server([A]);
    await renderScreen();
    const remove = tag('מותג א׳')!;
    const style = StyleSheet.flatten(remove.props.style);
    expect(style.height).toBe(tokens.touchTarget);
    expect(style.width).toBe(tokens.touchTarget);
    expect(remove.props.hitSlop).toBeUndefined();
  });

  it('while searching it says so, until the answer arrives', async () => {
    await renderScreen();
    let answer!: (value: unknown) => void;
    mockGet.mockReturnValueOnce(new Promise((resolve) => (answer = resolve)));
    await type('מות');
    expect(screen.getByText('מחפשים...')).toBeTruthy();

    await act(async () => answer({ data: [B] }));
    expect(screen.queryByText('מחפשים...')).toBeNull();
    expect(result('מותג ב׳')).toBeTruthy();
  });

  it('a short text does not say it is searching', async () => {
    await renderScreen();
    fireEvent.changeText(field(), 'מ');
    expect(screen.queryByText('מחפשים...')).toBeNull();
  });

  it('load failed: a message and a retry, with no search field', async () => {
    mockGet.mockRejectedValue(new TypeError('Network request failed'));
    await renderScreen();
    expect(screen.getByRole('alert').props.accessibilityLiveRegion).toBe('polite');
    expect(screen.getByText('לא הצלחנו לטעון את המותגים')).toBeTruthy();
    expect(screen.queryByLabelText('חיפוש מותג')).toBeNull();

    server([A]);
    await act(async () => fireEvent.press(screen.getByRole('button', { name: 'נסו שוב' })));
    expect(field()).toBeTruthy();
    expect(tag('מותג א׳')).toBeTruthy();
  });

  it('search: a named result for each brand found, without one already chosen', async () => {
    server([A], [A, B]);
    await renderScreen();
    await type('מות');
    expect(result('מותג ב׳')).toBeTruthy();
    expect(result('מותג א׳')).toBeNull();
    expect(screen.queryByText(NOT_FOUND)).toBeNull();
  });

  it('a short text: no request and no message', async () => {
    await renderScreen();
    mockGet.mockClear();
    await type('מ');
    expect(mockGet).not.toHaveBeenCalled();
    expect(screen.queryByText(NOT_FOUND)).toBeNull();
    expect(screen.queryByText(SEARCH_FAILED)).toBeNull();
  });

  it('nothing found', async () => {
    await renderScreen();
    await type('אין כזה');
    expect(screen.getByText(NOT_FOUND)).toBeTruthy();
  });

  it('search failed: a message, and the chosen brands stay', async () => {
    server([A]);
    await renderScreen();
    mockGet.mockRejectedValueOnce(new TypeError('Network request failed'));
    await type('מות');
    expect(screen.getByText(SEARCH_FAILED)).toBeTruthy();
    expect(tag('מותג א׳')).toBeTruthy();
    expect(mockPut).not.toHaveBeenCalled();
  });

  it('pressing a result: a tag at once, the whole set sent, the field emptied', async () => {
    server([A], [B]);
    await renderScreen();
    await type('מות');
    await act(async () => fireEvent.press(result('מותג ב׳')!));
    expect(tag('מותג ב׳')).toBeTruthy();
    expect(mockPut).toHaveBeenCalledWith(
      '/v1/me/brands',
      expect.objectContaining({ body: { brand_ids: ['a', 'b'] } }),
    );
    expect(field().props.value).toBe('');
    expect(result('מותג ב׳')).toBeNull();
    expect(screen.queryByText(EMPTY)).toBeNull();
  });

  it('pressing ✕: the tag goes at once, and the set is sent', async () => {
    server([A, B]);
    await renderScreen();
    await act(async () => fireEvent.press(tag('מותג א׳')!));
    expect(tag('מותג א׳')).toBeNull();
    expect(tag('מותג ב׳')).toBeTruthy();
    expect(mockPut).toHaveBeenCalledWith(
      '/v1/me/brands',
      expect.objectContaining({ body: { brand_ids: ['b'] } }),
    );
  });

  it('removing the last tag brings the empty state back', async () => {
    server([A]);
    await renderScreen();
    await act(async () => fireEvent.press(tag('מותג א׳')!));
    expect(screen.getByText(EMPTY)).toBeTruthy();
  });

  it('save failed: back to the saved state, with a message', async () => {
    server([A]);
    await renderScreen();
    mockPut.mockRejectedValueOnce(new TypeError('Network request failed'));
    await act(async () => fireEvent.press(tag('מותג א׳')!));
    expect(tag('מותג א׳')).toBeTruthy();
    expect(screen.getByRole('alert')).toBeTruthy();
    expect(screen.getByText(SAVE_FAILED)).toBeTruthy();
  });

  it('the back button goes back', async () => {
    await renderScreen();
    fireEvent.press(screen.getByRole('button', { name: 'חזרה' }));
    expect(mockRouter.back).toHaveBeenCalledTimes(1);
    expect(mockRouter.replace).not.toHaveBeenCalled();
  });

  it('with nothing to go back to, it opens the profile', async () => {
    mockRouter.canGoBack.mockReturnValue(false);
    await renderScreen();
    fireEvent.press(screen.getByRole('button', { name: 'חזרה' }));
    expect(mockRouter.back).not.toHaveBeenCalled();
    expect(mockRouter.replace).toHaveBeenCalledWith('/(tabs)/profile');
  });
});
