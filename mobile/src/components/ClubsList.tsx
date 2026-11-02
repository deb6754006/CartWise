import { Pressable, StyleSheet, Switch, Text, View } from 'react-native';

import { t } from '../i18n';
import { useClubs } from '../profile/useClubs';
import { tokens } from '../theme/tokens';
import { CardsSkeleton } from './CardsSkeleton';

const { colors, spacing, typography } = tokens;

/** A switch for each club, with its states. No navigation: Onboarding uses it as well. */
export function ClubsList() {
  const { status, clubs, selected, saveFailed, toggle, reload } = useClubs();

  if (status === 'loading') {
    return <CardsSkeleton label={t('clubs.loading')} testID="clubs-skeleton" />;
  }

  if (status === 'error') {
    return (
      <View style={styles.list}>
        <Text accessibilityRole="alert" style={styles.message}>
          {t('clubs.loadError')}
        </Text>
        <Pressable
          accessibilityRole="button"
          onPress={reload}
          style={({ pressed }) => [styles.retry, pressed && styles.pressed]}
        >
          <Text style={styles.retryLabel}>{t('clubs.retry')}</Text>
        </Pressable>
      </View>
    );
  }

  if (clubs.length === 0) return <Text style={styles.message}>{t('clubs.empty')}</Text>;

  return (
    <View style={styles.list}>
      {clubs.map((club) => {
        const on = selected.has(club.id);
        return (
          <View key={club.id} style={styles.card}>
            <Text style={styles.name}>{club.name}</Text>
            <Switch
              accessible
              accessibilityRole="switch"
              accessibilityLabel={club.name}
              accessibilityState={{ checked: on }}
              value={on}
              onValueChange={() => toggle(club.id)}
              trackColor={{ false: colors.borderStrong, true: colors.primary }}
              thumbColor={colors.surfaceRaised}
            />
          </View>
        );
      })}
      {saveFailed ? (
        <Text accessibilityRole="alert" accessibilityLiveRegion="polite" style={styles.saveError}>
          {t('clubs.saveError')}
        </Text>
      ) : null}
      <View style={styles.privacy}>
        <Text style={styles.privacyText}>{t('clubs.privacy')}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  list: {
    gap: spacing[2],
  },
  card: {
    minHeight: tokens.touchTarget,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing[2],
    backgroundColor: colors.surfaceRaised,
    borderWidth: 1,
    borderColor: colors.borderHairline,
    borderRadius: tokens.rounded.lg,
    paddingHorizontal: spacing[4],
    paddingVertical: spacing[3],
  },
  name: {
    ...typography.heading,
    flex: 1,
    color: colors.inkPrimary,
  },
  message: {
    ...typography.body,
    color: colors.inkSecondary,
  },
  retry: {
    minHeight: tokens.touchTarget,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: tokens.rounded.md,
    backgroundColor: colors.primary,
    paddingHorizontal: spacing[3],
  },
  pressed: {
    backgroundColor: colors.primarySoft,
  },
  retryLabel: {
    ...typography.body,
    fontFamily: tokens.fontFamily[600],
    color: colors.onPrimary,
  },
  saveError: {
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
});
