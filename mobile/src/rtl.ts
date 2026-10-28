import { DevSettings, I18nManager } from 'react-native';

/**
 * Force the RTL layout.
 *
 * Native builds already start in RTL: the expo-localization plugin sets it natively.
 * In Expo Go, forceRTL only takes effect after a reload, so the first launch would
 * render LTR; in dev we reload once to apply it (after the reload isRTL is true).
 */
export function ensureRTL(): void {
  I18nManager.allowRTL(true);
  I18nManager.forceRTL(true);
  if (!I18nManager.isRTL && __DEV__) {
    DevSettings.reload();
  }
}
