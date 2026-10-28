import { existsSync, readFileSync } from 'fs';
import { join } from 'path';

import type { ConfigContext, ExpoConfig } from 'expo/config';

/**
 * Firebase / Google sign-in config lives in mobile/google-services.json, which is never
 * committed (public repo). Without it the native Firebase plugins are left out, the app
 * still builds and runs as a guest, and the Google button says sign-in is not set up.
 */
const GOOGLE_SERVICES_FILE = './google-services.json';

/** OAuth client of type 3 (web) in google-services.json: the webClientId Google sign-in needs. */
function webClientIdFrom(path: string): string | undefined {
  try {
    const json = JSON.parse(readFileSync(path, 'utf8'));
    for (const client of json.client ?? []) {
      for (const oauth of client.oauth_client ?? []) {
        if (oauth.client_type === 3 && typeof oauth.client_id === 'string') return oauth.client_id;
      }
    }
  } catch {
    // Unreadable file: treated as not configured.
  }
  return undefined;
}

export default ({ config, projectRoot }: ConfigContext): ExpoConfig => {
  const googleServicesPath = join(projectRoot, GOOGLE_SERVICES_FILE);
  const hasGoogleServices = existsSync(googleServicesPath);
  const webClientId =
    process.env.GOOGLE_WEB_CLIENT_ID ||
    (hasGoogleServices ? webClientIdFrom(googleServicesPath) : undefined);

  return {
    ...config,
    name: 'CartWise',
    slug: 'cartwise',
    version: '1.0.0',
    scheme: 'cartwise',
    platforms: ['android'],
    orientation: 'portrait',
    icon: './assets/icon.png',
    userInterfaceStyle: 'light',
    android: {
      package: 'app.cartwise',
      adaptiveIcon: {
        backgroundColor: '#FBFAF7',
        foregroundImage: './assets/android-icon-foreground.png',
        backgroundImage: './assets/android-icon-background.png',
        monochromeImage: './assets/android-icon-monochrome.png',
      },
      predictiveBackGestureEnabled: false,
      ...(hasGoogleServices ? { googleServicesFile: GOOGLE_SERVICES_FILE } : {}),
    },
    plugins: [
      'expo-router',
      'expo-font',
      ['expo-localization', { supportsRTL: true, forcesRTL: true }],
      [
        'expo-splash-screen',
        {
          image: './assets/splash-icon.png',
          imageWidth: 200,
          resizeMode: 'contain',
          backgroundColor: '#FBFAF7',
        },
      ],
      'expo-status-bar',
      'expo-asset',
      'expo-secure-store',
      ...(hasGoogleServices
        ? [
            '@react-native-firebase/app',
            '@react-native-firebase/auth',
            '@react-native-google-signin/google-signin',
          ]
        : []),
    ],
    extra: {
      ...config.extra,
      // Read by src/identity/session.ts. Empty: Google sign-in is "not set up yet".
      googleWebClientId: hasGoogleServices && webClientId ? webClientId : '',
    },
  };
};
