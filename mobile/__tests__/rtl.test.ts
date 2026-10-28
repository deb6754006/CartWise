import { DevSettings, I18nManager } from 'react-native';

import { ensureRTL } from '../src/rtl';

function setIsRTL(value: boolean) {
  Object.defineProperty(I18nManager, 'isRTL', { value, configurable: true, writable: true });
}

describe('ensureRTL()', () => {
  const originalIsRTL = I18nManager.isRTL;

  beforeEach(() => {
    jest.spyOn(I18nManager, 'allowRTL').mockImplementation(() => {});
    jest.spyOn(I18nManager, 'forceRTL').mockImplementation(() => {});
  });

  afterEach(() => {
    jest.restoreAllMocks();
    setIsRTL(originalIsRTL);
  });

  it('allows and forces RTL', () => {
    jest.spyOn(DevSettings, 'reload').mockImplementation(() => {});
    setIsRTL(true);
    ensureRTL();
    expect(I18nManager.allowRTL).toHaveBeenCalledWith(true);
    expect(I18nManager.forceRTL).toHaveBeenCalledWith(true);
  });

  it('reloads once in dev when the layout is still LTR (Expo Go first launch)', () => {
    const reload = jest.spyOn(DevSettings, 'reload').mockImplementation(() => {});
    setIsRTL(false);
    ensureRTL();
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it('does not reload when the layout is already RTL', () => {
    const reload = jest.spyOn(DevSettings, 'reload').mockImplementation(() => {});
    setIsRTL(true);
    ensureRTL();
    expect(reload).not.toHaveBeenCalled();
  });
});

describe('root layout', () => {
  afterEach(() => jest.restoreAllMocks());

  it('calls ensureRTL when the module loads, before the first render', () => {
    jest.isolateModules(() => {
      jest.doMock('../src/rtl', () => ({ ensureRTL: jest.fn() }));
      const { ensureRTL: mocked } = require('../src/rtl');
      require('../app/_layout');
      expect(mocked).toHaveBeenCalledTimes(1);
    });
  });
});
