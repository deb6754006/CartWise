import { useRouter } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { BackHandler, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ClubsList } from '../src/components/ClubsList';
import { Mascot } from '../src/components/Mascot';
import {
  ONBOARDING_STEPS,
  OnboardingButton,
  OnboardingFrame,
  OnboardingTitle,
} from '../src/components/OnboardingFrame';
import { OriginStep } from '../src/components/OriginStep';
import { RangeEditor } from '../src/components/RangeEditor';
import { t } from '../src/i18n';
import { markOnboardingDone } from '../src/onboarding/state';
import { tokens } from '../src/theme/tokens';

const { colors, spacing, typography } = tokens;

const LAST_STEP = ONBOARDING_STEPS - 1;
// A second tap this soon after moving on belongs to the step before: it must not skip this one
// unseen. Comparing steps is not enough, because the new step has already rendered by then.
const DOUBLE_TAP_MS = 400;

function WelcomeStep({ step, onNext }: { step: number; onNext: () => void }) {
  const router = useRouter();
  return (
    <OnboardingFrame
      step={step}
      centered
      actions={
        <>
          <OnboardingButton label={t('onboarding.welcome.start')} onPress={onNext} />
          <Pressable
            accessibilityRole="link"
            accessibilityLabel={t('onboarding.welcome.privacyLink')}
            onPress={() => router.push('/privacy')}
            style={styles.privacy}
          >
            <Text style={styles.privacyText}>
              {t('onboarding.welcome.privacyPrefix')}{' '}
              <Text style={styles.privacyLink}>{t('onboarding.welcome.privacyLink')}</Text>
            </Text>
          </Pressable>
        </>
      }
    >
      <Mascot size={120} />
      <Text accessibilityRole="header" style={styles.welcomeTitle}>
        {t('onboarding.welcome.title')}
      </Text>
      <Text style={styles.welcomeSubtitle}>{t('onboarding.welcome.subtitle')}</Text>
      <View style={styles.points}>
        <Text style={styles.point}>{t('onboarding.welcome.pointStore')}</Text>
        <Text style={styles.point}>{t('onboarding.welcome.pointClubs')}</Text>
        <Text style={styles.point}>{t('onboarding.welcome.pointSources')}</Text>
      </View>
    </OnboardingFrame>
  );
}

function RangeStep({ step, onNext }: { step: number; onNext: () => void }) {
  return (
    <OnboardingFrame
      step={step}
      actions={<OnboardingButton label={t('onboarding.continue')} onPress={onNext} />}
    >
      <OnboardingTitle
        title={t('onboarding.range.title')}
        subtitle={t('onboarding.range.subtitle')}
      />
      <RangeEditor />
    </OnboardingFrame>
  );
}

function ClubsStep({ step, onNext }: { step: number; onNext: () => void }) {
  return (
    <OnboardingFrame
      step={step}
      actions={<OnboardingButton label={t('onboarding.finish')} onPress={onNext} />}
    >
      <OnboardingTitle title={t('onboarding.clubs.title')} subtitle={t('clubs.subtitle')} />
      <ClubsList />
    </OnboardingFrame>
  );
}

const STEPS = [WelcomeStep, OriginStep, RangeStep, ClubsStep];

/** SCR-ONB-1..4, on the first launch. No sign-in here (FR-1). */
export default function OnboardingScreen() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const finished = useRef(false);
  const lastMove = useRef(0);

  const next = useCallback(() => {
    const now = Date.now();
    if (now - lastMove.current < DOUBLE_TAP_MS) return;
    lastMove.current = now;
    if (step < LAST_STEP) {
      setStep(step + 1);
      return;
    }
    if (finished.current) return;
    finished.current = true;
    // Not awaited: a failed or slow save must not hold the user here.
    void markOnboardingDone();
    router.replace('/');
  }, [router, step]);

  // On the first step (the only one that opens another screen) the system handles back as usual.
  useEffect(() => {
    const subscription = BackHandler.addEventListener('hardwareBackPress', () => {
      if (step === 0) return false;
      setStep(step - 1);
      return true;
    });
    return () => subscription.remove();
  }, [step]);

  const Step = STEPS[step];

  return (
    <SafeAreaView edges={['top', 'bottom']} style={styles.container}>
      <View style={styles.bar}>
        <Pressable accessibilityRole="button" onPress={next} style={styles.skip}>
          <Text style={styles.skipLabel}>{t('onboarding.skip')}</Text>
        </Pressable>
      </View>
      {/* The key starts each step afresh, at the top. */}
      <Step key={step} step={step} onNext={next} />
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
    justifyContent: 'flex-end',
    paddingHorizontal: spacing.marginMobile,
  },
  skip: {
    minWidth: tokens.touchTarget,
    minHeight: tokens.touchTarget,
    alignItems: 'center',
    justifyContent: 'center',
  },
  skipLabel: {
    ...typography.meta,
    fontFamily: tokens.fontFamily[600],
    color: colors.primary,
  },
  welcomeTitle: {
    ...typography.display,
    color: colors.inkPrimary,
    textAlign: 'center',
  },
  welcomeSubtitle: {
    ...typography.body,
    color: colors.inkSecondary,
    textAlign: 'center',
  },
  points: {
    alignSelf: 'stretch',
    gap: spacing[2],
    backgroundColor: colors.surfaceRaised,
    borderWidth: 1,
    borderColor: colors.borderHairline,
    borderRadius: tokens.rounded.lg,
    padding: spacing[4],
  },
  point: {
    ...typography.body,
    color: colors.inkPrimary,
  },
  privacy: {
    minHeight: tokens.touchTarget,
    alignItems: 'center',
    justifyContent: 'center',
  },
  privacyText: {
    ...typography.meta,
    color: colors.inkSecondary,
    textAlign: 'center',
  },
  privacyLink: {
    color: colors.primary,
    textDecorationLine: 'underline',
  },
});
