import { useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { t } from '../i18n';
import { tokens } from '../theme/tokens';

const { colors, spacing, typography } = tokens;

const SKELETON_CARDS = 3;
/** EXPERIENCE §6: after this long, loading also says "one moment". */
const SLOW_LOADING_MS = 3000;

/** The loading state of a screen (EXPERIENCE §6): a skeleton of cards. */
export function CardsSkeleton({ label, testID }: { label: string; testID: string }) {
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setSlow(true), SLOW_LOADING_MS);
    return () => clearTimeout(timer);
  }, []);

  return (
    <View
      testID={testID}
      accessible
      accessibilityRole="progressbar"
      accessibilityLabel={label}
      style={styles.list}
    >
      {Array.from({ length: SKELETON_CARDS }, (_, i) => (
        <View key={i} style={styles.card}>
          <View style={styles.name} />
        </View>
      ))}
      {slow ? <Text style={styles.slow}>{t('loading.slow')}</Text> : null}
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
    width: '50%',
    height: spacing[4],
    borderRadius: tokens.rounded.sm,
    backgroundColor: colors.surfaceSunken,
  },
  slow: {
    ...typography.body,
    color: colors.inkSecondary,
  },
});
