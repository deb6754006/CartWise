import type { ReactNode } from 'react';
import { KeyboardAvoidingView, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { t } from '../i18n';
import { tokens } from '../theme/tokens';

const { colors, spacing, typography } = tokens;

export const ONBOARDING_STEPS = 4;

function ProgressDots({ step }: { step: number }) {
  return (
    <View
      accessible
      accessibilityRole="progressbar"
      accessibilityLabel={`${t('onboarding.step')} ${step + 1} ${t('onboarding.of')} ${ONBOARDING_STEPS}`}
      accessibilityValue={{ min: 1, max: ONBOARDING_STEPS, now: step + 1 }}
      style={styles.dots}
    >
      {Array.from({ length: ONBOARDING_STEPS }, (_, index) => (
        <View key={index} style={[styles.dot, index === step && styles.dotOn]} />
      ))}
    </View>
  );
}

/** One Onboarding step: scrolling content, then the progress dots and the step's actions. */
export function OnboardingFrame({
  step,
  centered = false,
  actions,
  children,
}: {
  /** From 0. */
  step: number;
  centered?: boolean;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <KeyboardAvoidingView behavior="padding" style={styles.frame}>
      <ScrollView
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={[styles.body, centered && styles.bodyCentered]}
      >
        {children}
      </ScrollView>
      <View style={styles.foot}>
        <ProgressDots step={step} />
        {actions}
      </View>
    </KeyboardAvoidingView>
  );
}

export function OnboardingTitle({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <View style={styles.heading}>
      <Text accessibilityRole="header" style={styles.title}>
        {title}
      </Text>
      <Text style={styles.subtitle}>{subtitle}</Text>
    </View>
  );
}

export function OnboardingButton({
  label,
  onPress,
  disabled = false,
  secondary = false,
}: {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  secondary?: boolean;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        secondary ? styles.secondary : pressed && styles.pressed,
        disabled && styles.buttonDisabled,
      ]}
    >
      <Text
        style={[
          styles.buttonLabel,
          secondary && styles.secondaryLabel,
          disabled && styles.labelDisabled,
        ]}
      >
        {label}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  frame: {
    flex: 1,
  },
  body: {
    flexGrow: 1,
    gap: spacing[4],
    paddingHorizontal: spacing.marginMobile,
    paddingBottom: spacing[4],
  },
  bodyCentered: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  foot: {
    gap: spacing[3],
    paddingHorizontal: spacing.marginMobile,
    paddingBottom: spacing[4],
  },
  dots: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: spacing[2],
    paddingVertical: spacing[1],
  },
  dot: {
    width: spacing[2],
    height: spacing[2],
    borderRadius: tokens.rounded.full,
    backgroundColor: colors.borderStrong,
  },
  // Wider as well, so the current step does not rest on color alone.
  dotOn: {
    width: spacing[4],
    backgroundColor: colors.primary,
  },
  heading: {
    gap: spacing[1],
  },
  title: {
    ...typography.display,
    color: colors.inkPrimary,
  },
  subtitle: {
    ...typography.body,
    color: colors.inkSecondary,
  },
  button: {
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
  secondary: {
    backgroundColor: colors.primaryTint,
  },
  buttonDisabled: {
    backgroundColor: colors.surfaceSunken,
  },
  buttonLabel: {
    ...typography.body,
    fontFamily: tokens.fontFamily[600],
    color: colors.onPrimary,
  },
  secondaryLabel: {
    color: colors.primary,
  },
  labelDisabled: {
    color: colors.inkDisabled,
  },
});
