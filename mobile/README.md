# CartWise mobile

Expo SDK 56, React Native, TypeScript, Expo Router. Android only. The UI is Hebrew and forced RTL, light mode only.

## Layout

- `app/` -- routes (Expo Router). `app/(tabs)/` holds the 5 tabs: בית, רשימות, סריקה, הוצאות, פרופיל.
- `src/i18n/he.json` -- every user-facing string. Read them with `t("tabs.home")` from `src/i18n`.
- `src/theme/tokens.ts` -- colors, typography, radii, spacing. Mirrors the frontmatter of `docs/planning-artifacts/ux-designs/ux-CartWise-2026-10-26/DESIGN.md`.
- `src/rtl.ts` -- `ensureRTL()`, called by the root layout.
- `src/api/` -- `client.ts` (typed `openapi-fetch` client) and `schema.ts` (generated, do not edit).
- `src/identity/` -- `device.ts` (guest device token), `session.ts` (Google sign-in and the user session), `requireSignIn.ts` (opens SHEET-SIGNIN on demand).

## Run on Android

```sh
cd mobile
npm install
npx expo start          # then press "a" for a running emulator, or scan the QR code with Expo Go
```

The app calls the API at `EXPO_PUBLIC_API_URL`. The default, `http://10.0.2.2:8000`, is the host machine as seen from the Android emulator. On a physical device, point it at your computer's LAN address:

```sh
# PowerShell (Windows)
$env:EXPO_PUBLIC_API_URL='http://192.168.1.10:8000'; npx expo start

# bash / zsh
EXPO_PUBLIC_API_URL=http://192.168.1.10:8000 npx expo start
```

Start the backend first (see `backend/README.md`). Do not commit `.env` files.

RTL is set natively by the `expo-localization` plugin, so native builds start in RTL. Expo Go ignores that plugin: there `ensureRTL()` calls `I18nManager.forceRTL`, which only takes effect after a reload, so on the first launch in dev the app reloads itself once and then renders RTL.

## Google sign-in (Firebase)

Guests never sign in. Scanning asks for a Google account (SHEET-SIGNIN); the app then links the guest's device to that account through `POST /v1/auth/link`. The server stores only the Firebase uid; the first name stays on the phone.

The Firebase config is not secret, but it is specific to one Firebase project, so it is kept out of this public repo. Without it the app still builds and runs as a guest, and the Google button says sign-in is not set up yet. To enable it:

1. Create a Firebase project, add an Android app with package `app.cartwise`.
2. Authentication -> Sign-in method -> enable **Google**.
3. Add the SHA-1 of the signing key to the Android app. For the debug keystore:
   ```sh
   keytool -list -v -keystore ~/.android/debug.keystore -alias androiddebugkey -storepass android -keypass android
   ```
   (After `npx expo prebuild`, the project's own key is `android/app/debug.keystore`; add that SHA-1 too.)
4. Download `google-services.json` and put it at `mobile/google-services.json`. It is git-ignored; never commit it.
5. Set `FIREBASE_PROJECT_ID` (the project ID) for the backend, see `.env.example`.
6. Build a development build (`npx expo run:android`). Expo Go has no Firebase native modules.

`app.config.ts` adds the Firebase and Google sign-in plugins, and `android.googleServicesFile`, only when `google-services.json` exists. It reads the web OAuth client id (client type 3) from that file; `GOOGLE_WEB_CLIENT_ID` overrides it.

## API client

The API types are generated from the backend code, never written by hand:

```sh
npm run gen:api
```

This needs [uv](https://docs.astral.sh/uv/) and `../backend`, but no running server or database. It writes `openapi.json` and `src/api/schema.ts`; commit both.

## Checks

```sh
npm run lint
npm run typecheck
npm test
```
