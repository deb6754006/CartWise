import * as Location from 'expo-location';
import { useEffect, useRef, useState } from 'react';
import { AppState, Linking, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { t } from '../i18n';
import { resolveAddress, saveOrigin } from '../onboarding/origin';
import { tokens } from '../theme/tokens';
import { OnboardingButton, OnboardingFrame } from './OnboardingFrame';

const { colors, spacing, typography } = tokens;

const PIN_CIRCLE_SIZE = 120;
// What the server accepts (backend geo/schemas.py). Below the minimum, a retry could never work.
const ADDRESS_MIN_LENGTH = 2;
const ADDRESS_MAX_LENGTH = 200;
const OSM_COPYRIGHT_URL = 'https://www.openstreetmap.org/copyright';

type Mode = 'ask' | 'denied' | 'address';

/**
 * SCR-ONB-2: only asks for the permission. The location itself is neither read nor kept here
 * (NFR-12). Without the permission, an address the user enters is kept on the device instead.
 */
export function OriginStep({ step, onNext }: { step: number; onNext: () => void }) {
  const [mode, setMode] = useState<Mode>('ask');
  const [address, setAddress] = useState('');
  const [busy, setBusy] = useState(false);
  const [errorKey, setErrorKey] = useState<'notFound' | 'failed' | null>(null);

  // Leaving the step (skip, back) drops whatever is still running: nothing is saved after it.
  const here = useRef(true);
  useEffect(() => {
    here.current = true;
    return () => {
      here.current = false;
    };
  }, []);

  // Back from the system settings: the permission may have been allowed there.
  useEffect(() => {
    if (mode !== 'denied') return undefined;
    let current = true;
    const subscription = AppState.addEventListener('change', (state) => {
      if (state !== 'active') return;
      Location.getForegroundPermissionsAsync().then(
        ({ granted }) => {
          if (granted && current) onNext();
        },
        () => {},
      );
    });
    return () => {
      current = false;
      subscription.remove();
    };
  }, [mode, onNext]);

  const askPermission = async () => {
    setBusy(true);
    let granted = false;
    try {
      granted = (await Location.requestForegroundPermissionsAsync()).granted;
    } catch {
      // The same as a refusal.
    }
    if (!here.current) return;
    setBusy(false);
    if (granted) onNext();
    else setMode('denied');
  };

  const saveAddress = async () => {
    setBusy(true);
    setErrorKey(null);
    try {
      const origin = await resolveAddress(address);
      if (!here.current) return;
      if (origin) {
        await saveOrigin(origin);
        if (here.current) onNext();
      } else {
        setErrorKey('notFound');
      }
    } catch {
      if (here.current) setErrorKey('failed');
    } finally {
      if (here.current) setBusy(false);
    }
  };

  const openSettings = () => {
    Linking.openSettings().catch(() => {});
  };

  if (mode === 'address') {
    return (
      <OnboardingFrame
        step={step}
        actions={
          <OnboardingButton
            label={t('onboarding.origin.save')}
            onPress={saveAddress}
            disabled={busy || address.trim().length < ADDRESS_MIN_LENGTH}
          />
        }
      >
        <Text accessibilityRole="header" style={styles.titleStart}>
          {t('onboarding.origin.title')}
        </Text>
        <Text style={styles.subtitleStart}>{t('onboarding.origin.addressHint')}</Text>
        <TextInput
          accessibilityLabel={t('onboarding.origin.addressLabel')}
          placeholder={t('onboarding.origin.addressPlaceholder')}
          placeholderTextColor={colors.inkSecondary}
          value={address}
          onChangeText={setAddress}
          editable={!busy}
          autoFocus
          maxLength={ADDRESS_MAX_LENGTH}
          style={styles.input}
        />
        <Pressable
          accessibilityRole="link"
          onPress={() => {
            Linking.openURL(OSM_COPYRIGHT_URL).catch(() => {});
          }}
          style={styles.attributionLink}
        >
          <Text style={styles.attribution}>{t('onboarding.origin.attribution')}</Text>
        </Pressable>
        {busy ? (
          <Text accessibilityLiveRegion="polite" style={styles.subtitleStart}>
            {t('onboarding.origin.checking')}
          </Text>
        ) : null}
        {errorKey ? (
          <Text accessibilityRole="alert" accessibilityLiveRegion="polite" style={styles.error}>
            {t(`onboarding.origin.${errorKey}`)}
          </Text>
        ) : null}
      </OnboardingFrame>
    );
  }

  const denied = mode === 'denied';
  return (
    <OnboardingFrame
      step={step}
      centered
      actions={
        <>
          {denied ? (
            <OnboardingButton label={t('onboarding.origin.openSettings')} onPress={openSettings} />
          ) : (
            <OnboardingButton
              label={t('onboarding.origin.allow')}
              onPress={askPermission}
              disabled={busy}
            />
          )}
          <OnboardingButton
            secondary
            label={t('onboarding.origin.useAddress')}
            onPress={() => setMode('address')}
            disabled={busy}
          />
        </>
      }
    >
      <View style={styles.pinCircle} importantForAccessibility="no-hide-descendants">
        <Text allowFontScaling={false} style={styles.pin}>
          {t('onboarding.origin.pin')}
        </Text>
      </View>
      <Text accessibilityRole="header" style={styles.title}>
        {t('onboarding.origin.title')}
      </Text>
      {denied ? (
        <Text accessibilityRole="alert" accessibilityLiveRegion="polite" style={styles.subtitle}>
          {t('onboarding.origin.denied')}
        </Text>
      ) : (
        <Text style={styles.subtitle}>{t('onboarding.origin.why')}</Text>
      )}
    </OnboardingFrame>
  );
}

const styles = StyleSheet.create({
  pinCircle: {
    width: PIN_CIRCLE_SIZE,
    height: PIN_CIRCLE_SIZE,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: tokens.rounded.full,
    backgroundColor: colors.skyDecor,
  },
  // The size from the SCR-ONB-2 mockup: decoration, outside the type scale.
  pin: {
    fontSize: 52,
    lineHeight: 64,
  },
  title: {
    ...typography.display,
    color: colors.inkPrimary,
    textAlign: 'center',
  },
  subtitle: {
    ...typography.body,
    color: colors.inkSecondary,
    textAlign: 'center',
  },
  titleStart: {
    ...typography.display,
    color: colors.inkPrimary,
  },
  subtitleStart: {
    ...typography.body,
    color: colors.inkSecondary,
  },
  input: {
    ...typography.body,
    minHeight: tokens.touchTarget,
    color: colors.inkPrimary,
    backgroundColor: colors.surfaceRaised,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: tokens.rounded.md,
    paddingHorizontal: spacing[3],
    textAlign: 'right',
  },
  attributionLink: {
    minHeight: tokens.touchTarget,
    justifyContent: 'center',
  },
  attribution: {
    ...typography.meta,
    color: colors.inkSecondary,
    textDecorationLine: 'underline',
  },
  error: {
    ...typography.meta,
    color: colors.errorInk,
    backgroundColor: colors.errorTint,
    borderRadius: tokens.rounded.sm,
    padding: spacing[2],
  },
});
