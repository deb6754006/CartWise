import { useRouter } from 'expo-router';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { t } from '../src/i18n';
import { tokens } from '../src/theme/tokens';

const { colors, spacing, typography } = tokens;

const SECTIONS = [
  { titleKey: 'privacy.savedTitle', itemKeys: ['account', 'choices', 'prices', 'address', 'location'] },
  {
    titleKey: 'privacy.notSavedTitle',
    itemKeys: ['personal', 'images', 'receiptDetails'],
  },
] as const;

/** A short summary of what is and is not kept. Not the full policy, and not a legal document. */
export default function PrivacyScreen() {
  const router = useRouter();

  const back = () => {
    if (router.canGoBack()) router.back();
    else router.replace('/');
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
          {t('privacy.title')}
        </Text>
      </View>
      <ScrollView contentContainerStyle={styles.body}>
        <Text style={styles.text}>{t('privacy.intro')}</Text>
        {SECTIONS.map(({ titleKey, itemKeys }) => (
          <View key={titleKey} style={styles.section}>
            <Text accessibilityRole="header" style={styles.sectionTitle}>
              {t(titleKey)}
            </Text>
            {itemKeys.map((item) => (
              <Text key={item} style={styles.text}>
                {t(`privacy.items.${item}`)}
              </Text>
            ))}
          </View>
        ))}
        <Text style={styles.note}>{t('privacy.summaryOnly')}</Text>
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
    gap: spacing[4],
    paddingHorizontal: spacing.marginMobile,
    paddingBottom: spacing[4],
  },
  section: {
    gap: spacing[2],
    backgroundColor: colors.surfaceRaised,
    borderWidth: 1,
    borderColor: colors.borderHairline,
    borderRadius: tokens.rounded.lg,
    padding: spacing[4],
  },
  sectionTitle: {
    ...typography.heading,
    color: colors.inkPrimary,
  },
  text: {
    ...typography.body,
    color: colors.inkPrimary,
  },
  note: {
    ...typography.meta,
    color: colors.inkSecondary,
  },
});
