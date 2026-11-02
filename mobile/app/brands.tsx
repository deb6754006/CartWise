import { useRouter } from 'expo-router';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { CardsSkeleton } from '../src/components/CardsSkeleton';
import { t } from '../src/i18n';
import { MAX_SEARCH_LENGTH, useBrands } from '../src/profile/useBrands';
import { tokens } from '../src/theme/tokens';

const { colors, spacing, typography } = tokens;

function BrandsContent() {
  const {
    status,
    selected,
    saveFailed,
    reload,
    add,
    remove,
    query,
    search,
    searchStatus,
    results,
    noResults,
  } = useBrands();

  if (status === 'loading') {
    return <CardsSkeleton label={t('brands.loading')} testID="brands-skeleton" />;
  }

  if (status === 'error') {
    return (
      <View style={styles.content}>
        <Text accessibilityRole="alert" style={styles.message}>
          {t('brands.loadError')}
        </Text>
        <Pressable
          accessibilityRole="button"
          onPress={reload}
          style={({ pressed }) => [styles.retry, pressed && styles.retryPressed]}
        >
          <Text style={styles.retryLabel}>{t('brands.retry')}</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <View style={styles.content}>
      <TextInput
        accessibilityLabel={t('brands.searchLabel')}
        placeholder={t('brands.searchPlaceholder')}
        placeholderTextColor={colors.inkSecondary}
        value={query}
        onChangeText={search}
        maxLength={MAX_SEARCH_LENGTH}
        autoCorrect={false}
        returnKeyType="search"
        style={styles.input}
      />
      {searchStatus === 'searching' ? (
        <Text accessibilityLiveRegion="polite" style={styles.message}>
          {t('brands.searching')}
        </Text>
      ) : null}
      {searchStatus === 'error' ? (
        <Text accessibilityRole="alert" accessibilityLiveRegion="polite" style={styles.error}>
          {t('brands.searchError')}
        </Text>
      ) : null}
      {noResults ? (
        <Text accessibilityLiveRegion="polite" style={styles.message}>
          {t('brands.noResults')}
        </Text>
      ) : null}
      {results.length > 0 ? (
        <View style={styles.results}>
          {results.map((brand) => (
            <Pressable
              key={brand.id}
              accessibilityRole="button"
              accessibilityLabel={`${t('brands.add')} ${brand.name}`}
              onPress={() => add(brand)}
              style={({ pressed }) => [styles.result, pressed && styles.resultPressed]}
            >
              <Text style={styles.resultName}>{brand.name}</Text>
            </Pressable>
          ))}
        </View>
      ) : null}
      {selected.length > 0 ? (
        <View style={styles.chips}>
          {selected.map((brand) => (
            <View key={brand.id} style={styles.chip}>
              <View style={styles.chipBackground} />
              <Text style={styles.chipName}>{brand.name}</Text>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`${t('brands.remove')} ${brand.name}`}
                onPress={() => remove(brand.id)}
                style={styles.remove}
              >
                <Text style={styles.removeIcon}>{t('brands.removeIcon')}</Text>
              </Pressable>
            </View>
          ))}
        </View>
      ) : (
        <View style={styles.empty}>
          <Text style={styles.emptyText}>{t('brands.empty')}</Text>
        </View>
      )}
      {saveFailed ? (
        <Text accessibilityRole="alert" accessibilityLiveRegion="polite" style={styles.error}>
          {t('brands.saveError')}
        </Text>
      ) : null}
    </View>
  );
}

/** SCR-BRANDS: which brands the user wants. Open to guests, with no sign-in. */
export default function BrandsScreen() {
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
            {t('brands.title')}
          </Text>
        </View>
        <Text style={styles.subtitle}>{t('brands.subtitle')}</Text>
      </View>
      {/* "handled": with the keyboard open, the first tap on a result already adds it. */}
      <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
        <BrandsContent />
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
  content: {
    gap: spacing[2],
  },
  input: {
    ...typography.body,
    minHeight: tokens.touchTarget,
    color: colors.inkPrimary,
    backgroundColor: colors.surfaceRaised,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: tokens.rounded.md,
    paddingHorizontal: spacing[3],
  },
  results: {
    overflow: 'hidden',
    backgroundColor: colors.surfaceRaised,
    borderWidth: 1,
    borderColor: colors.borderHairline,
    borderRadius: tokens.rounded.lg,
  },
  result: {
    minHeight: tokens.touchTarget,
    justifyContent: 'center',
    paddingHorizontal: spacing[4],
    paddingVertical: spacing[2],
  },
  resultPressed: {
    backgroundColor: colors.surfaceSunken,
  },
  resultName: {
    ...typography.body,
    color: colors.inkPrimary,
  },
  chips: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    columnGap: spacing[2],
  },
  // A full touch target high, since hitSlop does not reach past the parent on Android. The
  // tag's visible shape is chipBackground, which is shorter.
  chip: {
    minHeight: tokens.touchTarget,
    flexDirection: 'row',
    alignItems: 'center',
    paddingStart: spacing[3],
  },
  chipBackground: {
    position: 'absolute',
    start: 0,
    end: 0,
    top: spacing[2],
    bottom: spacing[2],
    backgroundColor: colors.skyTint,
    borderRadius: tokens.rounded.md,
  },
  chipName: {
    ...typography.meta,
    fontFamily: tokens.fontFamily[600],
    flexShrink: 1,
    color: colors.skyInk,
  },
  remove: {
    width: tokens.touchTarget,
    height: tokens.touchTarget,
    alignItems: 'center',
    justifyContent: 'center',
  },
  removeIcon: {
    ...typography.meta,
    color: colors.skyInk,
  },
  empty: {
    backgroundColor: colors.skyTint,
    borderWidth: 1,
    borderColor: colors.skyDecor,
    borderRadius: tokens.rounded.lg,
    padding: spacing[3],
  },
  emptyText: {
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
