---
title: 'Story 1.5: טווח ברירת מחדל'
type: 'feature'
created: '2026-11-02'
status: 'done'
baseline_revision: 'b9073c3a28b52ca29ae4f3c588e4f7a9ca834b5f'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/docs/implementation-artifacts/epic-1-context.md'
  - '{project-root}/docs/implementation-artifacts/spec-1-4-preferred-brands.md'
  - '{project-root}/docs/planning-artifacts/architecture/architecture-CartWise-2026-10-26/ARCHITECTURE-SPINE.md'
  - '{project-root}/CLAUDE.md'
warnings: ['oversized']
deferred:
  - summary: >-
      שני ה-AC של ה-Story (השוואה חדשה נפתחת מהטווח השמור, ושינוי בהשוואה בודדת לא משנה אותו) לא נבדקים מקצה לקצה.
    evidence: |-
      SHEET-RANGE וההשוואה נבנים ב-Epic 5. כאן נחשפים `identity.service.prefs_for_subject` והרכיב `RangePicker`. כדי להכריע: לבנות ב-Epic 5 את SHEET-RANGE עם המתג "לשמור כברירת מחדל", ולבדוק את שני ה-AC.
    severity: medium (unverified)
  - summary: >-
      `min_coverage_pct` לא נוסף ל-`user_prefs`, והשורה "כיסוי מינימלי" בפרופיל לא נבנתה.
    evidence: |-
      סף הכיסוי שייך ל-FR-20, והספים נטענים מ-`config/thresholds.yaml` שעדיין לא קיים. כדי להכריע: להוסיף את העמודה במיגרציה, ב-Story של Epic 5 שבונה את הסף.
    severity: low (unverified)
  - summary: >-
      מחיקת חשבון צריכה למחוק גם את שורת `user_prefs` של המשתמש.
    evidence: |-
      ל-`subject_id` אין FK, כמו ב-`user_clubs`. כדי להכריע: לטפל בזה ב-Story 1.7.
    severity: low (unverified)
  - summary: >-
      ב-Stories 5.1 עד 5.8 אין AC על פתיחה מהטווח השמור, או על כך ששינוי בהשוואה לא משנה אותו.
    evidence: |-
      Story 5.1 עוסק בסינון לפי טווח, ו-FR-5 לא מוזכר שם. הדרישה מופיעה רק ב-Story 1.5 וב-EXPERIENCE §10.4. כדי להכריע: לכלול את שני ה-AC ב-spec של Epic 5 שבונה את SHEET-RANGE.
    location: >-
      docs/planning-artifacts/prds/prd-CartWise-2026-10-26/epics.md
    severity: medium (unverified)
  - summary: >-
      ה-OpenAPI לא מתאר את השגיאות בפועל: 401 לא מתועד, ו-422 מתועד כ-`HTTPValidationError` ולא בפורמט AD-13.
    evidence: |-
      זה דפוס קיים מ-Epic 0, ולא רק של הנתיב החדש. הלקוח המיוצר מקבל טיפוס שגוי לשגיאות. כדי להכריע: להגדיר `responses` משותף ל-routers.
    location: >-
      backend/app/modules/identity/routes.py
    severity: low
---

<intent-contract>

## Intent

**Problem:** המשתמש לא יכול לשמור טווח ברירת מחדל: אמצעי תחבורה ודקות (FR-5). בלי זה, כל השוואה תדרוש בחירה מחדש.

**Approach:** מוסיפים `user_prefs` למודול identity, עם `GET/PUT /v1/me/prefs`. באפליקציה נבנה מסך "טווח ברירת מחדל" שנפתח מהפרופיל, על בסיס רכיב `RangePicker` בלי ניווט, כדי ש-Onboarding (Story 1.6) ו-SHEET-RANGE (Epic 5) ישתמשו בו.

## Boundaries & Constraints

**Always:**
- הטווח שייך ל-subject, והמסך זמין גם לאורח בלי הרשמה. AD-13 בכל התגובות, `require_subject`, ולקוח מיוצר מה-OpenAPI.
- ערכים מותרים: `default_mode` הוא `walk` או `car`. `default_minutes` הוא 5, 10, 15, 20 או 30 (FR-18, EXPERIENCE §10.4). האילוץ נאכף גם ב-DB.
- כשאין שורה, `GET` מחזיר את ברירות המחדל של המערכת, רכב ו-15 דקות, בלי ליצור שורה.
- ב-link, כשלמשתמש אין טווח שמור, הטווח של המכשיר עובר אליו. כשיש לו, הטווח של החשבון נשאר. בשני המקרים השורה של המכשיר נמחקת, באותה טרנזקציה. זה קורה בכל link שבו המכשיר שייך לאותו משתמש.
- מיקום המשתמש לא נשמר כאן.
- מחרוזות ב-`he.json`, וטוקנים מ-`tokens.ts`. כל אפשרות נגישה, עם שם ומצב נבחר.

**Never:**
- אין תחבורה ציבורית: הכפתור מושבת ומסומן "בקרוב", ולא ניתן לבחור בו. גם השרת דוחה אותה.
- לא בונים SHEET-RANGE, נקודת מוצא, השוואה, סף כיסוי או Onboarding.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| קריאה בלי שורה | `GET /v1/me/prefs` | 200 `{"default_mode": "car", "default_minutes": 15}`, ולא נוצרת שורה | — |
| שמירה | `PUT /v1/me/prefs` `{"default_mode": "walk", "default_minutes": 10}` | 200 עם אותם ערכים. `GET` מחזיר אותם. שמירה חוזרת מעדכנת את אותה שורה | — |
| ערך לא מותר | `transit`, 7 דקות, או שדה חסר | 422, בלי שינוי | AD-13 |
| שדה נוסף | למשל `lat` | 422, בלי שינוי | AD-13 |
| בלי token | `GET` או `PUT` | 401 `auth_required` | AD-13 |
| בידוד | שני subjects | כל אחד רואה ומשנה רק את שלו | — |
| link, למשתמש אין טווח | למכשיר walk/10 | למשתמש walk/10, ולמכשיר אין שורה | כשלון: rollback |
| link, למשתמש יש טווח | למכשיר walk/10, למשתמש car/20 | למשתמש car/20, ולמכשיר אין שורה | — |
| מכשיר של משתמש אחר | link מחזיר 409 | אין העברה | rollback |
| אפליקציה: טעינה | פתיחת המסך | Skeleton | — |
| אפליקציה: טעינה נכשלה | שגיאה או timeout | הודעה וכפתור "נסו שוב", בלי אפשרויות | — |
| אפליקציה: בחירה | לחיצה על אמצעי או דקות | הבחירה מוצגת מיד, ו-`PUT` נשלח עם שני הערכים | — |
| אפליקציה: החלפת אמצעי | הדקות שנבחרו | הדקות נשארות כמו שהן | — |
| אפליקציה: שינויים מהירים | כמה לחיצות בזמן שבקשה רצה | לכל היותר בקשה אחת רצה. בסופה נשלח המצב האחרון | — |
| אפליקציה: שמירה נכשלה | `PUT` נכשל | חזרה למצב האחרון שנשמר, ו-"לא הצלחנו לשמור. נסו שוב" | — |
| אפליקציה: תחבורה ציבורית | לחיצה על 🚌 | שום דבר לא קורה. הכפתור מסומן כמושבת לקוראי מסך | — |
| אפליקציה: פרופיל | חזרה למסך | השורה מציגה את הטווח, למשל "🚶 10 דק׳". אם הטעינה נכשלה, השורה מוצגת בלי ערך | — |

</intent-contract>

## Code Map

- `backend/app/modules/identity/{models,repository,service,schemas,routes}.py` -- `UserBrand`, `move_user_brands` ו-`link()`. אותה תבנית, אבל שורה אחת ל-subject, ו-`insert ... on_conflict`.
- `backend/migrations/versions/0005_brands.py` -- תבנית למיגרציה.
- `backend/tests/integration/test_brands.py` -- fixtures ודוגמאות של link ו-422. לשימוש חוזר.
- `mobile/src/profile/savedSelection.ts` -- `createSelectionSaver`, `useSavedSelection`, `loadAfterSave`. הטווח משתמש בו, כערך עם שני שדות.
- `mobile/src/profile/useBrands.ts`, `mobile/app/brands.tsx`, `mobile/src/components/CardsSkeleton.tsx` -- תבנית ל-hook, למסך ול-Skeleton.
- `mobile/app/(tabs)/profile.tsx` -- `useCountOnFocus` ו-`CountRow`. השורה החדשה מציגה ערך, ולא מספר.
- `docs/planning-artifacts/ux-designs/ux-CartWise-2026-10-26/mockups/screens-1-onboarding-home.html:49` -- SCR-ONB-3: מראה האפשרויות וההסבר. `EXPERIENCE.md:252` -- §10.4.

## Tasks & Acceptance

**Execution:**
- `backend/app/modules/identity/models.py` -- `UserPrefs`: `subject_id` (PK, בלי FK), `default_mode`, `default_minutes`, ו-`CheckConstraint` לשני הערכים.
- `backend/migrations/versions/0006_user_prefs.py` -- הטבלה ו-downgrade.
- `backend/app/modules/identity/{repository,service,schemas,routes}.py` -- `prefs_for_subject` (זו הנקודה ש-Epic 5 יקרא לה), `set_prefs`, `GET/PUT /me/prefs` עם `Literal` ו-`extra="forbid"`, והעברה ב-`link`.
- `backend/tests/integration/test_prefs.py` -- כל שורות המטריצה בצד השרת, סכימה, `alembic check` ו-roundtrip של המיגרציה.
- `mobile/openapi.json`, `mobile/src/api/schema.ts` -- `npm run gen:api`.
- `mobile/src/profile/useRange.ts` -- `loadRange`, טעינה ושמירה דרך `savedSelection`.
- `mobile/src/components/RangePicker.tsx` -- רכיב מבוקר: 🚶 🚗, 🚌 מושבת עם "בקרוב", ודקות. בלי ניווט ובלי קריאות רשת.
- `mobile/app/range.tsx` -- כותרת "טווח ברירת מחדל", חזרה, `RangePicker`, וההסבר "💡 זמן הנסיעה לא משנה את הדירוג. הוא רק קובע אילו חנויות נכנסות להשוואה."
- `mobile/app/(tabs)/profile.tsx` -- שורה "טווח ברירת מחדל" עם הערך, אחרי שורת המותגים, עם `dangerouslySingular`.
- `mobile/src/i18n/he.json` -- כל המחרוזות.
- `mobile/__tests__/{use-range,range-picker,range-screen}.test.tsx`, ותוספת ל-`profile.test.tsx` -- שורות המטריצה בצד האפליקציה.

**Acceptance Criteria:**
- Given אורח בפרופיל, when הוא פותח "טווח ברירת מחדל" ובוחר "הליכה, 10 דקות", then הבחירה נשמרת, והפרופיל מציג אותה, בלי מסך הרשמה.
- Given משתמש ששמר טווח, when `prefs_for_subject` נקראת, then היא מחזירה את הטווח הזה. זה מה ש-Epic 5 ישתמש בו.
- Given משתמש שלא שמר טווח, when `prefs_for_subject` נקראת, then היא מחזירה רכב ו-15 דקות. זה גם מה שמי שידלג ב-Onboarding יקבל.

## Spec Change Log

## Review Triage Log

### 2026-11-02 — Review pass
- verdicts: 22 findings — high 0, medium 3, low 13, false 3, maybe-false 3
- findings:
  - Intent Alignment:
    - `maybe-false` `defer` AC1: הפתיחה מהטווח השמור לא בנויה — ההשוואה ב-Epic 5. כבר ב-deferred.
    - `maybe-false` `defer` AC2: אין שינוי טווח בהשוואה בודדת — ב-Epic 5. כבר ב-deferred.
    - `maybe-false` `defer` ל-AC האלה אין בעלים ב-Stories של Epic 5 — כדי להכריע: לכלול אותם ב-spec של SHEET-RANGE. רשום ב-deferred.
    - `low` `reject` `min_coverage_pct` לא נוסף — החלטה מתועדת ב-deferred, ושייכת ל-FR-20.
    - `false` `reject` `maxWorkers` לא קשור ל-Story — נדרש כדי שהאימות יעבור: בלעדיו, אותן בדיקות נכשלו גם ב-commit הנקי ב-3 מתוך 3 ריצות.
  - Blind Hunter:
    - `low` `reject` `setMode` ו-`setMinutes` פועלים לפני טעינה — ה-UI לא מציג את ה-picker במצבים האלה, ולכן זה לא בר-השגה היום.
    - `low` `reject` `signIn.subtitle` מבטיח שההעדפות יעברו — מתאר נכון את רוב המקרים. בחשבון קיים הטווח נשאר, לפי החלטה במפרט.
    - `medium` `patch` `move_user_prefs` בלי נעילה מפספס `PUT` ראשון — נוסף `_lock_subject_prefs` ב-`upsert_user_prefs` וב-`move_user_prefs`.
    - `medium` `patch` הבדיקה המקבילית לא מכסה את המקרה הזה — נוספה `test_link_waits_for_a_first_put_in_progress`. הסרת הנעילות מכשילה אותה.
    - `low` `patch` `test_the_database_enforces_the_values` עלולה לעבור מסיבה לא נכונה — שמות עמודות, שם ה-constraint, ושורה תקינה.
    - `low` `reject` הערכים המותרים מוכפלים — הם כמעט לא משתנים, והסנכרון יעלה יותר מהתקלה.
    - `low` `reject` כשל שמירה אחרי יציאה מהמסך — כמו ב-Stories 1.3 ו-1.4. הפרופיל מציג את הערך מהשרת.
    - `low` `patch` הודעת כשל הטעינה בלי `accessibilityLiveRegion` — נוסף בשלושת המסכים.
    - `low` `defer` ה-OpenAPI לא מתאר את השגיאות — דפוס קיים. רשום ב-deferred.
    - `false` `reject` `maxWorkers` מאט את הבדיקות — נמדד: 50 שניות, לעומת 88 בלי ההגבלה.
    - `low` `reject` פערים בקלט (`10.0`, גוף שאינו אובייקט, token לא תקין) — ה-token נבדק ב-Story 1.1, וערך מספרי שקול לא מזיק.
    - `low` `patch` קפיצת פריסה בבחירה — ה-padding מפצה על המסגרת.
  - Edge Case Hunter:
    - `medium` `patch` `PUT` ראשון בזמן link — אותו תיקון.
    - `low` `reject` `PUT` שפג לו ה-timeout נשמר בשרת — נדיר, וטעינה מחדש של המסך מתקנת. רשום בסיכונים.
    - `low` `reject` כשל שמירה אחרי יציאה מהמסך — אותו נימוק.
    - `medium` `patch` (claim) ה-docstring לא כיסה את הסדר הזה — אותו תיקון, וה-docstring תוקן.
  - Verification Gap:
    - `false` `reject` (other) `maxWorkers` לא מופיע במפרט — אותו נימוק: נדרש לאימות, והוא נמדד.

## Design Notes

- **ברירת מחדל:** FR-18 קובע הליכה 10 ורכב 15, אבל לא איזה אמצעי קודם. ה-mockups של SCR-ONB-3 ושל SHEET-RANGE מציגים רכב ו-15 כנבחרים, ולכן זו ברירת המחדל.
- **בחשבון קיים הטווח נשאר:** זה ערך יחיד, ואי אפשר לאחד אותו כמו מועדונים. חשבון קיים כבר מייצג בחירה מכוונת.

## Verification

**Commands:**
- `cd backend && uv sync --locked && uv run ruff check . && uv run ruff format --check . && uv run mypy app && CARTWISE_REQUIRE_DOCKER=1 uv run pytest -q` -- expected: הכול עובר
- `cd mobile && npm run gen:api && npm run lint && npm run typecheck && npm test -- --ci` -- expected: עובר
- `cd mobile && npx expo export --platform android --output-dir <tmp>` -- expected: נבנה. אחר כך מוחקים את התיקייה.

## Auto Run Result

Status: done

**סיכום:** אפשר לשמור טווח ברירת מחדל במסך ייעודי שנפתח מהפרופיל, גם כאורח. הפרופיל מציג את הטווח, ו-`prefs_for_subject` מחזירה אותו, או רכב ו-15 דקות כשלא נשמר טווח. הטווח עובר לחשבון בהרשמה, אלא אם לחשבון כבר יש טווח.

**קבצים:**
- `backend/app/modules/identity/*` -- `UserPrefs`, `GET/PUT /v1/me/prefs`, העברה ב-`link`, ו-`prefs_for_subject`.
- `backend/migrations/versions/0006_user_prefs.py` -- הטבלה, עם אילוצי ערכים.
- `backend/tests/integration/test_prefs.py` -- המטריצה בצד השרת, מקביליות, סכימה ומיגרציה.
- `mobile/src/profile/useRange.ts`, `mobile/src/components/RangePicker.tsx`, `mobile/app/range.tsx` -- המסך והרכיב המשותף.
- `mobile/app/(tabs)/profile.tsx` -- שורת הטווח, ושורה כללית שמציגה ערך.
- `mobile/app/brands.tsx`, `mobile/src/components/ClubsList.tsx` -- הכרזה על כשל טעינה לקוראי מסך.
- `mobile/package.json` -- `maxWorkers: "25%"` ל-Jest. לא היה במפרט. נדרש כדי שהאימות יעבור (ראו למטה).
- `mobile/src/i18n/he.json`, `mobile/openapi.json`, `mobile/src/api/schema.ts` -- מחרוזות ולקוח מיוצר.
- `mobile/__tests__/{use-range,range-picker,range-screen,profile,brands-screen,clubs-list}.test.tsx` -- המטריצה בצד האפליקציה.

**ממצאי הסקירה:** 22 ממצאים. התיקונים כיסו 7 שורות: 3 medium ו-4 low. ה-medium הם קבוצה אחת: מירוץ של `PUT` ראשון מול link. 4 שורות נדחו ל-deferred. 11 נדחו, והנימוק של כל אחת רשום ב-Review Triage Log.

**המלצה לסקירת המשך:** `false`. תוקנה קבוצת medium אחת בלבד, והיא מכוסה בבדיקה שנכשלת כשמסירים את הנעילות.

**יציבות הבדיקות:** `npm test` נכשל ב-timeout של 5 שניות, בבדיקה הראשונה של `clubs-screen` ו-`brands-screen`, וגם של `range-screen`. אותן בדיקות נכשלו גם ב-commit הנקי לפני ה-Story, ב-3 מתוך 3 ריצות, ולכן השינוי לא גרם לזה. הסיבה היא עומס: Jest הריץ 15 תהליכים במקביל. אחרי ההגבלה ל-25% מהליבות (4 תהליכים כאן), כל הריצות עברו, בכ-50 שניות במקום 88.

**אימות:**
- backend: ruff, format ו-mypy עברו. `CARTWISE_REQUIRE_DOCKER=1 pytest`: 366 עברו.
- mobile: `gen:api`, lint ו-typecheck עברו, ו-278 בדיקות עברו.
- `expo export` ל-Android: עבר.
- gitleaks על הקבצים שהשתנו: `no leaks found`.

**סיכונים שנשארו:**
- המסך לא נבדק במכשיר או באמולטור, ובמיוחד RTL, והקראה של `radio` ב-TalkBack.
- אזהרת Jest על worker שלא יצא כראוי מופיעה בחלק מהריצות. הסיבה לא נמצאה, והבדיקות עוברות.
- `PUT` שפג לו ה-timeout יכול עדיין להישמר בשרת. במצב הזה לחיצה על הערך שמוצג לא תשלח כלום, עד טעינה מחדש של המסך.
- ב-CI עם מעט ליבות, 25% הוא תהליך אחד, והריצה תהיה איטית יותר.
