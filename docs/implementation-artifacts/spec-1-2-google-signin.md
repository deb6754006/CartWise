---
title: 'Story 1.2: הרשמה בחשבון Google בזמן הצורך'
type: 'feature'
created: '2026-10-28'
status: 'done'
baseline_revision: 'bc5469a58603724cd939f503cae9d8ac37326bcd'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/docs/implementation-artifacts/epic-1-context.md'
  - '{project-root}/docs/implementation-artifacts/spec-1-1-guest-identity.md'
  - '{project-root}/docs/planning-artifacts/architecture/architecture-CartWise-2026-10-26/ARCHITECTURE-SPINE.md'
  - '{project-root}/CLAUDE.md'
warnings: ['oversized']
deferred:
  - summary: >-
      הטריגר של המכסה ב-AC1, וההעברה בפועל של רשימות, העדפות ומכסה ב-AC2, קיימים רק כנקודות הרחבה.
    evidence: |-
      ה-modules נבנים ב-Epics 2 ו-8. כדי להכריע: לרשום transfer hooks ולקרוא ל-requireSignIn('quota'), עם בדיקות מקצה לקצה.
    severity: medium (unverified)
  - summary: >-
      מחיקת חשבון: משתמש שנמחק לא יכול להירשם שוב (firebase_uid ייחודי), ומכשיר של משתמש שנמחק מחזיר 409.
    evidence: |-
      להכריע ב-Story 1.7: anonymize ל-uid, וניתוק devices במחיקה.
    location: >-
      backend/app/modules/identity/service.py
    severity: medium (unverified)
  - summary: >-
      transfer hooks רצים רק ב-link הראשון, ונרשמים כ-side effect של import.
    evidence: |-
      נקודת רישום מפורשת תיקבע כשה-hook הראשון ייווצר (Epic 2).
    severity: low (unverified)
---

<intent-contract>

## Intent

**Problem:** אורח צריך להירשם רק כשזה נדרש, כלומר בסריקה או כשהמכסה נגמרת. ההרשמה היא בחשבון Google (FR-2), ואסור שיאבד משהו שנוצר כאורח. כרגע השרת מכיר רק Subject מסוג device, ואין משתמשים.

**Approach:** האפליקציה מתחברת ל-Google דרך Firebase Auth, ושולחת את ה-Firebase ID token ל-`POST /v1/auth/link`, יחד עם ה-device token. השרת מאמת את ה-ID token, יוצר או מאתר משתמש לפי `firebase_uid` בלבד, ומקשר אליו את המכשיר. אחר כך הוא מריץ את ה-hooks של העברת הנתונים, שמודולים אחרים רושמים. מעכשיו, בקשות עם ID token מזוהות כ-`Subject("user")`. באפליקציה, טאב הסריקה פותח אצל אורח את גיליון ההרשמה (SHEET-SIGNIN).

## Boundaries & Constraints

**Always:**
- נשמר רק `firebase_uid`. שם, מייל, טלפון, תמונה וכל claim אחר לא נשמרים בשרת ולא נכנסים ללוג (FR-2, AD-12). השם הפרטי מ-Google נשמר במכשיר בלבד, לברכה (UX §4).
- אימות ה-ID token: חתימת RS256 מול ה-JWKS הציבורי של Firebase (`securetoken@system.gserviceaccount.com`). בנוסף: `aud = FIREBASE_PROJECT_ID`, `iss = https://securetoken.google.com/<project>`, ו-`exp`, `iat` ו-`sub` לא ריקים. הקוד עובר דרך port: `FirebaseVerifier`. בבדיקות יש fake, ואין קריאות רשת.
- ה-link הוא idempotent. מכשיר שכבר מקושר לאותו משתמש מחזיר 200. מכשיר שמקושר למשתמש אחר מחזיר 409 `device_already_linked`.
- העברת הנתונים עוברת רק דרך ה-services של המודולים הבעלים (AD-2), כרשימת hooks שנרשמים ב-identity. כרגע אין עדיין רשימות, העדפות או מכסה, ולכן הרשימה ריקה. ה-hooks יירשמו ב-Stories של המודולים האלה.
- כשהמשתמש מבטל את ההתחברות באמצע (cancel ב-Google, או סגירת הגיליון), אין קריאה לשרת, והאפליקציה חוזרת למסך הקודם בלי שינוי.
- קונפיגורציית Firebase לא נכנסת לריפו. `google-services.json` ו-`FIREBASE_PROJECT_ID` מגיעים מקובץ מקומי או מ-env, עם placeholders ב-`.env.example`. כשהקונפיגורציה חסרה, האפליקציה נבנית ועובדת כאורח. כפתור Google מציג "ההתחברות עדיין לא הוגדרה", ולא קורס.

**Never:**
- אין Apple, אין iOS, ואין התחברות עם מייל וסיסמה.
- אין App Check. הוא נדחה ל-Story 10.3, יחד עם הגבלת הקצב.
- אין מחיקת חשבון (Story 1.7), ואין SHEET-QUOTA (Epic 8). כאן רק ה-trigger מהסריקה, ונקודת כניסה שתשמש את המכסה בהמשך.
- לא מבטלים ולא עוקפים בדיקות TLS (CLAUDE.md).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| link ראשון | `POST /v1/auth/link`. כותרת `Authorization: Bearer <firebase_id_token>`, וגוף `{"device_token": "..."}` | 201: `{"user_id"}`. נוצרים `users` (רק `firebase_uid`), ו-`devices.user_id`. ה-hooks רצים | — |
| link חוזר | אותו משתמש, ואותו מכשיר | 200, אותו `user_id`. ה-hooks לא רצים שוב | — |
| משתמש קיים, מכשיר חדש | `firebase_uid` קיים, ומכשיר חדש | 200 עם ה-`user_id` הקיים. המכשיר מקושר, וה-hooks רצים עבור המכשיר הזה | — |
| מכשיר של משתמש אחר | device כבר מקושר ל-user אחר | 409 `device_already_linked` | AD-13 |
| link בלי device_token | גוף בלי `device_token` | 201 או 200. המשתמש נוצר או מאותר, ואין קישור | — |
| ID token לא תקין | חתימה, `aud`, `iss` או `exp` שגויים | 401 `invalid_token` | ה-token לא מופיע בלוג |
| Firebase לא מוגדר | `FIREBASE_PROJECT_ID` ריק | 503 `auth_unavailable` על link ועל tokens של Firebase. ה-tokens של device ממשיכים לעבוד | — |
| בקשה עם ID token, משתמש מקושר | `GET /v1/me` | `{"kind":"user","id":"<user_id>"}` | — |
| ID token בלי user | `firebase_uid` שעוד לא עבר link | 401 `not_linked` | — |
| user שנמחק | `deleted_at` מוגדר | 401 `invalid_token` | — |
| אפליקציה: אורח לוחץ על סריקה | טאב סריקה, ואין session | נפתח SHEET-SIGNIN, ומסך הסריקה לא נפתח | — |
| אפליקציה: ביטול | cancel ב-Google, או "לא עכשיו" | הגיליון נסגר, אין קריאת link, ואין שינוי במצב | — |
| אפליקציה: הצלחה | Google ואחר כך link עם 2xx | session נשמר: user_id, ו-first name רק מקומית. ה-client עובר להשתמש ב-ID token (עם רענון). טאב הסריקה פותח את מסך הסריקה | — |
| אפליקציה: link נכשל | 4xx או 5xx, או רשת | הודעה בעברית בגיליון. ה-session לא נשמר, ויוצאים מ-Firebase | — |

</intent-contract>

## Code Map

- `backend/app/core/auth.py` -- ב-Story 1.1 נבנו `get_subject` (header קודם, session lazy, ו-503 ב-DB), `require_subject` ו-`auth_required()`. מרחיבים: כש-`alg` ב-header הוא RS256, מנתבים לאימות של Firebase.
- `backend/app/core/tokens.py` -- device tokens מסוג HS256. נשאר כמו שהוא.
- `backend/app/core/config.py` -- מוסיפים `FIREBASE_PROJECT_ID: str = ""` ו-`FIREBASE_JWKS_URL` (עם ברירת מחדל ציבורית).
- `backend/app/modules/identity/{models,repository,service,routes,schemas}.py` -- כבר קיימים: `Device` ו-register. מוסיפים `User`, link ו-hooks.
- `backend/migrations/versions/0002_devices.py` -- `devices.user_id` הוא nullable, בלי FK. במיגרציה החדשה `0003_users` מוסיפים FK ואינדקס.
- `backend/tests/integration/{conftest,pg}.py` -- fixtures של testcontainers ושל override ל-`get_session_factory`.
- `mobile/src/identity/device.ts` -- `ensureDeviceToken` ו-`getDeviceToken`. `mobile/src/api/client.ts` -- middleware של Authorization ו-retry. כאן הוא יעדיף user token כשיש session.
- `mobile/app/(tabs)/_layout.tsx` -- `ScanTabButton` שמעביר את ה-props. כאן מיירטים את הלחיצה אצל אורח.
- `mobile/src/i18n/he.json`, `mobile/src/theme/tokens.ts` -- המחרוזות והטוקנים. העיצוב של SHEET-SIGNIN לפי `mockups/screens-5-spend-profile.html` ו-EXPERIENCE §10.9.
- `mobile/app.json` -- plugins. יעבור ל-`app.config.ts`, כדי להוסיף את ה-plugins של Firebase רק כש-`google-services.json` קיים.

## Tasks & Acceptance

**Execution:**
- `backend/app/core/config.py` -- `FIREBASE_PROJECT_ID: str = ""` ו-`FIREBASE_JWKS_URL`. ב-prod, ערך ריק מותר (ה-auth פשוט לא זמין), ומתועד.
- `backend/app/core/firebase.py` -- `FirebaseVerifier` מסוג Protocol: `verify(id_token) -> firebase_uid`. `JwksFirebaseVerifier`: PyJWT עם `PyJWKClient` ו-cache, ובדיקות `aud`/`iss`/`exp`/`sub`. כל כשל מחזיר 401 `invalid_token`. אם הפרויקט לא מוגדר, 503 `auth_unavailable`. dependency בשם `get_firebase_verifier`, שאפשר להחליף (override).
- `backend/app/core/auth.py` -- ניתוב לפי ה-header של ה-JWT. HS256 עם `typ=device` הולך לנתיב הקיים. RS256 הולך ל-verifier, ואחריו `identity.service.user_for_firebase_uid`. אם אין משתמש: 401 `not_linked`. אם המשתמש נמחק: 401 `invalid_token`. אחרת: `Subject("user", user_id)`.
- `backend/app/modules/identity/models.py` -- `User`: `id` (uuid7), `firebase_uid` (unique, not null), `created_at`, `deleted_at` (nullable). FK מ-`Device.user_id`.
- `backend/migrations/versions/0003_users.py` -- טבלת `users`, FK ואינדקס על `devices.user_id`. downgrade.
- `backend/app/modules/identity/service.py` -- `link(firebase_uid, device_token | None) -> (user_id, created)`, לפי המטריצה. `register_transfer_hook(fn)` ו-`_TRANSFER_HOOKS`: כל hook מקבל `(session, from_device_id, to_user_id)`. ה-hooks רצים באותה טרנזקציה, ורק כשהמכשיר מקושר בפעם הראשונה.
- `backend/app/modules/identity/{schemas,routes}.py` -- `POST /v1/auth/link`, עם `LinkIn{device_token?}` ו-`LinkOut{user_id}`. מחזיר 201 או 200 לפי המטריצה. `/v1/me` תומך ב-`kind=user`.
- `backend/tests/unit/test_firebase.py` -- זוג מפתחות RSA מקומי ו-JWKS מזויף, בלי רשת: חתימה, aud, iss, exp, ופרויקט לא מוגדר.
- `backend/tests/integration/test_link.py` -- כל שורות המטריצה בצד השרת, עם fake verifier. בדיקה שה-hook רץ בדיוק פעם אחת. בדיקה שבטבלת `users` אין עמודות מעבר ל-`id`, `firebase_uid`, `created_at` ו-`deleted_at`.
- `mobile/app.config.ts` (במקום `app.json`) -- אותה קונפיגורציה. ה-plugins `@react-native-firebase/app`, `@react-native-firebase/auth` ו-`@react-native-google-signin/google-signin` נוספים רק אם `google-services.json` קיים. `android.googleServicesFile` מוגדר לפי אותו תנאי. ל-`.gitignore` כבר יש `google-services.json`.
- `mobile/package.json` -- להוסיף את הספריות דרך `npx expo install` (ו-`expo-build-properties`, אם נדרש).
- `mobile/src/identity/session.ts` -- `signInWithGoogle()`: Google, אחר כך Firebase credential, אחר כך ID token, ואז `POST /v1/auth/link` עם ה-device token. בהצלחה, נשמר `session {userId, firstName}` ב-secure-store. `getUserIdToken()` מחזיר ID token מרוענן, `isSignedIn()` ו-`signOut()`. ביטול מחזיר `{status: "cancelled"}` בלי קריאה לשרת. כשהספריות או הקונפיגורציה חסרות, מחזיר `{status: "unavailable"}`.
- `mobile/src/api/client.ts` -- כשיש session, ה-Authorization הוא ה-ID token. אחרת, device token. ה-retry ב-401 נשאר כפי שהוא עבור device. עבור user: רענון אחד של ה-ID token, ואז ניסיון חוזר.
- `mobile/src/components/SignInSheet.tsx` -- לפי EXPERIENCE §10.9: כותרת, תת-כותרת, כפתור "המשך עם Google", "🔒 אנחנו לא שומרים שם, מייל, טלפון או כתובת" ו-"לא עכשיו". מצבי טעינה ושגיאה, מחרוזות מ-`he.json` וטוקנים.
- `mobile/app/(tabs)/_layout.tsx` -- `ScanTabButton`: אצל אורח, הלחיצה פותחת את `SignInSheet`, במקום ניווט לטאב. אחרי הצלחה, ניווט לסריקה.
- `mobile/src/identity/requireSignIn.ts` -- `requireSignIn(reason)`: hook או פונקציה לפתיחת הגיליון. ישמש גם את המכסה (Epic 8).
- `mobile/__tests__/session.test.ts`, `signin-sheet.test.tsx`, ותוספות ל-`tabs-layout` ול-`client` -- שורות המטריצה בצד האפליקציה, עם mocks לספריות.
- `mobile/openapi.json`, `mobile/src/api/schema.ts` -- `npm run gen:api`.
- `.env.example` -- `FIREBASE_PROJECT_ID` (backend), והערה על `google-services.json` ב-`mobile/`, שלא נכנס ל-git.
- `mobile/README.md` -- איך מגדירים פרויקט Firebase (Google sign-in, SHA-1 של ה-debug keystore) ואיפה שמים את `google-services.json`.

**Acceptance Criteria:**
- Given אורח, when הוא לוחץ על סריקה, then נפתח SHEET-SIGNIN עם Google. כשמבטלים, חוזרים בלי שינוי.
- Given הרשמה מוצלחת, then המכשיר מקושר למשתמש, וה-hooks של העברת הנתונים רצים פעם אחת. כרגע אין hooks רשומים, ובבדיקה hook דמה מוודא את זה.
- Given טבלת `users`, then נשמר בה רק `firebase_uid`, וזה נבדק.
- Given שאין קונפיגורציית Firebase, then האפליקציה נבנית (`expo export`), עובדת כאורח, והכפתור מציג "עדיין לא הוגדר".

## Spec Change Log

## Review Triage Log

## Design Notes

- **בלי firebase-admin:** אימות דרך JWKS ו-PyJWT, שכבר קיים. אין תלות כבדה, ואפשר לבדוק בלי רשת. בזמן ריצה, ה-JWKS נטען מ-Google. ב-NetFree זה דורש תעודה, אבל זה רלוונטי רק בהרצה מקומית מול Firebase אמיתי.
- **בדיקה ידנית אמיתית:** דורשת מהמשתמשת פרויקט Firebase, הפעלה של Google sign-in, SHA-1 ו-`google-services.json`. בלי אלה, הכול נבדק עם mocks ו-fakes, והאפליקציה עובדת כאורח.

## Verification

**Commands:**
- `cd backend && uv sync --locked && uv run ruff check . && uv run ruff format --check . && uv run mypy app && CARTWISE_REQUIRE_DOCKER=1 uv run pytest -q` -- expected: הכול עובר
- `cd mobile && npm run gen:api && npm run lint && npm run typecheck && npm test -- --ci` -- expected: עובר
- `cd mobile && npx expo export --platform android --output-dir <tmp>` (בלי `google-services.json`) -- expected: נבנה. אחר כך מוחקים את התיקייה.

### 2026-10-29 — Review pass
- verdicts: 31 findings — high 0, medium 13, low 10, false 3, maybe-false 5
- findings:
  - Intent Alignment:
    - `maybe-false` `defer` הטריגר של המכסה ב-AC1, וההעברה בפועל של רשימות, העדפות ומכסה ב-AC2, קיימים רק כנקודות הרחבה (`requireSignIn('quota')`, `register_transfer_hook`) — ה-modules האלה נבנים ב-Epics 2 ו-8, לפי סדר הבנייה. ה-mechanism נבדק עם hook דמה.
    - `false` `reject` AC3 ו-AC4 — מומשו ונבדקו: עמודות `users` ומסלולי ביטול.
  - Verification Gap:
    - `medium` `patch` מסלול של משתמש מחובר אחרי הפעלה מחדש (`getCachedSession` undefined) לא נבדק — בדיקת tabs-layout ובדיקת unit ל-requireSignIn.
    - `medium` `patch` race של link לא נבדק — בדיקה מקבילית עם threads.
    - `medium` `patch` אין בדיקות ל-`app.config.ts` — `app-config.test.ts`.
    - `low` `patch` (other) `loadSession` לא נקרא בהפעלה — נקרא ב-bootstrap.
  - Edge Case Hunter:
    - `low` `defer` device token שנמחק מה-DB מחזיר 401 ב-link — הלקוח יקבל `invalid_token` וירשם מחדש בבקשה הבאה. retry ב-link יבוא בהמשך.
    - `medium` `patch` 401 שנשאר אחרי רענון אצל משתמש — signOut ו-retry עם device.
    - `maybe-false` `reject` fallback ל-device ב-503 של auth_unavailable — יוצר נתונים שמשויכים למכשיר אחרי link, ולא יועברו. עדיף להציג שגיאה. תקלה ב-auth היא נדירה.
    - `medium` `patch` session מקומי בלי משתמש ב-Firebase — `onAuthStateChanged`, וניקוי.
    - `low` `patch` לחיצה לפני `loadSession` — loadSession ב-bootstrap (אותה קבוצה).
    - `medium` `patch` refetch של JWKS לכל kid לא מוכר — לכל היותר רענון אחד בכל 60 שניות.
    - `low` `patch` JWKS שאינו JSON מחזיר 500 — 503.
    - `maybe-false` `defer` מכשיר של משתמש שנמחק מחזיר 409 — שייך ל-Story 1.7 (מחיקת חשבון: ניתוק devices ו-anonymize).
    - `low` `patch` firstName שאינו string — בדיקת טיפוס.
    - `low` `reject` (claim) 503 במקום 401 כש-JWKS לא זמין — סטייה מכוונת: זו תקלה ולא token רע, ו-401 היה גורם ל-refresh מיותר.
  - Blind Hunter:
    - `medium` `patch` JWKS לכל kid — אותה קבוצה.
    - `low` `patch` `auth_time` לא נבדק — require, ולא בעתיד.
    - `medium` `patch` 401 שלא נגמר אצל משתמש — אותה קבוצה.
    - `medium` `patch` session בלי משתמש ב-Firebase — אותה קבוצה.
    - `medium` `patch` חשבון שני על אותו מכשיר נחסם — retry בלי device_token כשמתקבל 409.
    - `maybe-false` `defer` משתמש שנמחק לא יוכל להירשם שוב — החלטה של Story 1.7: anonymize ל-uid במחיקה.
    - `maybe-false` `defer` hooks רק ב-link ראשון, ורישום דרך import — נקודת רישום מפורשת תיקבע כשה-hook הראשון ייווצר (Epic 2).
    - `medium` `patch` אין בדיקת מקביליות — אותה קבוצה.
    - `low` `patch` פערי בדיקות (503 ב-/me, timeout, idToken, hasPlayServices, downgrade מלא) — נוספו.
    - `low` `patch` ניסוח ב-README — תוקן.
    - `false` `reject` קבצים שנוצרו אוטומטית ו-lock לא ב-diff — במכוון. gen:api ו-api-schema ב-CI.
    - `medium` `patch` "G" כטקסט במקום הלוגו הרשמי — SVG רשמי, לפי הנחיות המיתוג של Google.

## Auto Run Result

Status: done

**סיכום:** הרשמה עם Google בזמן הצורך.
- **backend:**
  - טבלת `users`, שבה נשמר רק `firebase_uid`.
  - אימות Firebase ID token מול JWKS: RS256, aud, iss, exp, iat ו-auth_time. kid לא מוכר מרענן לכל היותר פעם ב-60 שניות, ותקלה ב-JWKS מחזירה 503.
  - `POST /v1/auth/link`, עם 201 או 200 ו-409, מוגן מפני race, ו-transfer hooks בטרנזקציה אחת.
  - Subject מסוג user.
- **mobile:**
  - `session.ts`: Google, אחר כך Firebase, ואז link. ביטול לא משנה דבר. retry בלי device_token כשמתקבל 409. סנכרון עם `onAuthStateChanged`.
  - client: מעדיף את ה-user token, ובכשל עובר ל-signOut ול-device token.
  - `SignInSheet` עם הלוגו הרשמי של G, ו-`requireSignIn` שמחובר לטאב הסריקה.
  - `app.config.ts` עם plugins של Firebase, רק כש-`google-services.json` קיים.

**ממצאי הסקירה:** 31 ממצאים. 18 patches הוחלו, 13 מהם medium. 3 פריטים נדחו ל-deferred: AC1 ו-AC2 מקצה לקצה, מחיקה ורישום מחדש, ונקודת הרישום של ה-hooks. השאר נדחו או נמצאו false, והנימוק של כל אחד רשום ב-Review Triage Log.

**המלצה לסקירת המשך:** `true`. היו patches רבים בדרגת medium: ה-cache של JWKS, ה-fallback ב-client, סנכרון ה-session וה-retry של 409. הם נבדקו ביחידה, אבל לא עברו סקירה עצמאית נוספת, ולא נבדקו מול פרויקט Firebase אמיתי או build של native.

**אימות:**
- backend: ruff, format ו-mypy עברו. `CARTWISE_REQUIRE_DOCKER=1 pytest`: 165 עברו.
- mobile: lint, typecheck ו-155 בדיקות עברו. `gen:api` עודכן.
- `expo export` ל-Android בלי `google-services.json`: עבר.
- gitleaks: `no leaks found`.

**סיכונים שנשארו:**
- לא נבדק מול Firebase אמיתי.
- build של Gradle בלי `google-services.json` לא נוסה, כי ה-modules של native מקושרים.
- ה-tokens של `components.sheet` לא נמצאים ב-frontmatter של DESIGN.md.
