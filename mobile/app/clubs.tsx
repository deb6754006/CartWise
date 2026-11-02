import { useRouter } from 'expo-router';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ClubsList } from '../src/components/ClubsList';
import { t } from '../src/i18n';
import { tokens } from '../src/theme/tokens';

const { colors, spacing, typography } = tokens;

/** SCR-CLUBS: which clubs the user belongs to. Open to guests, with no sign-in. */
export default function ClubsScreen() {
  const router = useRouter();

  const back = () => {
    if (router.canGoBack()) router.back();
    else router.replace('/(tabs)/profile');
  };

  return (
    <SafeAreaView edges={['top', 'bottom']} style={styles.container}>
      <View style={styles.top}>
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
            {t('clubs.title')}
          </Text>
        </View>
        <Text style={styles.subtitle}>{t('clubs.subtitle')}</Text>
      </View>
      <ScrollView contentContainerStyle={styles.body}>
        <ClubsList />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.surfaceBase,
  },
  top: {
    paddingHorizontal: spacing.marginMobile,
    paddingTop: spacing[2],
    paddingBottom: spacing[3],
  },
  bar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing[1],
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
  subtitle: {
    ...typography.meta,
    color: colors.inkSecondary,
  },
  body: {
    paddingHorizontal: spacing.marginMobile,
    paddingBottom: spacing[4],
  },
});
