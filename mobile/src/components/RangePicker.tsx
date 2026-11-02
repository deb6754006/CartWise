import { Pressable, StyleSheet, Text, View } from 'react-native';

import { t } from '../i18n';
import type { TravelMinutes, TravelMode } from '../profile/useRange';
import { tokens } from '../theme/tokens';

const { colors, spacing, typography } = tokens;

const MODES: readonly TravelMode[] = ['walk', 'car'];
/** FR-18, EXPERIENCE §10.4. The server accepts only these. */
const MINUTES: readonly TravelMinutes[] = [5, 10, 15, 20, 30];

function ModeOption({
  mode,
  selected,
  onPress,
}: {
  mode: TravelMode;
  selected: boolean;
  onPress: () => void;
}) {
  const name = t(`range.modes.${mode}`);
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityLabel={name}
      accessibilityState={{ checked: selected }}
      onPress={onPress}
      style={[styles.mode, selected && styles.modeSelected]}
    >
      <Text style={styles.modeIcon}>{t(`range.icons.${mode}`)}</Text>
      <Text style={[styles.modeName, selected && styles.modeNameSelected]}>{name}</Text>
    </Pressable>
  );
}

/**
 * Choosing a travel mode and minutes: controlled, with no navigation and no requests, so that
 * the profile, Onboarding and SHEET-RANGE can each decide what a choice means.
 */
export function RangePicker({
  mode,
  minutes,
  onModeChange,
  onMinutesChange,
}: {
  mode: TravelMode;
  minutes: TravelMinutes;
  onModeChange: (mode: TravelMode) => void;
  onMinutesChange: (minutes: TravelMinutes) => void;
}) {
  return (
    <View style={styles.picker}>
      <View
        accessibilityRole="radiogroup"
        accessibilityLabel={t('range.modeLabel')}
        style={styles.modes}
      >
        {MODES.map((option) => (
          <ModeOption
            key={option}
            mode={option}
            selected={option === mode}
            onPress={() => onModeChange(option)}
          />
        ))}
        {/* Public transport comes in version 1.1: shown, and not choosable. */}
        <Pressable
          disabled
          accessibilityRole="radio"
          accessibilityLabel={`${t('range.modes.transit')}, ${t('range.soon')}`}
          accessibilityState={{ disabled: true, checked: false }}
          style={[styles.mode, styles.modeDisabled]}
        >
          <Text style={styles.modeIcon}>{t('range.icons.transit')}</Text>
          <Text style={[styles.modeName, styles.disabledText]}>{t('range.modes.transit')}</Text>
          <Text style={[styles.soon, styles.disabledText]}>{t('range.soon')}</Text>
        </Pressable>
      </View>
      <Text style={styles.label}>{t('range.minutesQuestion')}</Text>
      <View
        accessibilityRole="radiogroup"
        accessibilityLabel={t('range.minutesQuestion')}
        style={styles.chips}
      >
        {MINUTES.map((option) => {
          const selected = option === minutes;
          return (
            <Pressable
              key={option}
              accessibilityRole="radio"
              accessibilityLabel={`${option} ${t('range.minutes')}`}
              accessibilityState={{ checked: selected }}
              onPress={() => onMinutesChange(option)}
              style={[styles.chip, selected && styles.chipSelected]}
            >
              <Text style={[styles.chipLabel, selected && styles.chipLabelSelected]}>{option}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  picker: {
    gap: spacing[4],
  },
  modes: {
    flexDirection: 'row',
    gap: spacing[2],
  },
  mode: {
    flex: 1,
    minHeight: tokens.touchTarget,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: tokens.rounded.md,
    backgroundColor: colors.surfaceRaised,
    paddingHorizontal: spacing[1],
    paddingVertical: spacing[3],
  },
  // A border thicker by 1 and padding thinner by 1: the size stays, so nothing moves on a choice.
  modeSelected: {
    borderWidth: 2,
    paddingHorizontal: spacing[1] - 1,
    paddingVertical: spacing[3] - 1,
    borderColor: colors.primary,
    backgroundColor: colors.primaryTint,
  },
  modeDisabled: {
    backgroundColor: colors.surfaceSunken,
  },
  modeIcon: {
    ...typography.title,
  },
  modeName: {
    ...typography.meta,
    color: colors.inkPrimary,
  },
  modeNameSelected: {
    fontFamily: tokens.fontFamily[700],
    color: colors.primary,
  },
  disabledText: {
    color: colors.inkDisabled,
  },
  soon: {
    ...typography.meta,
  },
  label: {
    ...typography.meta,
    color: colors.inkSecondary,
  },
  chips: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing[2],
  },
  chip: {
    minWidth: tokens.touchTarget,
    minHeight: tokens.touchTarget,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: tokens.rounded.md,
    backgroundColor: colors.surfaceRaised,
    paddingHorizontal: spacing[3],
  },
  chipSelected: {
    borderColor: colors.primary,
    backgroundColor: colors.primary,
  },
  chipLabel: {
    ...typography.body,
    color: colors.inkPrimary,
  },
  chipLabelSelected: {
    fontFamily: tokens.fontFamily[600],
    color: colors.onPrimary,
  },
});
