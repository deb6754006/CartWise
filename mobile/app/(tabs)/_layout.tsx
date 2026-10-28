import { Tabs, useRouter } from 'expo-router';
import { PlatformPressable } from 'expo-router/react-navigation';
import type { BottomTabBarButtonProps } from 'expo-router/tabs';
import { StyleSheet, View } from 'react-native';

import { SignInHost } from '../../src/components/SignInHost';
import { t } from '../../src/i18n';
import { requireSignIn } from '../../src/identity/requireSignIn';
import { getCachedSession } from '../../src/identity/session';
import { tokens } from '../../src/theme/tokens';

const { tabBar } = tokens.components;

/** Tab order, start (right, in RTL) to end. */
const TAB_ROUTES = [
  { name: 'index', labelKey: 'tabs.home' },
  { name: 'lists', labelKey: 'tabs.lists' },
  { name: 'scan', labelKey: 'tabs.scan' },
  { name: 'spending', labelKey: 'tabs.spending' },
  { name: 'profile', labelKey: 'tabs.profile' },
] as const;

/**
 * The raised, round scan button in the middle of the tab bar.
 * Everything the tab bar passes (role, label, selected state, press handlers, href,
 * testID, children) is forwarded; only the style is ours.
 * Scanning needs an account: a guest's press opens SHEET-SIGNIN instead, and the scan
 * screen opens only after a successful sign-in (cancelling leaves everything as it was).
 */
function ScanTabButton({ style: _style, onPress, ...props }: BottomTabBarButtonProps) {
  const router = useRouter();
  const selected = props.accessibilityState?.selected ?? props['aria-selected'] ?? false;
  const handlePress: NonNullable<BottomTabBarButtonProps['onPress']> = (event) => {
    if (getCachedSession()) {
      onPress?.(event);
      return;
    }
    requireSignIn('scan')
      .then((signedIn) => {
        if (signedIn) router.navigate('/scan');
      })
      .catch(() => {});
  };
  return (
    <View style={styles.scanSlot}>
      <PlatformPressable
        {...props}
        onPress={handlePress}
        style={[styles.scanFab, selected && styles.scanFabSelected]}
      />
    </View>
  );
}

export default function TabsLayout() {
  return (
    <>
      <Tabs
        screenOptions={{
          headerShown: false,
          tabBarActiveTintColor: tabBar.active,
          tabBarInactiveTintColor: tabBar.inactive,
          tabBarStyle: { backgroundColor: tabBar.background, borderTopColor: tokens.colors.borderHairline },
          tabBarItemStyle: { minHeight: tokens.touchTarget },
          tabBarLabelStyle: { ...tokens.typography.meta },
          tabBarIcon: () => null,
          sceneStyle: { backgroundColor: tokens.colors.surfaceBase },
        }}
      >
        {TAB_ROUTES.map(({ name, labelKey }) => (
          <Tabs.Screen
            key={name}
            name={name}
            options={{
              title: t(labelKey),
              tabBarAccessibilityLabel: t(labelKey),
              ...(name === 'scan'
                ? {
                    tabBarButton: (props) => <ScanTabButton {...props} />,
                    // The label sits on the primary circle.
                    tabBarActiveTintColor: tokens.colors.onPrimary,
                    tabBarInactiveTintColor: tokens.colors.onPrimary,
                    tabBarLabelStyle: { ...tokens.typography.meta, fontFamily: tokens.fontFamily[600] },
                  }
                : {}),
            }}
          />
        ))}
      </Tabs>
      <SignInHost />
    </>
  );
}

const styles = StyleSheet.create({
  scanSlot: {
    flex: 1,
    alignItems: 'center',
  },
  scanFab: {
    width: tabBar.scanFabSize,
    height: tabBar.scanFabSize,
    borderRadius: tokens.rounded.full,
    backgroundColor: tabBar.scanFab,
    alignItems: 'center',
    justifyContent: 'center',
    // Lift the button above the bar.
    marginTop: -tokens.spacing[5],
    ...tabBar.scanFabShadow,
  },
  scanFabSelected: tabBar.scanFabSelectedRing,
});
