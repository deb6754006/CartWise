import { act, fireEvent, render, screen } from '@testing-library/react-native';

import ClubsScreen from '../app/clubs';

// jest.mock calls are hoisted above the imports.
const mockRouter = { canGoBack: jest.fn(() => true), back: jest.fn(), replace: jest.fn() };
jest.mock('expo-router', () => ({ useRouter: () => mockRouter }));
const mockGet = jest.fn();
jest.mock('../src/api/client', () => ({
  api: { GET: (path: string) => mockGet(path) },
}));

const CLUBS = [{ id: 'a', name: 'מועדון רשת א׳', chain_id: 'c1', chain_name: 'רשת א׳' }];

describe('SCR-CLUBS', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockRouter.canGoBack.mockReturnValue(true);
    mockGet.mockImplementation(async (path: string) =>
      path === '/v1/clubs' ? { data: CLUBS } : { data: { club_ids: [] } },
    );
  });

  async function renderScreen() {
    render(<ClubsScreen />);
    await act(async () => {});
  }

  it('has its title, subtitle and the list', async () => {
    await renderScreen();
    expect(screen.getByRole('header', { name: 'המועדונים שלי' })).toBeTruthy();
    expect(screen.getByText('כך נראה לכם את המחיר שתשלמו באמת')).toBeTruthy();
    expect(screen.getByRole('switch', { name: 'מועדון רשת א׳' })).toBeTruthy();
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
