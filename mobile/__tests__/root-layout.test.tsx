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
const mockEnsureDeviceToken = jest.fn<Promise<string | null>, []>();
jest.mock('../src/identity/device', () => ({
  ensureDeviceToken: () => mockEnsureDeviceToken(),
}));

describe('root layout', () => {
  // By default the registration never settles: rendering must not wait for it.
  beforeEach(() => mockEnsureDeviceToken.mockReturnValue(new Promise(() => {})));
  afterEach(() => jest.clearAllMocks());

  it('registers the device in the background without blocking rendering', () => {
    mockUseFonts.mockReturnValue([true, null]);
    render(<RootLayout />);
    expect(screen.getByText('stack')).toBeTruthy();
    expect(mockEnsureDeviceToken).toHaveBeenCalledTimes(1);
  });

  it('swallows a failed registration', async () => {
    const rejected = Promise.reject(new Error('offline'));
    const catchSpy = jest.spyOn(rejected, 'catch');
    mockEnsureDeviceToken.mockReturnValue(rejected);
    mockUseFonts.mockReturnValue([true, null]);
    render(<RootLayout />);
    // The layout attached a rejection handler, and that handler absorbs the error.
    expect(catchSpy).toHaveBeenCalledWith(expect.any(Function));
    const handler = catchSpy.mock.calls[0][0] as (e: unknown) => unknown;
    expect(() => handler(new Error('offline'))).not.toThrow();
    await expect(catchSpy.mock.results[0].value).resolves.toBeUndefined();
    expect(screen.getByText('stack')).toBeTruthy();
  });

  it('starts the registration even while fonts are pending', () => {
    mockUseFonts.mockReturnValue([false, null]);
    render(<RootLayout />);
    expect(mockEnsureDeviceToken).toHaveBeenCalledTimes(1);
  });

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
