import { useState } from 'react';
import { ActivityIndicator, Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { t } from '../i18n';
import { GoogleG } from './GoogleG';
import { type Session, isSignInAvailable, signInWithGoogle } from '../identity/session';
import { tokens } from '../theme/tokens';

const { colors, spacing, typography } = tokens;
const { sheet } = tokens.components;

type Props = {
  visible: boolean;
  onSuccess: (session: Session) => void;
  /** "Not now", the scrim, the back button, or cancelling in Google. Nothing has changed. */
  onCancel: () => void;
};

type State = { kind: 'idle' } | { kind: 'loading' } | { kind: 'error'; message: string };

const ERROR_KEYS = new Set(['network', 'google', 'device_already_linked', 'auth_unavailable']);

function errorMessage(code: string): string {
  return t(`signIn.errors.${ERROR_KEYS.has(code) ? code : 'generic'}`);
}

/** SHEET-SIGNIN (EXPERIENCE §10.9): Google sign-in, shown only when it is needed. */
export function SignInSheet({ visible, onSuccess, onCancel }: Props) {
  const [state, setState] = useState<State>({ kind: 'idle' });
  const loading = state.kind === 'loading';

  const close = () => {
    if (loading) return;
    setState({ kind: 'idle' }); // a reopened sheet starts clean
    onCancel();
  };

  const signIn = async () => {
    if (loading) return;
    if (!isSignInAvailable()) {
      setState({ kind: 'error', message: t('signIn.unavailable') });
      return;
    }
    setState({ kind: 'loading' });
    const result = await signInWithGoogle();
    switch (result.status) {
      case 'success':
        setState({ kind: 'idle' });
        onSuccess(result.session);
        return;
      case 'cancelled':
        setState({ kind: 'idle' });
        onCancel();
        return;
      case 'unavailable':
        setState({ kind: 'error', message: t('signIn.unavailable') });
        return;
      case 'error':
        setState({ kind: 'error', message: errorMessage(result.code) });
    }
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={close}>
      <View style={styles.root}>
        <Pressable
          testID="signin-scrim"
          style={StyleSheet.absoluteFill}
          onPress={close}
          accessible={false}
        />
        <SafeAreaView edges={['bottom']} style={styles.sheet} accessibilityViewIsModal>
          <View style={styles.grabber} />
          <Text accessibilityRole="header" style={styles.title}>
            {t('signIn.title')}
          </Text>
          <Text style={styles.subtitle}>{t('signIn.subtitle')}</Text>

          <Pressable
            accessibilityRole="button"
            accessibilityLabel={t('signIn.google')}
            accessibilityState={{ disabled: loading, busy: loading }}
            disabled={loading}
            onPress={signIn}
            style={({ pressed }) => [styles.google, pressed && styles.pressed]}
          >
            {loading ? (
              <>
                <ActivityIndicator color={colors.primary} />
                <Text style={styles.googleLabel}>{t('signIn.loading')}</Text>
              </>
            ) : (
              <>
                <GoogleG />
                <Text style={styles.googleLabel}>{t('signIn.google')}</Text>
              </>
            )}
          </Pressable>

          {state.kind === 'error' ? (
            <Text accessibilityRole="alert" accessibilityLiveRegion="polite" style={styles.error}>
              {state.message}
            </Text>
          ) : null}

          <View style={styles.privacy}>
            <Text style={styles.privacyText}>{t('signIn.privacy')}</Text>
          </View>

          <Pressable
            accessibilityRole="button"
            disabled={loading}
            onPress={close}
            style={styles.notNow}
          >
            <Text style={[styles.notNowText, loading && styles.disabledText]}>
              {t('signIn.notNow')}
            </Text>
          </Pressable>
        </SafeAreaView>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    justifyContent: 'flex-end',
    backgroundColor: sheet.scrim,
  },
  sheet: {
    backgroundColor: sheet.background,
    borderTopLeftRadius: sheet.radius,
    borderTopRightRadius: sheet.radius,
    paddingHorizontal: spacing.marginMobile,
    paddingTop: spacing[3],
    paddingBottom: spacing[4],
    gap: spacing[3],
  },
  grabber: {
    alignSelf: 'center',
    width: sheet.grabberWidth,
    height: sheet.grabberHeight,
    borderRadius: sheet.grabberHeight,
    backgroundColor: sheet.grabber,
  },
  title: {
    ...typography.heading,
    color: colors.inkPrimary,
  },
  subtitle: {
    ...typography.meta,
    color: colors.inkSecondary,
  },
  google: {
    minHeight: tokens.touchTarget,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing[2],
    borderRadius: tokens.rounded.md,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    backgroundColor: colors.surfaceRaised,
    paddingHorizontal: spacing[3],
  },
  pressed: {
    backgroundColor: colors.surfaceSunken,
  },
  googleLabel: {
    ...typography.body,
    fontFamily: tokens.fontFamily[600],
    color: colors.inkPrimary,
  },
  error: {
    ...typography.meta,
    color: colors.errorInk,
    backgroundColor: colors.errorTint,
    borderRadius: tokens.rounded.sm,
    padding: spacing[2],
  },
  privacy: {
    backgroundColor: colors.primaryTint,
    borderRadius: tokens.rounded.sm,
    padding: spacing[2],
  },
  privacyText: {
    ...typography.meta,
    color: colors.inkPrimary,
  },
  notNow: {
    minHeight: tokens.touchTarget,
    alignItems: 'center',
    justifyContent: 'center',
  },
  notNowText: {
    ...typography.meta,
    color: colors.inkSecondary,
  },
  disabledText: {
    color: colors.inkDisabled,
  },
});
