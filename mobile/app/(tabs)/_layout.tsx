import { Tabs } from 'expo-router';
import { PlatformPressable } from 'expo-router/react-navigation';
import type { BottomTabBarButtonProps } from 'expo-router/tabs';
import { StyleSheet, View } from 'react-native';

import { t } from '../../src/i18n';
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
 */
function ScanTabButton({ style: _style, ...props }: BottomTabBarButtonProps) {
  const selected = props.accessibilityState?.selected ?? props['aria-selected'] ?? false;
  return (
    <View style={styles.scanSlot}>
      <PlatformPressable {...props} style={[styles.scanFab, selected && styles.scanFabSelected]} />
    </View>
  );
}

export default function TabsLayout() {
  return (
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
