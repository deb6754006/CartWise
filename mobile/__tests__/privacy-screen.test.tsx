import { fireEvent, render, screen } from '@testing-library/react-native';

import PrivacyScreen from '../app/privacy';
import he from '../src/i18n/he.json';

// jest.mock calls are hoisted above the imports.
const mockRouter = { canGoBack: jest.fn(() => true), back: jest.fn(), replace: jest.fn() };
jest.mock('expo-router', () => ({ useRouter: () => mockRouter }));

describe('the privacy summary', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockRouter.canGoBack.mockReturnValue(true);
  });

  it('says what is kept and what is not', () => {
    render(<PrivacyScreen />);
    expect(screen.getByRole('header', { name: 'פרטיות בקצרה' })).toBeTruthy();
    expect(screen.getByRole('header', { name: 'מה נשמר' })).toBeTruthy();
    expect(screen.getByRole('header', { name: 'מה לא נשמר' })).toBeTruthy();
    expect(screen.getByText(/שם, מייל, טלפון או כתובת לא נשמרים/)).toBeTruthy();
    expect(screen.getByText(/תמונות של חשבוניות/)).toBeTruthy();
    expect(screen.getByText(/נשמרת במכשיר שלכם בלבד/)).toBeTruthy();
    expect(screen.getByText(/דרך השרת שלנו ל-OpenStreetMap, ולא נשמרת בשרת/)).toBeTruthy();
    expect(screen.getByText(/ולא נשמר בהיסטוריה. רק אזור מעוגל נשאר לזמן מוגבל/)).toBeTruthy();
    expect(screen.getByText('זה סיכום קצר, ולא המדיניות המלאה.')).toBeTruthy();
  });

  it('shows every item in its strings', () => {
    render(<PrivacyScreen />);
    for (const item of Object.values(he.privacy.items)) {
      expect(screen.getByText(item)).toBeTruthy();
    }
  });

  it('does not claim a legal review', () => {
    expect(JSON.stringify(he.privacy)).not.toMatch(/משפט|עורך דין|עו"ד|חוק/);
  });

  it('back returns to where it was opened from', () => {
    render(<PrivacyScreen />);
    fireEvent.press(screen.getByRole('button', { name: 'חזרה' }));
    expect(mockRouter.back).toHaveBeenCalledTimes(1);
  });

  it('with nowhere to go back to, back opens home', () => {
    mockRouter.canGoBack.mockReturnValue(false);
    render(<PrivacyScreen />);
    fireEvent.press(screen.getByRole('button', { name: 'חזרה' }));
    expect(mockRouter.replace).toHaveBeenCalledWith('/');
  });
});
