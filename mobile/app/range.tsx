import { useRouter } from 'expo-router';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { CardsSkeleton } from '../src/components/CardsSkeleton';
import { RangePicker } from '../src/components/RangePicker';
import { t } from '../src/i18n';
import { useRange } from '../src/profile/useRange';
import { tokens } from '../src/theme/tokens';

const { colors, spacing, typography } = tokens;

function RangeContent() {
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

/** The default range, opened from the profile. Open to guests, with no sign-in. */
export default function RangeScreen() {
  const router = useRouter();

  const back = () => {
    if (router.canGoBack()) router.back();
    else router.replace('/(tabs)/profile');
  };

  return (
    <SafeAreaView edges={['top', 'bottom']} style={styles.container}>
      <View style={styles.bar}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={t('nav.back')}
          onPress={back}
          style={styles.back}
        >
          <Text style={styles.backIcon}>{t('nav.backArrow')}</Text>
        </Pressable>
        <Text accessibilityRole="header" style={styles.title}>
          {t('range.title')}
        </Text>
      </View>
      <ScrollView contentContainerStyle={styles.body}>
        <RangeContent />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.surfaceBase,
  },
  bar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing[1],
    paddingHorizontal: spacing.marginMobile,
    paddingTop: spacing[2],
    paddingBottom: spacing[3],
  },
  back: {
    width: tokens.touchTarget,
    height: tokens.touchTarget,
    alignItems: 'center',
    justifyContent: 'center',
  },
  backIcon: {
    ...typography.title,
    color: colors.inkPrimary,
  },
  title: {
    ...typography.title,
    flex: 1,
    color: colors.inkPrimary,
  },
  body: {
    paddingHorizontal: spacing.marginMobile,
    paddingBottom: spacing[4],
  },
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
