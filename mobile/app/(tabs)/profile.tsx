import { useFocusEffect, useRouter } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { t } from '../../src/i18n';
import {
  deleteAccount,
  getCachedSession,
  loadSession,
  onSessionChange,
  type Session,
} from '../../src/identity/session';
import { loadBrands } from '../../src/profile/useBrands';
import { loadClubs } from '../../src/profile/useClubs';
import { loadRange, type Range } from '../../src/profile/useRange';
import { tokens } from '../../src/theme/tokens';

const { colors, spacing, typography } = tokens;

const countClubs = () => loadClubs().then(({ clubIds }) => clubIds.length);
const countBrands = () => loadBrands().then((brands) => brands.length);

const shownRange = ({ default_mode, default_minutes }: Range) =>
  `${t(`range.icons.${default_mode}`)} ${default_minutes} ${t('range.minutesShort')}`;
const spokenRange = ({ default_mode, default_minutes }: Range) =>
  `${t(`range.modes.${default_mode}`)}, ${default_minutes} ${t('range.minutes')}`;

/**
 * A value that is refreshed on every return to the screen.
 * null: not known (still loading for the first time, or the last load failed).
 */
function useValueOnFocus<T>(load: () => Promise<T>): T | null {
  const [value, setValue] = useState<T | null>(null);

  useFocusEffect(
    useCallback(() => {
      let current = true;
      load().then(
        (loaded) => {
          if (current) setValue(loaded);
        },
        () => {
          if (current) setValue(null);
        },
      );
      return () => {
        current = false;
      };
    }, [load]),
  );

  return value;
}

/** A row leading to another screen. With no value, it is shown without one. */
function ValueRow({
  label,
  value,
  spokenValue = value,
  onPress,
}: {
  label: string;
  value: string | null;
  /** When the value does not read well aloud, as with an icon. */
  spokenValue?: string | null;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={spokenValue === null ? label : `${label}: ${spokenValue}`}
      onPress={onPress}
      style={({ pressed }) => [styles.row, pressed && styles.pressed]}
    >
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={styles.rowValue}>
        {value === null ? t('nav.forwardArrow') : `${value} ${t('nav.forwardArrow')}`}
      </Text>
    </Pressable>
  );
}

/** The signed-in session, kept in step with sign-in and sign-out. null: a guest. */
function useSession(): Session | null {
  const [session, setSession] = useState<Session | null>(() => getCachedSession() ?? null);
  useEffect(() => {
    let current = true;
    const unsubscribe = onSessionChange((s) => setSession(s));
    loadSession().then(
      (s) => {
        if (current) setSession(s);
      },
      () => {},
    );
    return () => {
      current = false;
      unsubscribe();
    };
  }, []);
  return session;
}

type Notice = 'deleted' | 'deleteFailed';

/**
 * "Account and privacy": for now only "delete account", and only for a signed-in user.
 * The press asks first (what is deleted and what is kept); a cancel sends nothing.
 */
function AccountSection({ onNotice }: { onNotice: (notice: Notice | null) => void }) {
  const session = useSession();
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const previousSession = useRef(session);

  // Signed in (again): an old "account deleted" notice no longer applies.
  useEffect(() => {
    if (session && !previousSession.current) onNotice(null);
    previousSession.current = session;
  }, [session, onNotice]);

  const runDelete = useCallback(async () => {
    if (busyRef.current) return; // a second confirm: still one request
    busyRef.current = true;
    setBusy(true);
    onNotice(null);
    let deleted = false;
    try {
      deleted = (await deleteAccount()).status === 'deleted';
    } catch {
      // deleteAccount never throws; if it does, it is a failure, and the row is usable again.
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
    onNotice(deleted ? 'deleted' : 'deleteFailed');
  }, [onNotice]);

  const confirm = () => {
    if (busyRef.current) return;
    Alert.alert(t('profile.deleteAccount.confirmTitle'), t('profile.deleteAccount.confirmBody'), [
      { text: t('profile.deleteAccount.cancel'), style: 'cancel' },
      {
        text: t('profile.deleteAccount.confirm'),
        style: 'destructive',
        onPress: () => {
          runDelete().catch(() => {});
        },
      },
    ]);
  };

  if (!session) return null;
  return (
    <>
      <Text style={styles.section}>{t('profile.account')}</Text>
      <View style={styles.card}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={t('profile.deleteAccount.row')}
          accessibilityState={{ disabled: busy, busy }}
          disabled={busy}
          onPress={confirm}
          style={({ pressed }) => [styles.row, pressed && styles.pressed]}
        >
          <Text style={[styles.rowLabel, styles.danger]}>
            {busy ? t('profile.deleteAccount.deleting') : t('profile.deleteAccount.row')}
          </Text>
          <Text style={styles.rowValue}>{t('nav.forwardArrow')}</Text>
        </Pressable>
      </View>
    </>
  );
}

/** SCR-PROFILE: the comparison rows, and the account row for a signed-in user. */
export default function ProfileScreen() {
  const router = useRouter();
  const clubCount = useValueOnFocus(countClubs);
  const brandCount = useValueOnFocus(countBrands);
  const range = useValueOnFocus(loadRange);
  const [notice, setNotice] = useState<Notice | null>(null);

  return (
    <SafeAreaView edges={['top']} style={styles.container}>
      <Text accessibilityRole="header" style={styles.title}>
        {t('profile.title')}
      </Text>
      <Text style={styles.section}>{t('profile.comparison')}</Text>
      <View style={styles.card}>
        <ValueRow
          label={t('profile.clubs')}
          value={clubCount === null ? null : String(clubCount)}
          onPress={() => router.push('/clubs', { dangerouslySingular: true })}
        />
        <View style={styles.divider} />
        <ValueRow
          label={t('profile.brands')}
          value={brandCount === null ? null : String(brandCount)}
          onPress={() => router.push('/brands', { dangerouslySingular: true })}
        />
        <View style={styles.divider} />
        <ValueRow
          label={t('profile.range')}
          value={range === null ? null : shownRange(range)}
          spokenValue={range === null ? null : spokenRange(range)}
          onPress={() => router.push('/range', { dangerouslySingular: true })}
        />
      </View>
      <AccountSection onNotice={setNotice} />
      {notice !== null && (
        <Text
          accessibilityRole="alert"
          accessibilityLiveRegion="polite"
          style={[styles.notice, notice === 'deleteFailed' && styles.danger]}
        >
          {t(`profile.deleteAccount.${notice}`)}
        </Text>
      )}
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
  danger: {
    color: colors.errorInk,
  },
  notice: {
    ...typography.meta,
    color: colors.inkSecondary,
    marginTop: spacing[2],
  },
});
