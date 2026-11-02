import { fireEvent, render, screen } from '@testing-library/react-native';
import { StyleSheet } from 'react-native';

import { RangePicker } from '../src/components/RangePicker';
import { tokens } from '../src/theme/tokens';

const onModeChange = jest.fn();
const onMinutesChange = jest.fn();

function renderPicker(mode: 'walk' | 'car' = 'car', minutes: 5 | 10 | 15 | 20 | 30 = 15) {
  return render(
    <RangePicker
      mode={mode}
      minutes={minutes}
      onModeChange={onModeChange}
      onMinutesChange={onMinutesChange}
    />,
  );
}

const radio = (name: string) => screen.getByRole('radio', { name });
const TRANSIT = 'ציבורית, בקרוב';

describe('RangePicker', () => {
  beforeEach(() => jest.clearAllMocks());

  it('offers walking, a car, and the fixed minutes, in order', () => {
    renderPicker();
    expect(screen.getAllByRole('radio').map((r) => r.props.accessibilityLabel)).toEqual([
      'הליכה',
      'רכב',
      TRANSIT,
      '5 דקות',
      '10 דקות',
      '15 דקות',
      '20 דקות',
      '30 דקות',
    ]);
    expect(screen.getByText('עד כמה דקות?')).toBeTruthy();
  });

  it('says which options are chosen, and only them', () => {
    renderPicker('walk', 10);
    const chosen = screen.getAllByRole('radio', { checked: true });
    expect(chosen.map((r) => r.props.accessibilityLabel)).toEqual(['הליכה', '10 דקות']);
  });

  it('shows a different choice when its props change', () => {
    const view = renderPicker('walk', 10);
    view.rerender(
      <RangePicker
        mode="car"
        minutes={30}
        onModeChange={onModeChange}
        onMinutesChange={onMinutesChange}
      />,
    );
    expect(screen.getByRole('radio', { name: 'רכב', checked: true })).toBeTruthy();
    expect(screen.getByRole('radio', { name: '30 דקות', checked: true })).toBeTruthy();
  });

  it('reports a chosen mode and chosen minutes, and changes nothing by itself', () => {
    renderPicker('car', 15);
    fireEvent.press(radio('הליכה'));
    expect(onModeChange).toHaveBeenCalledWith('walk');
    fireEvent.press(radio('20 דקות'));
    expect(onMinutesChange).toHaveBeenCalledWith(20);
    expect(screen.getByRole('radio', { name: 'רכב', checked: true })).toBeTruthy();
    expect(screen.getByRole('radio', { name: '15 דקות', checked: true })).toBeTruthy();
  });

  it('public transport is shown as coming soon, and pressing it does nothing', () => {
    renderPicker();
    expect(screen.getByText('🚌')).toBeTruthy();
    expect(screen.getByText('בקרוב')).toBeTruthy();
    const transit = radio(TRANSIT);
    expect(transit.props.accessibilityState).toMatchObject({ disabled: true, checked: false });
    fireEvent.press(transit);
    expect(onModeChange).not.toHaveBeenCalled();
    expect(onMinutesChange).not.toHaveBeenCalled();
    expect(screen.getByRole('radio', { name: 'רכב', checked: true })).toBeTruthy();
  });

  it('only public transport is disabled', () => {
    renderPicker();
    expect(screen.getAllByRole('radio', { disabled: true })).toHaveLength(1);
  });

  it('a chosen mode takes the same space as one that is not', () => {
    renderPicker('car');
    const inset = (name: string) => {
      const style = StyleSheet.flatten(radio(name).props.style);
      return [style.borderWidth + style.paddingHorizontal, style.borderWidth + style.paddingVertical];
    };
    expect(inset('רכב')).toEqual(inset('הליכה'));
  });

  it('every option is at least a full touch target', () => {
    renderPicker();
    for (const option of screen.getAllByRole('radio')) {
      expect(StyleSheet.flatten(option.props.style).minHeight).toBeGreaterThanOrEqual(
        tokens.touchTarget,
      );
    }
  });
});
