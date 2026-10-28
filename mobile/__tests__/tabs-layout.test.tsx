import { fireEvent, renderRouter, screen } from 'expo-router/testing-library';

import TabsLayout from '../app/(tabs)/_layout';
import HomeScreen from '../app/(tabs)/index';
import ListsScreen from '../app/(tabs)/lists';
import ProfileScreen from '../app/(tabs)/profile';
import ScanScreen from '../app/(tabs)/scan';
import SpendingScreen from '../app/(tabs)/spending';

function renderTabs() {
  return renderRouter(
    {
      '(tabs)/_layout': TabsLayout,
      '(tabs)/index': HomeScreen,
      '(tabs)/lists': ListsScreen,
      '(tabs)/scan': ScanScreen,
      '(tabs)/spending': SpendingScreen,
      '(tabs)/profile': ProfileScreen,
    },
    { initialUrl: '/' },
  );
}

describe('tabs layout', () => {
  it('renders 5 tabs in order, each with a Hebrew accessibility label', () => {
    renderTabs();

    const tabs = screen.getAllByRole('tab');
    expect(tabs.map((tab) => tab.props.accessibilityLabel)).toEqual([
      'בית',
      'רשימות',
      'סריקה',
      'הוצאות',
      'פרופיל',
    ]);
    expect(screen.getByText('מסך הבית')).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'בית' })).toBeSelected();
    // The scan tab is the raised, round 56dp button.
    expect(screen.getByRole('tab', { name: 'סריקה' })).toHaveStyle({
      width: 56,
      height: 56,
      borderRadius: 9999,
    });
  });

  it('switches to the scan screen when the scan tab is pressed', () => {
    const router = renderTabs();

    fireEvent.press(screen.getByRole('tab', { name: 'סריקה' }));

    expect(router.getPathname()).toBe('/scan');
    expect(screen.getByText('סריקת קבלה')).toBeTruthy();
    const scanTab = screen.getByRole('tab', { name: 'סריקה' });
    expect(scanTab).toBeSelected();
    expect(scanTab).toHaveStyle({ borderWidth: 3 });
    expect(screen.getByRole('tab', { name: 'בית' })).not.toBeSelected();
  });
});
