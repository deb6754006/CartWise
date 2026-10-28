import {
  Rubik_400Regular,
  Rubik_600SemiBold,
  Rubik_700Bold,
  Rubik_800ExtraBold,
  useFonts,
} from '@expo-google-fonts/rubik';
import { Stack } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';

import { ensureDeviceToken } from '../src/identity/device';
import { startSessionSync } from '../src/identity/session';
import { ensureRTL } from '../src/rtl';
import { tokens } from '../src/theme/tokens';

// Runs once, before the first render.
ensureRTL();
SplashScreen.preventAutoHideAsync().catch(() => {});

export default function RootLayout() {
  const [fontsLoaded, fontError] = useFonts({
    Rubik_400Regular,
    Rubik_600SemiBold,
    Rubik_700Bold,
    Rubik_800ExtraBold,
  });
  const ready = fontsLoaded || fontError != null;

  useEffect(() => {
    // Guest identity: register in the background. Never blocks rendering; failures are
    // retried on the next launch or the next API request.
    ensureDeviceToken().catch(() => {});
    // Registered user: read the stored session and keep it in step with Firebase.
    startSessionSync().catch(() => {});
  }, []);

  useEffect(() => {
    // Fall back to the system font rather than block the app.
    if (fontError) console.warn('[fonts] failed to load Rubik:', fontError.message);
  }, [fontError]);

  useEffect(() => {
    if (ready) SplashScreen.hideAsync().catch(() => {});
  }, [ready]);

  if (!ready) return null;

  return (
    <>
      <StatusBar style="dark" />
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: tokens.colors.surfaceBase },
        }}
      />
    </>
  );
}
