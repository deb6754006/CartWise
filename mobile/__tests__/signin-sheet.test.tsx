import { act, fireEvent, render, screen } from '@testing-library/react-native';

import { SignInSheet } from '../src/components/SignInSheet';
import type { SignInResult } from '../src/identity/session';

// jest.mock calls are hoisted above the imports.
const mockSignIn = jest.fn<Promise<SignInResult>, []>();
const mockAvailable = jest.fn(() => true);
jest.mock('../src/identity/session', () => ({
  signInWithGoogle: () => mockSignIn(),
  isSignInAvailable: () => mockAvailable(),
}));

const SESSION = { userId: 'u1', firstName: 'דנה' };

function renderSheet() {
  const onSuccess = jest.fn();
  const onCancel = jest.fn();
  render(<SignInSheet visible onSuccess={onSuccess} onCancel={onCancel} />);
  return { onSuccess, onCancel };
}

const google = () => screen.getByRole('button', { name: 'המשך עם Google' });

describe('SignInSheet', () => {
  beforeEach(() => {
    mockSignIn.mockReset();
    mockAvailable.mockReturnValue(true);
  });

  it('shows the SHEET-SIGNIN copy', () => {
    renderSheet();
    expect(screen.getByText('כדי לסרוק ולעקוב אחרי ההוצאות, צריך להתחבר')).toBeTruthy();
    expect(screen.getByText('הרשימות וההעדפות שלכם יישמרו ויעברו לחשבון')).toBeTruthy();
    expect(screen.getByText('🔒 אנחנו לא שומרים שם, מייל, טלפון או כתובת')).toBeTruthy();
    expect(google()).toBeTruthy();
    // Google's official multicolor "G" mark, next to the Hebrew label.
    expect(screen.getByTestId('google-g', { includeHiddenElements: true })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'לא עכשיו' })).toBeTruthy();
  });

  it('"not now" cancels without signing in', () => {
    const { onCancel, onSuccess } = renderSheet();
    fireEvent.press(screen.getByRole('button', { name: 'לא עכשיו' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onSuccess).not.toHaveBeenCalled();
    expect(mockSignIn).not.toHaveBeenCalled();
  });

  it('the scrim cancels too', () => {
    const { onCancel } = renderSheet();
    fireEvent.press(screen.getByTestId('signin-scrim', { includeHiddenElements: true }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('success: shows loading, then reports the session', async () => {
    let resolve!: (r: SignInResult) => void;
    mockSignIn.mockReturnValue(new Promise((r) => (resolve = r)));
    const { onSuccess, onCancel } = renderSheet();

    fireEvent.press(google());
    expect(screen.getByText('מתחברים...')).toBeTruthy();
    // Closing is blocked while signing in.
    fireEvent.press(screen.getByRole('button', { name: 'לא עכשיו' }));
    expect(onCancel).not.toHaveBeenCalled();

    await act(async () => resolve({ status: 'success', session: SESSION }));
    expect(onSuccess).toHaveBeenCalledWith(SESSION);
  });

  it('cancelling in Google closes the sheet', async () => {
    mockSignIn.mockResolvedValue({ status: 'cancelled' });
    const { onCancel, onSuccess } = renderSheet();
    await act(async () => fireEvent.press(google()));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it.each([
    ['device_already_linked', 'המכשיר הזה כבר מחובר לחשבון אחר'],
    ['network', 'אין חיבור לשרת. בדקו את החיבור ונסו שוב'],
    ['server', 'ההתחברות לא הצליחה. נסו שוב בעוד רגע'],
  ])('link error %s: Hebrew message in the sheet, stays open', async (code, message) => {
    mockSignIn.mockResolvedValue({ status: 'error', code });
    const { onCancel, onSuccess } = renderSheet();
    await act(async () => fireEvent.press(google()));
    expect(screen.getByText(message)).toBeTruthy();
    expect(onCancel).not.toHaveBeenCalled();
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it('not configured: the button says sign-in is not set up yet', async () => {
    mockAvailable.mockReturnValue(false);
    renderSheet();
    await act(async () => fireEvent.press(google()));
    expect(screen.getByText('ההתחברות עדיין לא הוגדרה')).toBeTruthy();
    expect(mockSignIn).not.toHaveBeenCalled();
  });
});
