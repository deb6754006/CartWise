import { readFileSync } from 'fs';
import { load } from 'js-yaml';
import { join } from 'path';

import { tokens, type Weight } from '../src/theme/tokens';

type TypeSpec = { fontFamily: string; fontSize: string; fontWeight: number; lineHeight: number };
type Design = {
  colors: Record<string, string>;
  typography: Record<string, TypeSpec>;
  rounded: Record<string, string>;
  spacing: Record<string, string>;
  components: { 'tab-bar': Record<string, string> };
};

const designPath = join(
  __dirname,
  '../../docs/planning-artifacts/ux-designs/ux-CartWise-2026-10-26/DESIGN.md',
);
const frontmatter = readFileSync(designPath, 'utf8').match(/^---\r?\n([\s\S]*?)\r?\n---/);
if (!frontmatter) throw new Error(`no YAML frontmatter in ${designPath}`);
const design = load(frontmatter[1]) as Design;

const camel = (key: string) => key.replace(/-([a-z0-9])/g, (_, c: string) => c.toUpperCase());
const px = (value: string) => Number(value.replace(/px$/, ''));
/** Resolve a "{colors.primary}" reference against the DESIGN.md colors. */
const ref = (value: string) => value.replace(/^\{colors\.(.+)\}$/, (_, k: string) => design.colors[k]);

function lookup<T>(table: object, key: string): T {
  if (!(key in table)) throw new Error(`tokens.ts is missing "${key}"`);
  return (table as Record<string, T>)[key];
}

describe('tokens mirror the DESIGN.md frontmatter', () => {
  it.each(Object.entries(design.colors))('colors.%s', (key, value) => {
    expect(lookup<string>(tokens.colors, camel(key))).toBe(value);
  });

  it('has no colors that DESIGN.md does not define', () => {
    expect(Object.keys(tokens.colors).sort()).toEqual(Object.keys(design.colors).map(camel).sort());
  });

  it.each(Object.entries(design.typography))('typography.%s', (key, spec) => {
    const style = lookup<{ fontFamily: string; fontSize: number; lineHeight: number }>(
      tokens.typography,
      camel(key),
    );
    expect(spec.fontFamily).toBe('Rubik');
    expect(style.fontSize).toBe(px(spec.fontSize));
    expect(style.fontFamily).toBe(tokens.fontFamily[spec.fontWeight as Weight]);
    expect(style.lineHeight).toBe(Math.round(px(spec.fontSize) * spec.lineHeight));
    // The weight lives in the family name only.
    expect(style).not.toHaveProperty('fontWeight');
  });

  it.each(Object.entries(design.rounded))('rounded.%s', (key, value) => {
    expect(lookup<number>(tokens.rounded, camel(key))).toBe(px(value));
  });

  it.each(Object.entries(design.spacing))('spacing.%s', (key, value) => {
    expect(lookup<number>(tokens.spacing, camel(key))).toBe(px(value));
  });

  it.each(Object.entries(design.components['tab-bar']))('components.tab-bar.%s', (key, value) => {
    expect(lookup<string>(tokens.components.tabBar, camel(key))).toBe(ref(value));
  });

  it('keeps touch targets at 48dp or more', () => {
    expect(tokens.touchTarget).toBeGreaterThanOrEqual(48);
    expect(tokens.components.tabBar.scanFabSize).toBeGreaterThanOrEqual(tokens.touchTarget);
  });
});
