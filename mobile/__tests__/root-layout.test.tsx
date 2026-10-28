import { render, screen } from '@testing-library/react-native';

import RootLayout from '../app/_layout';

// jest.mock calls are hoisted above the imports.

const mockUseFonts = jest.fn();
const mockHideAsync = jest.fn(() => Promise.resolve());

jest.mock('@expo-google-fonts/rubik', () => ({
  useFonts: () => mockUseFonts(),
  Rubik_400Regular: 1,
  Rubik_600SemiBold: 2,
  Rubik_700Bold: 3,
  Rubik_800ExtraBold: 4,
}));
jest.mock('expo-splash-screen', () => ({
  preventAutoHideAsync: jest.fn(() => Promise.resolve()),
  hideAsync: () => mockHideAsync(),
}));
jest.mock('expo-router', () => {
  const { Text: MockText } = jest.requireActual('react-native');
  return { Stack: () => <MockText>stack</MockText> };
});
jest.mock('../src/rtl', () => ({ ensureRTL: jest.fn() }));

describe('root layout', () => {
  afterEach(() => jest.clearAllMocks());

  it('renders nothing and keeps the splash while fonts are pending', () => {
    mockUseFonts.mockReturnValue([false, null]);
    render(<RootLayout />);
    expect(screen.queryByText('stack')).toBeNull();
    expect(mockHideAsync).not.toHaveBeenCalled();
  });

  it('hides the splash and renders the app once fonts load', () => {
    mockUseFonts.mockReturnValue([true, null]);
    render(<RootLayout />);
    expect(screen.getByText('stack')).toBeTruthy();
    expect(mockHideAsync).toHaveBeenCalledTimes(1);
  });

  it('still renders, hides the splash and warns when fonts fail', () => {
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
    mockUseFonts.mockReturnValue([false, new Error('boom')]);
    render(<RootLayout />);
    expect(screen.getByText('stack')).toBeTruthy();
    expect(mockHideAsync).toHaveBeenCalledTimes(1);
    expect(warn).toHaveBeenCalledWith(expect.stringContaining('[fonts]'), 'boom');
    warn.mockRestore();
  });
});
