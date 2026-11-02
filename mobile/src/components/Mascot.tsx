import Svg, { Circle, Path, Rect } from 'react-native-svg';

import { tokens } from '../theme/tokens';

const { colors } = tokens;

const VIEW_WIDTH = 60;
const VIEW_HEIGHT = 52;
// The cheeks, from the mockup's symbol. DESIGN.md has no token for this color.
const CHEEK = '#F9A8D4';

/** The cart character from the mockups. `size` is its width. Decorative, and never animated. */
export function Mascot({ size = 120 }: { size?: number }) {
  return (
    <Svg
      testID="mascot"
      width={size}
      height={(size * VIEW_HEIGHT) / VIEW_WIDTH}
      viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
      accessible={false}
    >
      <Rect x={6} y={10} width={38} height={24} rx={9} fill={colors.lilacDecor} />
      <Rect x={40} y={2} width={16} height={18} rx={4} fill={colors.sky} />
      <Circle cx={18} cy={20} r={2.6} fill={colors.inkPrimary} />
      <Circle cx={31} cy={20} r={2.6} fill={colors.inkPrimary} />
      <Path
        d="M19 26 Q24.5 30 30 26"
        stroke={colors.inkPrimary}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
      />
      <Circle cx={12} cy={25} r={2} fill={CHEEK} />
      <Circle cx={37} cy={25} r={2} fill={CHEEK} />
      <Circle cx={14} cy={42} r={4} fill={colors.inkDisabled} />
      <Circle cx={34} cy={42} r={4} fill={colors.inkDisabled} />
    </Svg>
  );
}
