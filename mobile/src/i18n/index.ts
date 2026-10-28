import he from './he.json';

type Dict = { [key: string]: string | Dict };

const strings: Dict = he;

/**
 * Look up a user-facing string by dotted key, e.g. t("tabs.home").
 * A missing key returns the key itself (and warns in dev) instead of throwing.
 */
export function t(key: string): string {
  let node: string | Dict | undefined = strings;
  for (const part of key.split('.')) {
    node = typeof node === 'object' ? node[part] : undefined;
    if (node === undefined) break;
  }
  if (typeof node === 'string') return node;
  if (__DEV__) console.warn(`[i18n] missing key: ${key}`);
  return key;
}
