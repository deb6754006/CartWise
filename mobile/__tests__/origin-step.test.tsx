import { act, fireEvent, render, screen } from '@testing-library/react-native';
import * as Location from 'expo-location';
import * as SecureStore from 'expo-secure-store';
import { AppState, Linking } from 'react-native';

import { OriginStep } from '../src/components/OriginStep';
import { getSavedOrigin } from '../src/onboarding/origin';

// jest.mock calls are hoisted above the imports.
jest.mock('expo-location', () => ({
  requestForegroundPermissionsAsync: jest.fn(),
  getForegroundPermissionsAsync: jest.fn(),
  getCurrentPositionAsync: jest.fn(),
  getLastKnownPositionAsync: jest.fn(),
  // Needs the permission on Android, so the step must never call it.
  geocodeAsync: jest.fn(),
}));
jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn(),
  setItemAsync: jest.fn(),
}));
const mockGet = jest.fn();
jest.mock('../src/api/client', () => ({
  api: { GET: (path: string, init: unknown) => mockGet(path, init) },
}));

const requestPermission = Location.requestForegroundPermissionsAsync as jest.Mock;
const getPermission = Location.getForegroundPermissionsAsync as jest.Mock;
const getItem = SecureStore.getItemAsync as jest.Mock;
const setItem = SecureStore.setItemAsync as jest.Mock;

const ALLOW = 'אישור מיקום';
const USE_ADDRESS = 'אזין כתובת במקום';
const OPEN_SETTINGS = 'לפתיחת ההגדרות';
const SAVE = 'שמירה';
const NOT_FOUND = 'לא מצאנו את הכתובת. נסו לכתוב אותה אחרת';
const FAILED = 'לא הצלחנו לבדוק את הכתובת. נסו שוב או דלגו';
const ADDRESS = 'הרצל 1, תל אביב';
const found = () => ({ data: { lat: 32.06, lng: 34.77 }, response: { status: 200 } });
const failed = (status: number) => ({ error: {}, response: { status } });
const notFound = () => ({
  error: { error: { code: 'address_not_found' } },
  response: { status: 404 },
});

const onNext = jest.fn();
let addListener: jest.SpyInstance;
let removeListener: jest.Mock;

const press = async (name: string) => {
  // Not returned: the press would then wait for a handler that a test keeps pending on purpose.
  await act(async () => {
    fireEvent.press(screen.getByRole('button', { name }));
  });
};
const renderStep = () => render(<OriginStep step={1} onNext={onNext} />);
const enterAddress = async (text: string) => {
  await press(USE_ADDRESS);
  fireEvent.changeText(screen.getByLabelText('כתובת'), text);
};

describe('the location step', () => {
  beforeEach(() => {
    jest.resetAllMocks();
    setItem.mockResolvedValue(undefined);
    removeListener = jest.fn();
    addListener = jest
      .spyOn(AppState, 'addEventListener')
      .mockReturnValue({ remove: removeListener });
  });

  afterEach(() => addListener.mockRestore());

  describe('back from the system settings', () => {
    const appBecomes = async (state: string) => {
      const listener = addListener.mock.calls[addListener.mock.calls.length - 1][1];
      await act(async () => listener(state));
    };
    const refuse = async () => {
      requestPermission.mockResolvedValue({ granted: false });
      renderStep();
      await press(ALLOW);
    };

    it('allowed there: the next step', async () => {
      await refuse();
      getPermission.mockResolvedValue({ granted: true });
      await appBecomes('active');
      expect(onNext).toHaveBeenCalledTimes(1);
    });

    it('still refused, or the check failed: stays on the explanation', async () => {
      await refuse();
      getPermission.mockResolvedValue({ granted: false });
      await appBecomes('active');
      getPermission.mockRejectedValue(new Error('no activity'));
      await appBecomes('active');
      expect(onNext).not.toHaveBeenCalled();
      expect(screen.getByRole('alert')).toHaveTextContent(/בלי הרשאת מיקום/);
    });

    it('checks only when the app becomes active', async () => {
      await refuse();
      await appBecomes('background');
      expect(getPermission).not.toHaveBeenCalled();
    });

    it('does not listen before a refusal, or once entering an address', async () => {
      renderStep();
      expect(addListener).not.toHaveBeenCalled();
      await press(USE_ADDRESS);
      expect(addListener).not.toHaveBeenCalled();
    });

    it('stops listening after moving on to an address', async () => {
      await refuse();
      await press(USE_ADDRESS);
      expect(removeListener).toHaveBeenCalledTimes(1);
    });
  });

  it('explains why, and asks for nothing until a button is pressed', () => {
    renderStep();
    expect(screen.getByRole('header', { name: 'איפה אתם?' })).toBeTruthy();
    expect(screen.getByText(/נשתמש במיקום שלכם רק בזמן ההשוואה/)).toBeTruthy();
    expect(screen.queryByText(/אנחנו לא שומרים אותו/)).toBeNull();
    expect(requestPermission).not.toHaveBeenCalled();
  });

  it('allowed: the next step, and no location is read or saved', async () => {
    requestPermission.mockResolvedValue({ granted: true });
    renderStep();
    await press(ALLOW);
    expect(onNext).toHaveBeenCalledTimes(1);
    expect(Location.getCurrentPositionAsync).not.toHaveBeenCalled();
    expect(Location.getLastKnownPositionAsync).not.toHaveBeenCalled();
    expect(setItem).not.toHaveBeenCalled();
    // Nothing from the permission goes to the server.
    expect(mockGet).not.toHaveBeenCalled();
  });

  it('while asking, the buttons are off, so there is only one request', async () => {
    let answer!: (value: { granted: boolean }) => void;
    requestPermission.mockReturnValue(new Promise((resolve) => (answer = resolve)));
    renderStep();
    await press(ALLOW);
    expect(screen.getByRole('button', { name: ALLOW })).toBeDisabled();
    fireEvent.press(screen.getByRole('button', { name: ALLOW }));
    expect(requestPermission).toHaveBeenCalledTimes(1);
    await act(async () => answer({ granted: true }));
  });

  it.each([
    ['refused', () => requestPermission.mockResolvedValue({ granted: false })],
    ['failed', () => requestPermission.mockRejectedValue(new Error('no activity'))],
  ])('%s: an explanation, the settings, and an address instead', async (_name, arrange) => {
    arrange();
    const openSettings = jest.spyOn(Linking, 'openSettings').mockResolvedValue();
    renderStep();
    await press(ALLOW);

    expect(onNext).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent(/בלי הרשאת מיקום/);
    await press(OPEN_SETTINGS);
    expect(openSettings).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: USE_ADDRESS })).toBeTruthy();
    openSettings.mockRestore();
  });

  it('settings that cannot open change nothing', async () => {
    requestPermission.mockResolvedValue({ granted: false });
    const openSettings = jest.spyOn(Linking, 'openSettings').mockRejectedValue(new Error('no'));
    renderStep();
    await press(ALLOW);
    await press(OPEN_SETTINGS);
    expect(screen.getByRole('alert')).toHaveTextContent(/בלי הרשאת מיקום/);
    openSettings.mockRestore();
  });

  it('refused, then an address that is found: kept on the device, then the next step', async () => {
    requestPermission.mockResolvedValue({ granted: false });
    mockGet.mockResolvedValue(found());
    renderStep();
    await press(ALLOW);
    await enterAddress(ADDRESS);
    await press(SAVE);

    expect(onNext).toHaveBeenCalledTimes(1);
    const origin = { label: ADDRESS, lat: 32.06, lng: 34.77 };
    getItem.mockImplementation(async () => setItem.mock.calls[0][1]);
    await expect(getSavedOrigin()).resolves.toEqual(origin);
    // Located through our server, with the address only, and not by the device's geocoder.
    expect(mockGet).toHaveBeenCalledTimes(1);
    expect(mockGet).toHaveBeenCalledWith(
      '/v1/geo/geocode',
      expect.objectContaining({ params: { query: { q: ADDRESS } } }),
    );
    expect(Location.geocodeAsync).not.toHaveBeenCalled();
  });

  it('with the permission never asked for, an address is still located and kept', async () => {
    mockGet.mockResolvedValue(found());
    renderStep();
    await enterAddress(ADDRESS);
    await press(SAVE);
    expect(requestPermission).not.toHaveBeenCalled();
    expect(Location.geocodeAsync).not.toHaveBeenCalled();
    expect(setItem).toHaveBeenCalledTimes(1);
    expect(onNext).toHaveBeenCalledTimes(1);
  });

  it('the address screen credits OpenStreetMap, with a link to its copyright page', async () => {
    const openURL = jest.spyOn(Linking, 'openURL').mockResolvedValue(undefined);
    renderStep();
    expect(screen.queryByText('© OpenStreetMap contributors')).toBeNull();
    await press(USE_ADDRESS);
    fireEvent.press(screen.getByRole('link', { name: '© OpenStreetMap contributors' }));
    expect(openURL).toHaveBeenCalledWith('https://www.openstreetmap.org/copyright');
    openURL.mockRestore();
  });

  it('the save button needs 2 characters after trimming, and the field stops at 200', async () => {
    renderStep();
    await press(USE_ADDRESS);
    expect(screen.getByLabelText('כתובת').props.maxLength).toBe(200);
    fireEvent.changeText(screen.getByLabelText('כתובת'), ' א ');
    expect(screen.getByRole('button', { name: SAVE })).toBeDisabled();
    fireEvent.changeText(screen.getByLabelText('כתובת'), ' אב ');
    expect(screen.getByRole('button', { name: SAVE })).toBeEnabled();
  });

  it('during the check: says so, save is off, and a second press sends nothing', async () => {
    let answer!: (value: unknown) => void;
    mockGet.mockReturnValue(new Promise((resolve) => (answer = resolve)));
    renderStep();
    await enterAddress(ADDRESS);
    expect(screen.queryByText('בודקים...')).toBeNull();
    await press(SAVE);

    expect(screen.getByText('בודקים...').props.accessibilityLiveRegion).toBe('polite');
    expect(screen.getByRole('button', { name: SAVE })).toBeDisabled();
    await press(SAVE);
    expect(mockGet).toHaveBeenCalledTimes(1);

    await act(async () => answer(notFound()));
    expect(screen.queryByText('בודקים...')).toBeNull();
    expect(screen.getByRole('button', { name: SAVE })).toBeEnabled();
  });

  it('never logs the address', async () => {
    const spies = (['log', 'info', 'warn', 'error', 'debug'] as const).map((method) =>
      jest.spyOn(console, method).mockImplementation(() => {}),
    );
    mockGet.mockRejectedValue(new TypeError('Network request failed'));
    renderStep();
    await enterAddress(ADDRESS);
    await press(SAVE);
    for (const spy of spies) {
      expect(JSON.stringify(spy.mock.calls)).not.toContain(ADDRESS);
      spy.mockRestore();
    }
  });

  it('an empty address: the button stays off', async () => {
    renderStep();
    await press(USE_ADDRESS);
    expect(screen.getByRole('button', { name: SAVE })).toBeDisabled();
    fireEvent.changeText(screen.getByLabelText('כתובת'), '   ');
    expect(screen.getByRole('button', { name: SAVE })).toBeDisabled();
    fireEvent.press(screen.getByRole('button', { name: SAVE }));
    expect(mockGet).not.toHaveBeenCalled();
    fireEvent.changeText(screen.getByLabelText('כתובת'), ADDRESS);
    expect(screen.getByRole('button', { name: SAVE })).toBeEnabled();
  });

  it('address not found: a message, nothing saved, no next step, and it can be retried', async () => {
    mockGet.mockResolvedValue(notFound());
    renderStep();
    await enterAddress('אין כזו');
    await press(SAVE);
    expect(screen.getByRole('alert')).toHaveTextContent(NOT_FOUND);
    expect(setItem).not.toHaveBeenCalled();
    expect(onNext).not.toHaveBeenCalled();

    mockGet.mockResolvedValue(found());
    await press(SAVE);
    expect(screen.queryByRole('alert')).toBeNull();
    expect(onNext).toHaveBeenCalledTimes(1);
  });

  it.each([
    ['the server is unavailable', () => mockGet.mockResolvedValue(failed(503))],
    ['the network failed', () => mockGet.mockRejectedValue(new TypeError('Network'))],
  ])('%s: a message, and nothing saved', async (_name, arrange) => {
    arrange();
    renderStep();
    await enterAddress(ADDRESS);
    await press(SAVE);
    expect(screen.getByRole('alert')).toHaveTextContent(FAILED);
    expect(setItem).not.toHaveBeenCalled();
    expect(onNext).not.toHaveBeenCalled();
  });

  it('saving failed: the same message, with no next step', async () => {
    mockGet.mockResolvedValue(found());
    setItem.mockRejectedValue(new Error('keystore'));
    renderStep();
    await enterAddress(ADDRESS);
    await press(SAVE);
    expect(screen.getByRole('alert')).toHaveTextContent(FAILED);
    expect(onNext).not.toHaveBeenCalled();
  });

  it('leaving during the check: nothing is saved, and no next step', async () => {
    let answer!: (value: unknown) => void;
    mockGet.mockReturnValue(new Promise((resolve) => (answer = resolve)));
    const { unmount } = renderStep();
    await enterAddress(ADDRESS);
    await press(SAVE);
    unmount();
    await act(async () => answer(found()));
    expect(setItem).not.toHaveBeenCalled();
    expect(onNext).not.toHaveBeenCalled();
  });

  it('leaving while asking for the permission: no next step', async () => {
    let answer!: (value: { granted: boolean }) => void;
    requestPermission.mockReturnValue(new Promise((resolve) => (answer = resolve)));
    const { unmount } = renderStep();
    await press(ALLOW);
    unmount();
    await act(async () => answer({ granted: true }));
    expect(onNext).not.toHaveBeenCalled();
  });
});
