import { mkdtempSync, rmSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

import type { ConfigContext, ExpoConfig } from 'expo/config';

import appConfig from '../app.config';

// Placeholder values only: never real Firebase config in the repo.
const FIXTURE = {
  project_info: { project_id: 'placeholder-project' },
  client: [
    {
      oauth_client: [
        { client_id: 'placeholder-android.apps.googleusercontent.com', client_type: 1 },
        { client_id: 'placeholder-web.apps.googleusercontent.com', client_type: 3 },
      ],
    },
  ],
};
const FIREBASE_PLUGINS = [
  '@react-native-firebase/app',
  '@react-native-firebase/auth',
  '@react-native-google-signin/google-signin',
];

let root: string;

function build(): ExpoConfig {
  return appConfig({ config: {}, projectRoot: root } as unknown as ConfigContext);
}

const pluginNames = (c: ExpoConfig) =>
  (c.plugins ?? []).map((p) => (Array.isArray(p) ? p[0] : p) as string);

describe('app.config.ts', () => {
  const originalOverride = process.env.GOOGLE_WEB_CLIENT_ID;

  beforeEach(() => {
    root = mkdtempSync(join(tmpdir(), 'cartwise-app-config-'));
    delete process.env.GOOGLE_WEB_CLIENT_ID;
  });

  afterEach(() => {
    rmSync(root, { recursive: true, force: true });
    if (originalOverride === undefined) delete process.env.GOOGLE_WEB_CLIENT_ID;
    else process.env.GOOGLE_WEB_CLIENT_ID = originalOverride;
  });

  it('without google-services.json: guest-only build, every expo plugin kept', () => {
    const c = build();
    expect(c.extra?.googleWebClientId).toBe('');
    expect(c.android?.googleServicesFile).toBeUndefined();
    const names = pluginNames(c);
    for (const p of FIREBASE_PLUGINS) expect(names).not.toContain(p);
    expect(names).toEqual([
      'expo-router',
      'expo-font',
      'expo-localization',
      'expo-splash-screen',
      'expo-status-bar',
      'expo-asset',
      'expo-secure-store',
    ]);
    expect(c.plugins).toContainEqual(['expo-localization', { supportsRTL: true, forcesRTL: true }]);
    expect(c.android?.package).toBe('app.cartwise');
    expect(c.platforms).toEqual(['android']);
  });

  it('with google-services.json: the web (type 3) client id, plugins and the file', () => {
    writeFileSync(join(root, 'google-services.json'), JSON.stringify(FIXTURE));
    const c = build();
    expect(c.extra?.googleWebClientId).toBe('placeholder-web.apps.googleusercontent.com');
    expect(c.android?.googleServicesFile).toBe('./google-services.json');
    const names = pluginNames(c);
    for (const p of FIREBASE_PLUGINS) expect(names).toContain(p);
    expect(names).toContain('expo-secure-store');
    expect(names).toContain('expo-localization');
  });

  it('GOOGLE_WEB_CLIENT_ID overrides the id from the file', () => {
    writeFileSync(join(root, 'google-services.json'), JSON.stringify(FIXTURE));
    process.env.GOOGLE_WEB_CLIENT_ID = 'placeholder-override.apps.googleusercontent.com';
    expect(build().extra?.googleWebClientId).toBe(
      'placeholder-override.apps.googleusercontent.com',
    );
  });
});
