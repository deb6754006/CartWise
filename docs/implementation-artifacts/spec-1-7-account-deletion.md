---
title: 'Story 1.7: מחיקת חשבון'
type: 'feature'
created: '2026-11-03'
status: 'done'
baseline_revision: 'cde3d100a11c05b13f996656e8f4d5a58e32a93e'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/docs/implementation-artifacts/epic-1-context.md'
  - '{project-root}/docs/implementation-artifacts/spec-1-2-google-signin.md'
  - '{project-root}/docs/planning-artifacts/architecture/architecture-CartWise-2026-10-26/ARCHITECTURE-SPINE.md'
  - '{project-root}/CLAUDE.md'
warnings: ['oversized']
deferred:
  - summary: >-
      רשימות, סיכום הוצאות ותצפיות מחיר עדיין לא קיימים, ולכן מחיקתם או ניתוקם לא נבדקים מקצה לקצה.
    evidence: |-
      הם נבנים ב-Epics 2, 6 ו-9. כאן יש נקודת הרחבה: `register_deletion_hook`. כדי להכריע: כל מודול בעלים רושם hook (רשימות וחשבוניות נמחקות, `contributor_user_id` מתאפס ל-NULL), עם בדיקה.
    severity: medium (unverified)
  - summary: >-
      ה-worker רץ רק ב-compose המקומי. ב-production הוא יתווסף עם ה-compose של הפריסה.
    evidence: |-
      `deploy/docker-compose.yml` הוא לפיתוח בלבד. כדי להכריע: לכלול את השירות `worker` ב-compose של הפריסה.
    severity: medium (unverified)
  - summary: >-
      אם מחיקת המשתמש ב-Firebase נכשלת, או שהמשתמש מבטל את ההתחברות מחדש, החשבון ב-Firebase, עם המייל, נשאר.
    evidence: |-
      בלי Firebase Admin SDK, המחיקה אפשרית רק מהלקוח, ואחרי `signOut` אין דרך לנסות שוב. כדי להכריע: החלטה של המשתמשת אם להוסיף מפתח service account (ב-`.env` בשרת בלבד) ומחיקה מהשרת.
    location: >-
      mobile/src/identity/session.ts
    severity: medium
  - summary: >-
      אין בדיקה לשתי ריצות purge במקביל (`SKIP LOCKED`).
    evidence: |-
      עדיין אין purge hooks רשומים, ולכן הרצה כפולה לא נראית היום. כדי להכריע: להוסיף את הבדיקה עם ה-purge hook הראשון (Epics 2, 6, 9).
    location: >-
      backend/app/modules/identity/repository.py
    severity: low
---

<intent-contract>

## Intent

**Problem:** משתמש רשום לא יכול למחוק את החשבון שלו (FR-6). בנוסף, מ-Story 1.2 נשאר פער: משתמש שנמחק לא יוכל להירשם מחדש, כי `firebase_uid` ייחודי, ומכשיר שלו יחזיר 409.

**Approach:** `DELETE /v1/me` מוחק את החשבון מיד (soft delete): המשתמש מנותק, הנתונים האישיים שבבעלות identity נמחקים, ו-hooks של מודולים אחרים רצים. job יומי ב-worker מוחק את השורה סופית, ומריץ hooks של מחיקה סופית, לכל משתמש שנמחק לפני יותר מ-30 יום. באפליקציה יש שורה "מחיקת חשבון" בפרופיל, עם אישור.

## Boundaries & Constraints

**Always:**
- **מחיקה מיידית, בטרנזקציה אחת:**
  - `deleted_at` מוגדר.
  - `firebase_uid` מוחלף בערך שאינו מזהה, כמו `deleted:<user_id>`, כך שאותו חשבון Google יוצר משתמש חדש ב-link הבא.
  - כל המכשירים מנותקים (`user_id = NULL`).
  - `user_clubs`, `user_brands` ו-`user_prefs` של המשתמש נמחקים.
  - כל ה-hooks שנרשמו ב-`register_deletion_hook(fn(session, user_id))` רצים.
- מחיקה חוזרת של משתמש שכבר נמחק לא אמורה לקרות, כי ה-token שלו כבר לא מזוהה.
- **מחיקה סופית:** `purge_deleted(session, now)` מוחקת שורות `users` עם `deleted_at` של יותר מ-30 יום, אחרי שה-hooks של מחיקה סופית (`register_purge_hook`) רצו. היא idempotent ובטוחה להרצה חוזרת.
- **worker:**
  - `app/worker/main.py` מריץ את `purge_deleted` פעם ביום, עם APScheduler, כפי שקובע architecture.md.
  - קוד אחד ל-API ול-worker.
  - שירות `worker` נוסף ל-compose המקומי.
- `DELETE /v1/me` זמין רק ל-`Subject("user")`. אורח מקבל 403 `account_required`. אין גוף לבקשה, והתשובה היא 204.
- **באפליקציה:**
  - השורה מוצגת רק למשתמש מחובר, בצבע שגיאה (מה-mockup).
  - לחיצה פותחת אישור, עם הסבר מה נמחק ומה נשאר.
  - אחרי 204: האפליקציה מנסה למחוק את המשתמש ב-Firebase (`deleteUser`). אם Firebase דורש התחברות טרייה, מתבצעת התחברות מחדש עם Google ואז מחיקה. כשל במחיקה ב-Firebase לא מבטל את המחיקה אצלנו.
  - אחר כך `signOut`: ה-session והשם הפרטי נמחקים מהמכשיר. האפליקציה ממשיכה כאורח, עם הודעה שהחשבון נמחק.
- AD-2: identity לא נוגע בטבלאות של מודולים אחרים. AD-13 בכל התגובות. מחרוזות ב-`he.json`.

**Never:**
- אין Firebase Admin SDK, ואין מפתח service account.
- אין מחיקה של תצפיות מחיר: הן נשארות, בלי שיוך (דרך hook ב-Epic 6).
- אין "התנתקות" ואין שורות אחרות בפרופיל.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| מחיקה | `DELETE /v1/me` עם ID token של משתמש מקושר | 204. `deleted_at` מוגדר, `firebase_uid` לא מזהה, המכשירים מנותקים, והמועדונים, המותגים והטווח שלו נמחקים. ה-hooks רצים | כשל: rollback מלא |
| אורח | device token | 403 `account_required`, בלי שינוי | AD-13 |
| בלי token | — | 401 `auth_required` | AD-13 |
| token אחרי מחיקה | אותו ID token | 401 `not_linked`, כי ה-uid לא קיים יותר | — |
| הרשמה מחדש | link עם אותו Google ומכשיר | 201, משתמש חדש. המכשיר מקושר אליו | — |
| מכשיר אחרי מחיקה | device token של המכשיר | עובד כאורח | — |
| בידוד | שני משתמשים | הנתונים של השני לא נפגעים | — |
| מחיקה סופית | משתמש שנמחק לפני 31 יום, ואחר לפני 29 | רק הראשון נמחק. ה-purge hooks רצים לו בלבד | כשל ב-hook: rollback לאותו משתמש, והשאר ממשיכים |
| מחיקה סופית חוזרת | הרצה שנייה | אין שינוי | — |
| worker | הפעלה | `purge_deleted` מתוזמנת פעם ביום | — |
| אפליקציה: אורח | פרופיל בלי session | אין שורת "מחיקת חשבון" | — |
| אפליקציה: ביטול | "ביטול" באישור | אין בקשה ואין שינוי | — |
| אפליקציה: מחיקה | אישור, ו-204 | `deleteUser`, ואז `signOut`, הודעה "החשבון נמחק", והשורה נעלמת | — |
| אפליקציה: Firebase דורש התחברות טרייה | `auth/requires-recent-login` | התחברות מחדש עם Google, ואז `deleteUser` | כשל או ביטול: ממשיכים ל-`signOut`, בלי הודעת שגיאה |
| אפליקציה: השרת נכשל | שגיאה, timeout או רשת | הודעה "לא הצלחנו למחוק את החשבון. נסו שוב", ונשארים מחוברים | — |
| אפליקציה: לחיצה כפולה | אישור פעמיים | בקשה אחת | — |

</intent-contract>

## Code Map

- `backend/app/modules/identity/service.py` -- `link()`, `_TRANSFER_HOOKS` ו-`register_transfer_hook`. כאן נוספים `delete_account`, `register_deletion_hook`, `register_purge_hook` ו-`purge_deleted`.
- `backend/app/modules/identity/repository.py` -- הפונקציות של `user_clubs`, `user_brands` ו-`user_prefs`, וגם `lock_device`. כאן נוספות פונקציות המחיקה.
- `backend/app/modules/identity/routes.py` -- `/me`, ו-`_subject_uuid`.
- `backend/app/core/auth.py` -- `_user_subject`: משתמש עם `deleted_at` מקבל `invalid_token`, ומשתמש שאינו קיים מקבל `not_linked`.
- `backend/tests/integration/test_link.py`, `test_prefs.py` -- `FakeVerifier`, `_id_token` ו-fixtures.
- `deploy/docker-compose.yml`, `backend/Dockerfile` -- השירות `api`. שירות `worker` משתמש באותו image, עם פקודה אחרת.
- `mobile/src/identity/session.ts` -- `signOut`, `nativeSignOut`, `loadNative`, `signInWithGoogle` (ומה שמשמש להתחברות מחדש).
- `mobile/app/(tabs)/profile.tsx` -- השורות של הפרופיל. `docs/planning-artifacts/ux-designs/ux-CartWise-2026-10-26/mockups/screens-5-spend-profile.html:55` -- שורת "מחיקת חשבון", בצבע שגיאה.

## Tasks & Acceptance

**Execution:**
- `backend/pyproject.toml`, `backend/uv.lock` -- `apscheduler`, דרך `uv add`. בשגיאת תעודה עוצרים ומדווחים לפי CLAUDE.md.
- `backend/app/modules/identity/{repository,service,routes,schemas}.py` -- `delete_account`, hooks, `purge_deleted`, ו-`DELETE /me`.
- `backend/app/worker/{__init__,main}.py`, `backend/app/worker/jobs/purge_deleted.py` -- worker עם APScheduler: job יומי, וסשן משלו לכל ריצה.
- `deploy/docker-compose.yml`, `deploy/README.md` -- שירות `worker`, ואיך מריצים אותו.
- `backend/tests/integration/test_delete_account.py` -- כל שורות השרת במטריצה, כולל rollback, hooks והרשמה מחדש. `backend/tests/unit/test_worker.py` -- שה-job מתוזמן פעם ביום.
- `mobile/openapi.json`, `mobile/src/api/schema.ts` -- `npm run gen:api`.
- `mobile/src/identity/session.ts` -- `deleteAccount()`: `DELETE`, ואז Firebase והתחברות מחדש לפי הצורך, ואז `signOut`. מחזיר `{status: 'deleted'}` או `{status: 'failed'}`.
- `mobile/app/(tabs)/profile.tsx` -- קטע "חשבון ופרטיות" עם השורה, רק למשתמש מחובר, אישור ב-`Alert` או במודל, והודעות.
- `mobile/src/i18n/he.json` -- כל המחרוזות.
- `mobile/__tests__/{delete-account,profile}.test.tsx` -- שורות האפליקציה במטריצה, עם mocks לספריות של Firebase.

**Acceptance Criteria:**
- Given משתמש מחובר, when הוא מוחק את החשבון ומאשר, then הוא מנותק, והנתונים שלו ב-identity נמחקים מיד.
- Given משתמש שנמחק לפני יותר מ-30 יום, when ה-job היומי רץ, then השורה שלו נמחקת, וה-purge hooks רצים.
- Given hook רשום של מודול אחר, when משתמש נמחק, then ה-hook רץ באותה טרנזקציה. זה מה ש-Epics 2, 6 ו-9 ישתמשו בו.
- Given משתמש שנמחק, when הוא נרשם שוב עם אותו Google, then נוצר משתמש חדש וריק.

## Spec Change Log

## Review Triage Log

### 2026-11-03 — Review pass
- verdicts: 31 findings — high 0, medium 10, low 17, false 3, maybe-false 1
- findings:
  - Verification Gap:
    - `medium` `patch` אין בדיקה של link מול מחיקה במקביל — `test_concurrent_link_and_delete_leave_no_device_linked`. הסרת ה-FOR SHARE מכשילה אותה.
    - `low` `defer` אין בדיקה לשתי ריצות purge במקביל — אין עדיין purge hooks. רשום ב-deferred.
  - Intent Alignment:
    - `maybe-false` `defer` רשימות, הוצאות ותצפיות לא נמחקות בפועל — המודולים לא קיימים. כבר ב-deferred.
    - `low` `patch` שורה נמחקת עד 31 יום, מעבר ל"תוך 30" — `PURGE_AFTER` הוא 29 יום.
    - `medium` `defer` חשבון Firebase עם המייל יכול להישאר — התיקון דורש Admin SDK, שהמפרט מוציא. נדרשת החלטה של המשתמשת. רשום ב-deferred.
    - `false` `reject` הטקסט "תוך 30 יום" סותר מחיקה מיידית ב-hooks — מחיקה מיידית מקיימת "תוך 30 יום".
  - Blind Hunter:
    - `false` `reject` קבצים מיוצרים ו-lock לא ב-patch — במכוון. CI בודק אותם.
    - `medium` `patch` `PUT` מקביל למחיקה משאיר שורות יתומות — `_lock_live_subject` ב-`set_clubs`, `set_brands` ו-`set_prefs`, ומחיקה חוזרת ב-purge.
    - `medium` `patch` הנעילה ב-`link()` לא נבדקת — אותו תיקון כמו ב-Verification Gap.
    - `medium` `patch` אפליקציה תקועה כשהמחיקה הצליחה והתשובה אבדה — `not_linked` ב-DELETE נחשב `deleted`.
    - `false` `reject` טקסט האישור סותר את ה-hooks — אותו נימוק.
    - `low` `reject` ה-worker עולה לפני המיגרציות — compose לפיתוח בלבד, וה-job הראשון רץ ב-03:00.
    - `low` `patch` אין `restart` ואין טיפול ב-SIGTERM — `restart: unless-stopped` ו-`init: true`.
    - `low` `patch` כשל קבוע ב-purge hook שקט — הלוג מדווח גם `failed`.
    - `medium` `defer` חשבון Firebase נשאר — אותו נימוק.
    - `low` `patch` הודעת "החשבון נמחק" לא נעלמת — מתאפסת כשיש session.
    - `low` `reject` `BaseException` מול `Exception` — אין נזק נצפה.
    - `low` `reject` שעון ה-DB מול שעון Python — אותו שרת, וסטייה של שניות לא משנה בסף של ימים.
    - `low` `reject` תיעוד חלקי של שגיאות ב-OpenAPI — דפוס קיים, שכבר רשום ב-deferred של Story 1.5.
    - `low` `reject` אין אינדקס ל-`deleted_at`, והרשימה לא מוגבלת — מעט משתמשים נמחקים.
    - `low` `reject` `purge_deleted.run` עם ברירות המחדל לא נבדק — הוא נבדק עם session משלו, וההרצה הידנית מתועדת.
  - Edge Case Hunter:
    - `medium` `patch` `PUT` מחזיר שורות אחרי מחיקה — אותו תיקון.
    - `medium` `patch` purge לא מנקה שורות של identity — מחיקה חוזרת לפני `delete_user`.
    - `medium` `patch` `not_linked` אחרי מחיקה שהצליחה — אותו תיקון.
    - `low` `patch` שתי מחיקות במקביל — `delete_account` מחזיר 204 כשהמשתמש כבר נמחק.
    - `low` `reject` link בין ה-select לנעילה מחזיר 401 במקום משתמש חדש — חלון צר, וניסיון נוסף מצליח.
    - `low` `patch` `getAuth()` מחוץ ל-try — נתפס, וממשיכים ל-`signOut`.
    - `low` `patch` דגל busy לא מתאפס כש-`deleteAccount` נכשל — `finally`.
    - `low` `patch` הודעה ישנה אחרי התחברות — אותו תיקון.
    - `low` `reject` רשימה לא מוגבלת ב-purge — אותו נימוק.
    - `medium` `patch` (claim) "נמחק מיד" לא נכון עם `PUT` מקביל — אותו תיקון.

## Design Notes

- **למה `deleteUser` מהאפליקציה:** Firebase שומר את המייל של החשבון. בלי Admin SDK, הדרך היחידה למחוק אותו היא מהלקוח. זה חינמי, ולא דורש מפתח בשרת.
- **למה הנתונים של identity נמחקים מיד:** הם קטנים ואישיים. 30 הימים קיימים עבור נתונים גדולים של מודולים אחרים, ובשביל גיבויים.

## Verification

**Commands:**
- `cd backend && uv sync --locked && uv run ruff check . && uv run ruff format --check . && uv run mypy app && CARTWISE_REQUIRE_DOCKER=1 uv run pytest -q` -- expected: הכול עובר
- `cd mobile && npm run gen:api && npm run lint && npm run typecheck && npm test -- --ci` -- expected: עובר
- `cd mobile && npx expo export --platform android --output-dir <tmp>` -- expected: נבנה. אחר כך מוחקים את התיקייה.

## Auto Run Result

Status: done

**סיכום:** משתמש רשום יכול למחוק את החשבון מהפרופיל, אחרי אישור. השרת מוחק מיד את הנתונים של identity, מנתק את המכשירים, ומשחרר את חשבון ה-Google להרשמה חדשה. worker מוחק את השורה סופית תוך 30 יום. האפליקציה מוחקת גם את המשתמש ב-Firebase, ומתנתקת.

**קבצים:**
- `backend/app/modules/identity/{repository,service,routes}.py` -- `delete_account`, hooks של מחיקה ושל מחיקה סופית, `purge_deleted`, `DELETE /v1/me`, ונעילת המשתמש בכתיבות וב-link.
- `backend/app/worker/` -- APScheduler עם job יומי.
- `backend/pyproject.toml`, `backend/uv.lock` -- `apscheduler<4`.
- `deploy/docker-compose.yml`, `deploy/README.md` -- שירות `worker`.
- `backend/tests/integration/test_delete_account.py`, `backend/tests/unit/test_worker.py` -- המטריצה בצד השרת ומקביליות.
- `mobile/src/identity/session.ts` -- `deleteAccount`.
- `mobile/app/(tabs)/profile.tsx`, `mobile/src/i18n/he.json` -- "חשבון ופרטיות" ו"מחיקת חשבון".
- `mobile/openapi.json`, `mobile/src/api/schema.ts` -- לקוח מיוצר.
- `mobile/__tests__/{delete-account,profile}.test.tsx` -- המטריצה בצד האפליקציה.

**ממצאי הסקירה:** 31 ממצאים. התיקונים כיסו 16 שורות: 9 medium ו-7 low. ה-medium מתחלקים לשלוש קבוצות: כתיבה מקבילה למחיקה, בדיקת המקביליות של link, ומחיקה שהצליחה בלי תשובה. 4 שורות נדחו ל-deferred, ואחת מהן היא medium שדורש החלטה (Firebase). 11 נדחו, והנימוק של כל אחת רשום ב-Review Triage Log.

**המלצה לסקירת המשך:** `true`. תוקנו שלוש קבוצות medium בנעילות ובזרימת המחיקה. הסיכון שלא אומת: מחיקה מול Firebase אמיתי, כולל התחברות מחדש.

**אימות:**
- backend: ruff, format ו-mypy עברו. `CARTWISE_REQUIRE_DOCKER=1 pytest`: 438 עברו.
- mobile: `gen:api`, lint ו-typecheck עברו, ו-388 בדיקות עברו בשתי ריצות.
- `expo export` ל-Android עבר, ו-`docker compose config` עבר.
- gitleaks על הקבצים שהשתנו: `no leaks found`.

**סיכונים שנשארו:**
- חשבון Firebase עם המייל יכול להישאר אם המחיקה בצד הלקוח נכשלת.
- ה-image של ה-worker לא נבנה בפועל, וה-worker רץ רק ב-compose המקומי.
- המחיקה של רשימות, הוצאות ותצפיות תלויה ב-hooks שעוד לא קיימים.
