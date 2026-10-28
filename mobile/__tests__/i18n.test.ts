import { t } from '../src/i18n';

describe('t()', () => {
  afterEach(() => jest.restoreAllMocks());

  it('returns the Hebrew string for an existing key', () => {
    expect(t('tabs.home')).toBe('בית');
  });

  it('returns the key itself and warns for a missing key', () => {
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
    expect(t('no.such.key')).toBe('no.such.key');
    expect(warn).toHaveBeenCalledWith(expect.stringContaining('no.such.key'));
  });

  it('returns the key for a path that stops at a group, not a string', () => {
    jest.spyOn(console, 'warn').mockImplementation(() => {});
    expect(t('tabs')).toBe('tabs');
  });
});
