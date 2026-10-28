/**
 * Design tokens. Mirrors the frontmatter of
 * docs/planning-artifacts/ux-designs/ux-CartWise-2026-10-26/DESIGN.md.
 * Keep the two in sync: change DESIGN.md first, then this file.
 */

const colors = {
  surfaceBase: '#FBFAF7',
  surfaceRaised: '#FFFFFF',
  surfaceSunken: '#F3F1EC',
  inkPrimary: '#374151',
  inkSecondary: '#78716C',
  inkDisabled: '#A8A29E',
  borderHairline: '#EFECE6',
  borderStrong: '#E7E5E4',
  primary: '#7C3AED',
  primarySoft: '#8B5CF6',
  primaryTint: '#F5F3FF',
  onPrimary: '#FFFFFF',
  sky: '#7DD3FC',
  skyTint: '#F0F9FF',
  skyInk: '#0369A1',
  skyDecor: '#E0F2FE',
  lilacDecor: '#DDD6FE',
  estimateBg: '#FEF3C7',
  estimateInk: '#92400E',
  reliabilityGreen: '#16A34A',
  reliabilityYellow: '#CA8A04',
  reliabilityRed: '#DC2626',
  errorInk: '#B91C1C',
  errorTint: '#FEF2F2',
  successTint: '#F0FDF4',
} as const;

/** Rubik font family name per weight, as registered by @expo-google-fonts/rubik. */
export const fontFamily = {
  400: 'Rubik_400Regular',
  600: 'Rubik_600SemiBold',
  700: 'Rubik_700Bold',
  800: 'Rubik_800ExtraBold',
} as const;

export type Weight = keyof typeof fontFamily;

/**
 * The weight is carried by the Rubik family name only. Setting fontWeight as well can
 * make Android synthesize bold or fall back to the system font.
 * DESIGN.md gives line height as a ratio; React Native needs it in dp.
 */
function textStyle(fontSize: number, weight: Weight, lineHeightRatio: number) {
  return {
    fontFamily: fontFamily[weight],
    fontSize,
    lineHeight: Math.round(fontSize * lineHeightRatio),
  };
}

const typography = {
  display: textStyle(24, 700, 1.3),
  title: textStyle(20, 700, 1.35),
  heading: textStyle(16, 600, 1.4),
  body: textStyle(15, 400, 1.5),
  meta: textStyle(13, 400, 1.45),
  priceLg: { ...textStyle(20, 800, 1.2), fontVariant: ['tabular-nums'] as const },
  price: { ...textStyle(15, 600, 1.3), fontVariant: ['tabular-nums'] as const },
} as const;

const rounded = {
  sm: 8,
  md: 12,
  lg: 18,
  full: 9999,
} as const;

const spacing = {
  1: 4,
  2: 8,
  3: 12,
  4: 16,
  5: 24,
  6: 32,
  marginMobile: 16,
} as const;

/** Minimum touch target, in dp. */
const touchTarget = 48;

const components = {
  /** Bottom sheets (white, top corners rounded), per the SHEET-* mockups. */
  sheet: {
    background: colors.surfaceRaised,
    radius: rounded.lg,
    grabber: colors.borderStrong,
    grabberWidth: 40,
    grabberHeight: 4,
    /** Dims the screen behind a sheet (inkPrimary at 35%). */
    scrim: 'rgba(55, 65, 81, 0.35)',
  },
  tabBar: {
    background: '#FFFDF9',
    active: colors.primary,
    inactive: colors.inkSecondary,
    scanFab: colors.primary,
    scanFabSize: 56,
    /** Ring drawn on the scan button while its tab is selected. */
    scanFabSelectedRing: { borderWidth: 3, borderColor: colors.lilacDecor },
    /** The scan button is the only component with a prominent shadow. */
    scanFabShadow: {
      shadowColor: colors.inkPrimary,
      shadowOpacity: 0.25,
      shadowRadius: 8,
      shadowOffset: { width: 0, height: 4 },
      elevation: 6,
    },
  },
} as const;

export const tokens = {
  colors,
  fontFamily,
  typography,
  rounded,
  spacing,
  touchTarget,
  components,
} as const;

export type Tokens = typeof tokens;
