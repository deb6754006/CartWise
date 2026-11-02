import { useFocusEffect, useRouter } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { t } from '../../src/i18n';
import { loadClubs } from '../../src/profile/useClubs';
import { tokens } from '../../src/theme/tokens';

const { colors, spacing, typography } = tokens;

/** SCR-PROFILE. So far, only the clubs row: the other rows come with their own stories. */
export default function ProfileScreen() {
  const router = useRouter();
  // null: not known (still loading for the first time, or the last load failed).
  const [clubCount, setClubCount] = useState<number | null>(null);

  useFocusEffect(
    useCallback(() => {
      let current = true;
      loadClubs().then(
        ({ clubIds }) => {
          if (current) setClubCount(clubIds.length);
        },
        () => {
          if (current) setClubCount(null);
        },
      );
      return () => {
        current = false;
      };
    }, []),
  );

  const clubsLabel = t('profile.clubs');

  return (
    <SafeAreaView edges={['top']} style={styles.container}>
      <Text accessibilityRole="header" style={styles.title}>
        {t('profile.title')}
      </Text>
      <Text style={styles.section}>{t('profile.comparison')}</Text>
      <View style={styles.card}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={clubCount === null ? clubsLabel : `${clubsLabel}: ${clubCount}`}
          onPress={() => router.push('/clubs', { dangerouslySingular: true })}
          style={({ pressed }) => [styles.row, pressed && styles.pressed]}
        >
          <Text style={styles.rowLabel}>{clubsLabel}</Text>
          <Text style={styles.rowValue}>
            {clubCount === null ? t('nav.forwardArrow') : `${clubCount} ${t('nav.forwardArrow')}`}
          </Text>
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.surfaceBase,
    paddingHorizontal: spacing.marginMobile,
    gap: spacing[2],
  },
  title: {
    ...typography.title,
    color: colors.inkPrimary,
    marginTop: spacing[4],
    marginBottom: spacing[2],
  },
  section: {
    ...typography.meta,
    fontFamily: tokens.fontFamily[600],
    color: colors.inkPrimary,
  },
  card: {
    overflow: 'hidden',
    backgroundColor: colors.surfaceRaised,
    borderWidth: 1,
    borderColor: colors.borderHairline,
    borderRadius: tokens.rounded.lg,
  },
  row: {
    minHeight: tokens.touchTarget,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing[2],
    paddingHorizontal: spacing[4],
    paddingVertical: spacing[2],
  },
  pressed: {
    backgroundColor: colors.surfaceSunken,
  },
  rowLabel: {
    ...typography.body,
    flex: 1,
    color: colors.inkPrimary,
  },
  rowValue: {
    ...typography.meta,
    color: colors.inkSecondary,
  },
});
