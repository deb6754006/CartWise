import { Pressable, StyleSheet, Text, View } from 'react-native';

import { t } from '../i18n';
import { useRange } from '../profile/useRange';
import { tokens } from '../theme/tokens';
import { CardsSkeleton } from './CardsSkeleton';
import { RangePicker } from './RangePicker';

const { colors, spacing, typography } = tokens;

/** The saved range with its states. No navigation: the range screen and Onboarding both use it. */
export function RangeEditor() {
  const { status, range, saveFailed, reload, setMode, setMinutes } = useRange();

  if (status === 'loading') {
    return <CardsSkeleton label={t('range.loading')} testID="range-skeleton" />;
  }

  if (status === 'error') {
    return (
      <View style={styles.content}>
        <Text accessibilityRole="alert" accessibilityLiveRegion="polite" style={styles.message}>
          {t('range.loadError')}
        </Text>
        <Pressable
          accessibilityRole="button"
          onPress={reload}
          style={({ pressed }) => [styles.retry, pressed && styles.retryPressed]}
        >
          <Text style={styles.retryLabel}>{t('range.retry')}</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <View style={styles.content}>
      <RangePicker
        mode={range.default_mode}
        minutes={range.default_minutes}
        onModeChange={setMode}
        onMinutesChange={setMinutes}
      />
      <View style={styles.hint}>
        <Text style={styles.hintText}>{t('range.hint')}</Text>
      </View>
      {saveFailed ? (
        <Text accessibilityRole="alert" accessibilityLiveRegion="polite" style={styles.error}>
          {t('range.saveError')}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  content: {
    gap: spacing[4],
  },
  hint: {
    backgroundColor: colors.skyTint,
    borderWidth: 1,
    borderColor: colors.skyDecor,
    borderRadius: tokens.rounded.lg,
    padding: spacing[3],
  },
  hintText: {
    ...typography.meta,
    color: colors.inkPrimary,
  },
  message: {
    ...typography.body,
    color: colors.inkSecondary,
  },
  error: {
    ...typography.meta,
    color: colors.errorInk,
    backgroundColor: colors.errorTint,
    borderRadius: tokens.rounded.sm,
    padding: spacing[2],
  },
  retry: {
    minHeight: tokens.touchTarget,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: tokens.rounded.md,
    backgroundColor: colors.primary,
    paddingHorizontal: spacing[3],
  },
  retryPressed: {
    backgroundColor: colors.primarySoft,
  },
  retryLabel: {
    ...typography.body,
    fontFamily: tokens.fontFamily[600],
    color: colors.onPrimary,
  },
});
