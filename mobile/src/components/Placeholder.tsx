import { StyleSheet, Text } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { t } from '../i18n';
import { tokens } from '../theme/tokens';

/** Temporary screen body until the real screens land. */
export function Placeholder({ titleKey }: { titleKey: string }) {
  // Headers are hidden and Android is edge-to-edge, so keep clear of the status bar.
  return (
    <SafeAreaView edges={['top']} style={styles.container}>
      <Text accessibilityRole="header" style={styles.title}>
        {t(titleKey)}
      </Text>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: tokens.colors.surfaceBase,
    paddingHorizontal: tokens.spacing.marginMobile,
  },
  title: {
    ...tokens.typography.title,
    color: tokens.colors.inkPrimary,
    marginTop: tokens.spacing[4],
  },
});
