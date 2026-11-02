import { useFocusEffect, useRouter } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { t } from '../../src/i18n';
import { loadBrands } from '../../src/profile/useBrands';
import { loadClubs } from '../../src/profile/useClubs';
import { tokens } from '../../src/theme/tokens';

const { colors, spacing, typography } = tokens;

const countClubs = () => loadClubs().then(({ clubIds }) => clubIds.length);
const countBrands = () => loadBrands().then((brands) => brands.length);

/**
 * A count that is refreshed on every return to the screen.
 * null: not known (still loading for the first time, or the last load failed).
 */
function useCountOnFocus(load: () => Promise<number>): number | null {
  const [count, setCount] = useState<number | null>(null);

  useFocusEffect(
    useCallback(() => {
      let current = true;
      load().then(
        (loaded) => {
          if (current) setCount(loaded);
        },
        () => {
          if (current) setCount(null);
        },
      );
      return () => {
        current = false;
      };
    }, [load]),
  );

  return count;
}

function CountRow({
  label,
  count,
  onPress,
}: {
  label: string;
  count: number | null;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={count === null ? label : `${label}: ${count}`}
      onPress={onPress}
      style={({ pressed }) => [styles.row, pressed && styles.pressed]}
    >
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={styles.rowValue}>
        {count === null ? t('nav.forwardArrow') : `${count} ${t('nav.forwardArrow')}`}
      </Text>
    </Pressable>
  );
}

/** SCR-PROFILE. So far, the clubs and brands rows: the others come with their own stories. */
export default function ProfileScreen() {
  const router = useRouter();
  const clubCount = useCountOnFocus(countClubs);
  const brandCount = useCountOnFocus(countBrands);

  return (
    <SafeAreaView edges={['top']} style={styles.container}>
      <Text accessibilityRole="header" style={styles.title}>
        {t('profile.title')}
      </Text>
      <Text style={styles.section}>{t('profile.comparison')}</Text>
      <View style={styles.card}>
        <CountRow
          label={t('profile.clubs')}
          count={clubCount}
          onPress={() => router.push('/clubs', { dangerouslySingular: true })}
        />
        <View style={styles.divider} />
        <CountRow
          label={t('profile.brands')}
          count={brandCount}
          onPress={() => router.push('/brands', { dangerouslySingular: true })}
        />
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
  divider: {
    height: 1,
    marginHorizontal: spacing[4],
    backgroundColor: colors.borderHairline,
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
