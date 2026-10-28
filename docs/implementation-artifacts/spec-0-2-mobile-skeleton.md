---
title: 'Story 0.2: שלד האפליקציה'
type: 'chore'
created: '2026-10-28'
status: 'done'
baseline_revision: 'a185cb76001c101e18a2e81f00dad3b7ffc78bea'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/docs/implementation-artifacts/epic-0-context.md'
  - '{project-root}/docs/planning-artifacts/ux-designs/ux-CartWise-2026-10-26/DESIGN.md'
  - '{project-root}/CLAUDE.md'
warnings: ['oversized']
deferred:
  - summary: >-
      אין בדיקה אוטומטית ש-openapi.json ו-schema.ts מעודכנים מול ה-backend.
    evidence: |-
      maybe-false. כדי להכריע: צעד ב-CI שמריץ gen:api ואחריו git diff --exit-code על שני הקבצים. מתאים ל-Story 0.3.
    location: >-
      mobile/scripts/gen-api.mjs
    severity: medium (unverified)
---

<intent-contract>

## Intent

**Problem:** אין עדיין אפליקציה. כל ה-Stories של המסכים צריכות שלד Expo אחד, עם RTL, טוקני עיצוב, ניווט ולקוח API שנוצרים במקום אחד, כדי שלא כל מסך ימציא אותם מחדש.

**Approach:** פרויקט Expo SDK 56 ב-TypeScript, בתיקייה `mobile/`. Android בלבד. RTL מאולץ. מחרוזות מ-`he.json`. טוקנים מ-DESIGN.md. ניווט ב-Expo Router, עם 5 טאבים ו-placeholder בכל אחד. לקוח API שמיוצר מה-OpenAPI של ה-backend. lint, typecheck ובדיקות.

## Boundaries & Constraints

**Always:**
- כל טקסט שמוצג למשתמש מגיע מ-`src/i18n/he.json`, דרך פונקציה `t()`. אין טקסט עברי קשיח ב-JSX.
- כל צבע, גודל, רדיוס וריווח מגיעים מ-`src/theme/tokens.ts`, שמשקף את ה-frontmatter של DESIGN.md.
- הממשק RTL: הטאב הראשון ("בית") מימין. הגופן הוא Rubik.
- כל אזור מגע הוא 48dp לפחות, ולכל טאב יש `accessibilityLabel` בעברית.
- טיפוסי ה-API מיוצרים בלבד (AD-13). לא כותבים טיפוסי API ידנית.
- כתובת השרת מגיעה מ-`EXPO_PUBLIC_API_URL`. ברירת המחדל היא `http://10.0.2.2:8000`, כתובת המחשב המארח מתוך אמולטור Android.

**Never:**
- לא מוסיפים iOS, web, מסכים אמיתיים, auth, state management או ספריית i18n חיצונית.
- לא שומרים מפתחות, `.env` או סודות.
- מצב כהה (dark mode) כבוי, וגרדיאנטים לא בשימוש.
- אם פקודה נכשלת בשגיאת תעודה (NetFree): לא עוקפים. עוצרים ומדווחים (CLAUDE.md).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| מחרוזת קיימת | `t("tabs.home")` | `"בית"` | — |
| מפתח חסר | `t("no.such.key")` | מחזיר את המפתח עצמו (`"no.such.key"`), ובמצב dev רושם `console.warn` | לא זורק שגיאה |
| סדר הטאבים | רינדור ה-layout של הטאבים | 5 טאבים, בסדר: בית, רשימות, סריקה, הוצאות, פרופיל | — |
| RTL | הפעלת האפליקציה | `I18nManager.forceRTL(true)` ו-`allowRTL(true)` נקראים לפני הרינדור | — |
| ייצור לקוח API | `npm run gen:api` עם backend מקומי (בלי שרת רץ) | נוצרים `openapi.json` ו-`src/api/schema.ts`, ו-`client.ts` מוצא את `/v1/health` עם טיפוסים | אם uv או ה-backend חסרים: הודעת שגיאה ברורה, ויציאה עם קוד שונה מ-0 |

</intent-contract>

## Code Map

- `mobile/` -- לא קיים. פרויקט חדש.
- `backend/app/main.py` -- `create_app()` בונה את האפליקציה, ו-`app.openapi()` מחזיר את הסכמה בלי DB, כי ה-engine נוצר אבל לא מתחבר עד שמגיעה בקשה. `GET /v1/health` הוא ה-endpoint היחיד בשלב הזה.
- `docs/planning-artifacts/ux-designs/ux-CartWise-2026-10-26/DESIGN.md` -- ה-frontmatter (colors, typography, rounded, spacing, components.tab-bar) הוא המקור ל-`tokens.ts`.
- `docs/implementation-artifacts/spec-0-1-backend-skeleton.md` -- המוסכמות של Story 0.1: הריפו ציבורי, `.gitignore` לכל תיקייה, ו-README לכל חלק.
- `CLAUDE.md` -- כלל NetFree. npm במחשב הזה עובד, דרך `NODE_EXTRA_CA_CERTS` שהמשתמשת הגדירה.

## Tasks & Acceptance

**Execution:**
- `mobile/` (create-expo-app, `blank-typescript`, SDK 56) -- שלד פרויקט. ב-`package.json`: `expo ~56`, ו-`"main": "expo-router/entry"`.
- `mobile/app.json` -- `name: "CartWise"`, `slug: "cartwise"`, `platforms: ["android"]`, `android.package: "app.cartwise"`, `userInterfaceStyle: "light"`, `scheme: "cartwise"`. plugins: `expo-router`, `expo-font`, ו-`expo-localization` עם `{"supportsRTL": true, "forcesRTL": true}` -- RTL ברמת ה-native.
- `mobile/src/i18n/he.json`, `mobile/src/i18n/index.ts` -- מחרוזות הטאבים וה-placeholders. `t(key)` עם מפתחות מקוננים ונקודות, לפי המטריצה.
- `mobile/src/rtl.ts` -- `ensureRTL()`: קורא ל-`I18nManager.allowRTL(true)` ול-`forceRTL(true)`. נקרא ב-root layout.
- `mobile/src/theme/tokens.ts` -- אובייקט `tokens` עם `colors`, `typography`, `rounded`, `spacing` ו-`components.tabBar`, בערכים זהים ל-frontmatter של DESIGN.md. `fontFamily` לפי משקל: `Rubik_400Regular`, `Rubik_600SemiBold`, `Rubik_700Bold` ו-`Rubik_800ExtraBold`.
- `mobile/app/_layout.tsx` -- root: `ensureRTL()`, טעינת Rubik (`@expo-google-fonts/rubik`), splash עד שהגופנים נטענים, ו-`Stack` בלי header.
- `mobile/app/(tabs)/_layout.tsx` -- `Tabs`, עם 5 מסכים בסדר: index (בית), lists, scan, spending, profile. הצבעים לפי `tokens.components.tabBar`. לטאב הסריקה יש כפתור עגול ומוגבה בצבע primary, בגודל 56dp, עם צל. הכותרות מ-`t()`.
- `mobile/app/(tabs)/{index,lists,scan,spending,profile}.tsx` -- placeholder: כותרת מ-`t()` על רקע `surface-base`, בגופן Rubik.
- `mobile/scripts/gen-api.mjs`, `mobile/package.json` (script `gen:api`) -- מריץ `uv --directory ../backend run python -c "...json.dumps(create_app().openapi())..."` ושומר את `mobile/openapi.json`. אחר כך מריץ `openapi-typescript` שמייצר `src/api/schema.ts`. הקבצים שנוצרו נכנסים ל-git.
- `mobile/src/api/client.ts` -- `openapi-fetch` עם `paths` מ-`schema.ts`, ו-`baseUrl` מ-`EXPO_PUBLIC_API_URL`, עם ברירת המחדל.
- `mobile/package.json` -- scripts: `lint` (`expo lint`, eslint-config-expo), `typecheck` (`tsc --noEmit`), `test` (`jest`, preset `jest-expo`).
- `mobile/__tests__/` -- בדיקות: `t()` (מפתח קיים וחסר), `ensureRTL` (mock ל-I18nManager), טוקנים (primary `#7C3AED`, surface-base `#FBFAF7`, וגודל הטקסט של body 15), layout הטאבים (5 תוויות בסדר, עם `@testing-library/react-native`), ו-`client.ts` (ברירת מחדל ל-baseUrl).
- `mobile/.gitignore` -- מה ש-create-expo-app מייצר, ובנוסף `.env*`, `android/` ו-`ios/` (prebuild).
- `mobile/README.md` -- הרצה על אמולטור או מכשיר Android, `gen:api`, ובדיקות.

**Acceptance Criteria:**
- Given `mobile/`, when מריצים `npx expo start`, then Metro עולה בלי שגיאות. (אימות ידני על מכשיר Android לא נדרש בשלב הזה.)
- Given האפליקציה, then יש בדיוק 5 טאבים בסדר שהוגדר, הראשון מימין, ובטאב הסריקה כפתור מוגבה.
- Given `mobile/`, when מריצים `npm run lint && npm run typecheck && npm test`, then הכול עובר.
- Given backend מ-Story 0.1, when מריצים `npm run gen:api`, then `src/api/schema.ts` מכיל את `/v1/health`.

## Spec Change Log

## Review Triage Log

## Design Notes

- **RTL בשתי שכבות:** ה-plugin של expo-localization קובע RTL ב-native, כבר בהפעלה הראשונה. `I18nManager.forceRTL` נדרש בנוסף ל-Expo Go ולבדיקות. בלי השכבה של ה-native, השינוי נכנס לתוקף רק בהפעלה השנייה.
- **ייצור הסכמה מקוד ה-backend:** הסכמה נוצרת מהקוד, ולא מ-`/openapi.json` של שרת רץ. כך הסקריפט עובד בלי Docker, ו-CI יוכל לבדוק שהקובץ מעודכן.

## Verification

**Commands:**
- `cd mobile && npm install` -- expected: מסתיים בלי שגיאה. בשגיאת תעודה: עוצרים לפי CLAUDE.md.
- `cd mobile && npm run gen:api && grep -q "/v1/health" src/api/schema.ts` -- expected: הצלחה
- `cd mobile && npm run lint && npm run typecheck && npm test -- --ci` -- expected: הכול עובר
- `cd mobile && npx expo export --platform android --output-dir /tmp/cw-export` -- expected: ה-bundle נבנה בלי שגיאות. אחר כך מוחקים את התיקייה.

### 2026-10-28 — Review pass
- verdicts: 38 findings — high 0, medium 9, low 18, false 6, maybe-false 0 (+5 rows carried into groups)
- findings:
  - Intent Alignment:
    - `low` `patch` RTL בזמן ריצה לא נבדק — קבוצת RTL ב-Expo Go (reload כש-isRTL=false).
    - `low` `reject` "הטאב הראשון מימין" לא נבדק במיקום על המסך — jest לא מפעיל RTL ולא מחשב layout. הסדר נבדק, והמיקום תלוי ב-RTL שנבדק בנפרד.
    - `medium` `patch` הטוקנים לא מושווים ל-DESIGN.md — בדיקה שקוראת את ה-frontmatter.
    - `low` `reject` רינדור Rubik לא נבדק — דורש מכשיר. הטעינה נבדקת בבדיקת ה-root layout.
    - `false` `reject` schema.ts ו-openapi.json לא ב-diff — הוצאו במכוון כקבצים שנוצרו אוטומטית. הם קיימים, ונכנסים ל-commit.
    - `false` `reject` `expo start` לא נבדק — אומת ידנית: Metro עלה, ו-`expo export` ל-Android עבר.
    - `false` `reject` placeholder "סריקת קבלה" — תואם למונחי ה-UX (קבלה). ה-AC לא מגביל את הטקסט.
  - Blind Hunter:
    - `false` `reject` קבצים חסרים ב-diff (schema, lock, assets) — במכוון, ראו למעלה.
    - `maybe-false` `defer` אין בדיקה שה-schema מעודכן מול ה-backend — אין עדיין CI. יתווסף ב-Story 0.3.
    - `low` `patch` gen-api מניח stdout של JSON, וכותב את openapi.json לפני שבודק — כתיבה לקובץ זמני, ובדיקת ה-binary לפני הכתיבה.
    - `low` `patch` RTL ב-Expo Go בהפעלה הראשונה — `DevSettings.reload()` ב-dev כש-isRTL=false.
    - `medium` `patch` spies לא משוחזרים ב-rtl.test — `restoreAllMocks`, ו-spy בתוך isolateModules.
    - `medium` `patch` כפתור הסריקה: role ו-props לא מועברים — מעבירים את ה-props של ה-tab bar.
    - `medium` `patch` כפתור הסריקה בלי מצב נבחר — טבעת primary-tint כשהטאב פעיל (אותה קבוצה).
    - `low` `reject` אין אייקונים לטאבים — מחוץ להיקף השלד. האייקונים ייכנסו במסכים.
    - `medium` `patch` אין safe area במסכים — SafeAreaView ב-Placeholder.
    - `low` `reject` HTTP בלי הצפנה יחסום build של release — ברירת המחדל היא ל-dev בלבד. ב-prod יש HTTPS דרך Caddy (AD-1).
    - `low` `patch` פקודת env ב-README לא עובדת ב-Windows — נוספה צורה ל-PowerShell.
    - `low` `patch` `.env*` יסתיר `.env.example` — נוסף `!.env.example`.
    - `low` `reject` המפתחות של `t()` בלי טיפוס — אין שגיאה בשימוש יומיומי, ויש warn בזמן ריצה. טיפוס מפתחות הוא שינוי מבני.
    - `medium` `patch` בדיקת הטוקנים לא בודקת התאמה ל-DESIGN.md — אותה קבוצה כמו ב-Intent.
    - `low` `patch` כשל בטעינת גופן שקט — console.warn.
    - `medium` `patch` fontWeight יחד עם משפחת Rubik ב-Android — fontWeight הוסר מ-textStyle.
    - `low` `reject` חסרים ב-app.json versionCode, predictiveBack ו-+not-found — יוגדרו בפריסה (EAS) ובמסכים. predictiveBack false הוא ברירת המחדל של התבנית.
  - Edge Case Hunter:
    - `medium` `patch` aria-selected לא מועבר לכפתור הסריקה — קבוצת ה-props של כפתור הסריקה.
    - `medium` `patch` role "button" במקום tab ב-Android — אותה קבוצה.
    - `low` `patch` הבדיקות רצות על iOS כברירת מחדל — preset של jest-expo/android.
    - `medium` `patch` spies דולפים — קבוצת rtl.test.
    - `medium` `patch` instance אחר של I18nManager ב-isolateModules — קבוצת rtl.test.
    - `low` `patch` openapi.json נכתב לפני הבדיקה — קבוצת gen-api.
    - `low` `patch` spawn error מדווח "exit null" — קבוצת gen-api.
    - `low` `patch` rejection של ה-splash לא מטופל — `.catch`.
    - `low` `patch` טענת RTL בהפעלה הראשונה — קבוצת RTL.
  - Verification Gap:
    - `medium` `patch` לחיצה על טאב הסריקה לא נבדקת — נוספה בדיקת press.
    - `medium` `patch` ה-gating של splash וגופנים לא מרונדר — root-layout.test בשלושה מצבים.
    - `maybe-false` `defer` רענון ה-schema מול ה-backend — כמו בממצא של Blind Hunter. ייבדק ב-CI של Story 0.3.
    - `false` `reject` (other) קבצים שנוצרו לא ב-diff — במכוון.
    - `medium` `patch` (other) הטוקנים בקוד קשיח — קבוצת ה-frontmatter.

## Auto Run Result

Status: done

**סיכום:** שלד אפליקציה ב-`mobile/`: Expo SDK 56 (56.0.24, RN 0.85.3) ב-TypeScript, Android בלבד, עם Expo Router. RTL בשתי שכבות: plugin של expo-localization, ו-`ensureRTL` עם reload ב-dev. מחרוזות ב-`he.json` דרך `t()`. טוקנים מ-DESIGN.md, בגופן Rubik. 5 טאבים, עם כפתור סריקה מוגבה שמעביר את ה-props ומציג מצב נבחר. placeholders עם SafeArea. לקוח API (openapi-fetch) מטיפוסים שנוצרים מה-backend (`gen:api`).

**קבצים:** `mobile/app/` (שני ה-layouts ו-5 מסכים), `mobile/src/{i18n,theme,api,components,rtl.ts}`, `mobile/scripts/gen-api.mjs`, `mobile/openapi.json` ו-`mobile/src/api/schema.ts` (נוצרו אוטומטית), `mobile/__tests__/` (6 קבצים), `app.json`, `package.json` ו-lock, `babel.config.js`, `eslint.config.js`, `tsconfig.json`, `.gitignore`, `README.md`, `assets/`.

**ממצאי הסקירה:** 38 ממצאים. 13 קבוצות patch הוחלו (9 medium ו-low). 2 פריטים נדחו ל-deferred: בדיקה שה-schema מעודכן, ב-CI של Story 0.3. השאר נדחו או נמצאו false, והנימוק של כל אחד רשום ב-Review Triage Log.

**המלצה לסקירת המשך:** `true`. הוחלו כמה patches בדרגת medium: ה-props של כפתור הסריקה עם `PlatformPressable`, `DevSettings.reload` ב-RTL, ו-`babel.config.js` חדש ש-Metro קורא. כל אלה נבדקו בבדיקות וב-`expo export`, אבל לא עברו סקירה עצמאית נוספת, ולא הורצו על מכשיר.

**אימות:**
- `npm install`: אין שגיאות תעודה.
- `npm run gen:api`: ה-schema מכיל את `/v1/health`.
- `npm run lint` ו-`npm run typecheck` יצאו עם קוד 0. יש 4 warnings של `require` בבדיקות.
- `npm test -- --ci`: 63 בדיקות ב-6 suites עברו.
- `npx expo export --platform android`: עבר.

**סיכונים שנשארו:**
- האפליקציה לא הורצה על אמולטור או מכשיר Android.
- `expo-doctor` מתריע על בעיית זיכרון ב-Hermes ב-SDK 56.
- יש override לגרסת TypeScript עבור openapi-typescript.
- `@testing-library/react-native` נעול בגרסה 13.
