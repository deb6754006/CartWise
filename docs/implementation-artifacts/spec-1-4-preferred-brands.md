---
title: 'Story 1.4: הגדרת מותגים רצויים'
type: 'feature'
created: '2026-11-02'
status: 'done'
baseline_revision: '2876e9c08cafce95fef8f08c018d939b5ab3ae96'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/docs/implementation-artifacts/epic-1-context.md'
  - '{project-root}/docs/implementation-artifacts/spec-1-3-clubs.md'
  - '{project-root}/docs/planning-artifacts/architecture/architecture-CartWise-2026-10-26/ARCHITECTURE-SPINE.md'
  - '{project-root}/CLAUDE.md'
warnings: ['oversized']
deferred:
  - summary: >-
      AC2 ו-AC3 של ה-Story (רק מותגים רצויים נבחרים להשוואה, ושינוי משפיע רק על השוואות חדשות) לא נבדקים מקצה לקצה.
    evidence: |-
      ההשוואה נבנית ב-Epic 5, ואילוץ המותג של פריט ב-Story 2.4. כאן נחשפת רק `identity.service.brand_ids_for_subject`. כדי להכריע: בדיקות ב-Story 5.2 וב-Story 2.4.
    severity: medium (unverified)
  - summary: >-
      אין עדיין מותגים אמיתיים ב-production, ולכן החיפוש שם לא מוצא כלום.
    evidence: |-
      המותגים מגיעים מהקבצים הרשמיים (Epic 3). כדי להכריע: ליצור שורות `brands` בקליטה, דרך `catalog.service.ensure_brand`.
    severity: medium (unverified)
  - summary: >-
      `normalize_he` לא מאחדת עדיין כתיב מלא וחסר, ולא מפרקת קיצורים (NFR-21).
    evidence: |-
      המילון שייך לחיפוש המוצרים ולהתאמה (Story 2.x ו-Epic 7). כדי להכריע: להרחיב את `normalize_he`, ולחשב מחדש את `name_norm` במיגרציית נתונים.
    location: >-
      backend/app/modules/catalog/service.py
    severity: medium (unverified)
  - summary: >-
      מחיקת חשבון צריכה למחוק גם את שורות `user_brands` של המשתמש.
    evidence: |-
      ל-`subject_id` אין FK, כמו ב-`user_clubs`. כדי להכריע: לטפל בזה ב-Story 1.7.
    severity: low (unverified)
  - summary: >-
      אף Story ב-Epic 3 לא דורש ליצור שורות `brands`, ול-`ensure_brand` אין קורא ב-production.
    evidence: |-
      הארכיטקטורה קובעת שהמותגים מגיעים מהקבצים הרשמיים, אבל ב-Stories 3.2 עד 3.6 אין AC על כך. כדי להכריע: לכלול יצירת מותגים ב-spec של הקליטה ב-Epic 3.
    location: >-
      docs/planning-artifacts/prds/prd-CartWise-2026-10-26/epics.md
    severity: medium (unverified)
  - summary: >-
      ל-AC3 ("שינוי משפיע רק על השוואות חדשות") אין AC מקביל ב-Story 5.2 או ב-Story 2.4.
    evidence: |-
      הניסוח מופיע רק ב-Story 1.4 (`epics.md:106`), ובארכיטקטורה יש רק שמירה של snapshot של ההשוואה. כדי להכריע: לבדוק ב-Epic 5 שתוצאה שמורה לא משתנה אחרי שינוי ברשימת המותגים.
    location: >-
      docs/planning-artifacts/prds/prd-CartWise-2026-10-26/epics.md:106
    severity: medium (unverified)
  - summary: >-
      שמות שנבדלים רק בסוג הגרש נשמרים כמותגים נפרדים עם אותו `name_norm`.
    evidence: |-
      `ensure_brand` מונע כפילויות לפי `name` בלבד. לא ברור אם זה קורה בנתונים אמיתיים. כדי להכריע: לבדוק את שדה המותג בקבצים ב-Story 3.1, ולהחליט אם `name_norm` צריך להיות ייחודי לפני שהקליטה נשענת על `ensure_brand`.
    location: >-
      backend/app/modules/catalog/service.py
    severity: medium (unverified)
  - summary: >-
      לא נבדק במכשיר שהקשה ראשונה על תוצאה מוסיפה אותה כשהמקלדת פתוחה.
    evidence: |-
      `keyboardShouldPersistTaps="handled"` ב-`mobile/app/brands.tsx` לא נבדק, ו-`fireEvent.press` לא מעורב במקלדת. כדי להכריע: בדיקה ידנית במכשיר.
    location: >-
      mobile/app/brands.tsx
    severity: low
---

<intent-contract>

## Intent

**Problem:** משתמש שקונה רק מותגים מסוימים, למשל בגלל כשרות, לא יכול להגדיר אותם (FR-4). בלי הרשימה הזו, האילוץ "אחד מהמותגים הרצויים" שייבנה בהמשך לא יכול לעבוד.

**Approach:** מוסיפים `brands` ל-catalog ו-`user_brands` ל-identity, עם `GET /v1/brands/search?q=` ו-`GET/PUT /v1/me/brands`. באפליקציה נבנה SCR-BRANDS, שנפתח מהפרופיל: חיפוש והוספה, ותגיות עם הסרה. לוגיקת השמירה של המועדונים הופכת למשותפת.

## Boundaries & Constraints

**Always:**
- כמו במועדונים (Story 1.3): הסימונים שייכים ל-subject, והמסך זמין גם לאורח בלי הרשמה. `PUT` מחליף את כל הקבוצה, ומזהה לא מוכר דוחה את כל הבקשה. בכל link שבו המכשיר שייך לאותו משתמש, המותגים עוברים כאיחוד באותה טרנזקציה, עם נעילה לכל subject כמו ב-`user_clubs`.
- AD-2: identity משתמש בנתוני catalog רק דרך `catalog.service`. AD-13 בכל התגובות, `require_subject` בכל ה-endpoints, ולקוח מיוצר מה-OpenAPI.
- `brands.name` נשמר ב-NFC. `brands.name_norm` מחושב רק דרך `catalog.service.normalize_he()`, ואותה פונקציה מנרמלת את מחרוזת החיפוש.
- `normalize_he` מסירה ניקוד, גרש, גרשיים ומרכאות, מאחדת רווחים ואותיות לטיניות קטנות, ומחזירה NFC. היא הנקודה היחידה שתורחב בהמשך.
- התוכן של מחרוזת החיפוש לא נכנס ללוג.
- מחרוזות ב-`he.json`, וטוקנים מ-`tokens.ts`. כל פעולה נגישה: שדה החיפוש, כל תוצאה וכל הסרה מקבלים שם.

**Never:**
- אין שמות של מותגים אמיתיים בקוד, במיגרציות או ב-seed. בפיתוח יש רק "מותג א׳", "מותג ב׳" ו-"מותג ג׳". המיגרציה לא מכניסה נתונים.
- לא בונים אילוץ מותג לפריט (Story 2.4), השוואה (Epic 5), Onboarding (Story 1.6) ומילון כתיב.
- אין הגבלת קצב (Story 10.3).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| חיפוש | `GET /v1/brands/search?q=מות` | 200, רשימה של `id`, `name`, לכל היותר 20. התאמה לפי תת-מחרוזת של `name_norm`, כשתוצאה שמתחילה בחיפוש קודמת, ואז לפי שם | — |
| חיפוש עם ניקוד או גרש | `q` עם ניקוד, גרשיים או רווחים מיותרים | אותן תוצאות כמו בלעדיהם | — |
| תווים מיוחדים | `q=%_\` בתוך מחרוזת | נחשבים לתווים רגילים, ולא wildcard | — |
| חיפוש קצר | פחות מ-2 תווים אחרי נרמול | 200, רשימה ריקה | — |
| חיפוש ארוך | `q` מעל 100 תווים, או בלי `q` | 422 בפורמט AD-13 | AD-13 |
| בלי token | כל ה-endpoints החדשים | 401 `auth_required` | AD-13 |
| קריאה | `GET /v1/me/brands`, אין סימונים | 200 `{"brands": []}` | — |
| שמירה | `PUT /v1/me/brands` `{"brand_ids": [a, b]}` | 200 `{"brands": [{id, name}, ...]}`, ממוין לפי שם. `GET` מחזיר אותו דבר | — |
| כפילות וניקוי | `[a, a]`, או `[]` | נשמר פעם אחת, או שהכל נמחק | — |
| מזהה לא מוכר | `[a, zzz]` | 422 `unknown_brand`, והקודמים נשארים | AD-13, הודעה בעברית |
| גוף לא תקין | שדה נוסף, לא UUID, או מעל 200 מזהים | 422, בלי שמירה | AD-13 |
| בידוד | שני subjects | כל אחד רואה ומשנה רק את שלו | — |
| link | למכשיר `a, b`, למשתמש `b, c` | למשתמש `a, b, c`, למכשיר כלום. גם ב-link חוזר. כשלון ב-link עושה rollback | rollback |
| מכשיר של משתמש אחר | link מחזיר 409 | אין העברה | rollback |
| אפליקציה: אין מותגים | אין סימונים | "לא בחרתם מותגים. ההשוואה תכלול כל מותג" | — |
| אפליקציה: חיפוש | הקלדה של 2 תווים ומעלה | בקשה אחת אחרי 300ms בלי הקלדה. מותג שכבר נבחר לא מוצג בתוצאות | — |
| אפליקציה: חיפוש קצר | פחות מ-2 תווים | אין בקשה ואין תוצאות | — |
| אפליקציה: תשובה ישנה | תשובה לחיפוש קודם מגיעה אחרי תשובה חדשה | התשובה הישנה לא מוצגת | — |
| אפליקציה: אין תוצאות | תשובה ריקה | "לא מצאנו מותג בשם הזה" | — |
| אפליקציה: חיפוש נכשל | שגיאה או timeout | "לא הצלחנו לחפש. נסו שוב". המותגים שנבחרו לא משתנים | — |
| אפליקציה: הוספה | לחיצה על תוצאה | התגית מופיעה מיד, ו-`PUT` נשלח עם הקבוצה המלאה. השדה מתרוקן | — |
| אפליקציה: הסרה | לחיצה על ✕ בתגית | התגית נעלמת מיד, ו-`PUT` נשלח | — |
| אפליקציה: שינויים מהירים | כמה פעולות בזמן שבקשה רצה | לכל היותר בקשה אחת רצה. בסופה נשלח המצב האחרון | — |
| אפליקציה: שמירה נכשלה | `PUT` נכשל | חזרה למצב האחרון שנשמר, ו-"לא הצלחנו לשמור. נסו שוב" | — |
| אפליקציה: טעינה נכשלה | שגיאה או timeout | הודעה וכפתור "נסו שוב", בלי שדה חיפוש | — |

</intent-contract>

## Code Map

- `backend/app/modules/catalog/{models,repository,service,routes,schemas}.py` -- מ-Story 1.3: `Chain`, `Club`, `existing_club_ids`, `ensure_chain_with_club`. אותה תבנית למותגים. ל-router אין prefix.
- `backend/app/modules/identity/repository.py` -- `_lock_subject_clubs`, `replace_user_clubs`, `move_user_clubs`. הנעילה היא לפי subject. למותגים צריך מפתח נעילה נפרד או נעילה משותפת, בלי deadlock ב-link.
- `backend/app/modules/identity/service.py` -- `link()` קורא ל-`move_user_clubs`. `set_clubs` הוא התבנית ל-`set_brands`.
- `backend/migrations/versions/0004_chains_clubs.py` -- תבנית למיגרציה. `0001_extensions.py` כבר מפעיל את `pg_trgm`.
- `backend/scripts/seed_dev_catalog.py` -- מוסיפים לכאן את המותגים הבדויים.
- `backend/tests/integration/test_clubs.py` -- fixtures, `_set_concurrently` ו-`test_concurrent_put_and_link_do_not_lose_marks`. לשימוש חוזר.
- `mobile/src/profile/useClubs.ts` -- `withTimeout`, `activeSave` ו-`persist`. זו הלוגיקה שעוברת למודול משותף.
- `mobile/app/clubs.tsx`, `mobile/app/(tabs)/profile.tsx` -- תבנית למסך ולשורת הפרופיל, כולל `dangerouslySingular` ו-`useFocusEffect`.
- `docs/planning-artifacts/ux-designs/ux-CartWise-2026-10-26/mockups/screens-5-spend-profile.html:77` -- SCR-BRANDS. `EXPERIENCE.md:165` -- מצב ריק. אם יש סתירה בין ה-mockup ל-EXPERIENCE בטקסט של המצב הריק, EXPERIENCE קובע.

## Tasks & Acceptance

**Execution:**
- `backend/app/modules/catalog/models.py` -- `Brand`: `id`, `name` (unique), `name_norm` (עם אינדקס GIN של `gin_trgm_ops`) -- לפי architecture.md §נתונים, ו-trigram תומך ב-`LIKE` על תת-מחרוזת.
- `backend/app/modules/catalog/{repository,service,schemas,routes}.py` -- `normalize_he`, `search_brands`, `brands_by_ids`, `existing_brand_ids`, `ensure_brand` (idempotent), ו-`GET /brands/search` עם `require_subject`. ה-repository מקבל מחרוזת מנורמלת, ומבצע escape ל-`%`, `_` ו-`\`.
- `backend/app/modules/identity/models.py` -- `UserBrand`: `subject_id`, ו-`brand_id` (FK, `ondelete=CASCADE`, עם אינדקס), ו-PK מורכב.
- `backend/migrations/versions/0005_brands.py` -- `brands`, אינדקס trigram, `user_brands`, ו-downgrade. בלי נתונים.
- `backend/app/modules/identity/{repository,service,schemas,routes}.py` -- `brand_ids_for_subject` (ל-Epics 2 ו-5), `set_brands`, `GET/PUT /me/brands` עם `extra="forbid"` ועד 200 מזהים, והעברה ב-`link`.
- `backend/scripts/seed_dev_catalog.py`, `backend/README.md` -- מותגים בדויים, ועדכון ההסבר.
- `backend/tests/integration/test_brands.py` -- כל שורות המטריצה בצד השרת, סכימה, בדיקת `alembic check`, מקביליות `PUT` מול link, ו-seed. `backend/tests/unit/test_normalize.py` -- `normalize_he`.
- `mobile/src/profile/savedSelection.ts` -- מודול משותף: timeout, שמירה סדרתית של המצב האחרון, המתנה של טעינה לשמירה שרצה, וחזרה למצב השמור. `useClubs.ts` עובר להשתמש בו, בלי שינוי בהתנהגות, וכל הבדיקות הקיימות שלו ממשיכות לעבור בלי שינוי בציפיות.
- `mobile/openapi.json`, `mobile/src/api/schema.ts` -- `npm run gen:api`.
- `mobile/src/profile/useBrands.ts` -- טעינה, הוספה, הסרה וחיפוש עם debounce, ו-guard לתשובה ישנה.
- `mobile/app/brands.tsx` -- SCR-BRANDS: כותרת "מותגים רצויים", חזרה, ההסבר מה-mockup, שדה "חיפוש מותג...", תוצאות, תגיות עם ✕ ומצב ריק.
- `mobile/app/(tabs)/profile.tsx` -- שורה "מותגים רצויים" עם מספר, אחרי שורת המועדונים.
- `mobile/src/i18n/he.json` -- כל המחרוזות.
- `mobile/__tests__/{use-brands,brands-screen}.test.tsx`, ותוספת ל-`profile.test.tsx` -- שורות המטריצה בצד האפליקציה.

**Acceptance Criteria:**
- Given אורח בפרופיל, when הוא פותח "מותגים רצויים", מחפש מותג ומוסיף אותו, then המותג מוצג כתגית, ובלי מסך הרשמה.
- Given שהוספתי מותג, when אני יוצא וחוזר, then הוא עדיין שם, והפרופיל מציג את המספר הנכון.
- Given אורח שבחר מותגים, when הוא נרשם, then המותגים מופיעים בחשבון שלו.
- Given שני מותגים, when נבחר רק אחד, then `brand_ids_for_subject` מחזירה רק אותו. זה מה ש-Epics 2 ו-5 ישתמשו בו.
- Given המסכים של המועדונים, then הם מתנהגים כמו קודם, אחרי המעבר למודול המשותף.

## Spec Change Log

## Review Triage Log

### 2026-11-02 — Review pass
- verdicts: 32 findings — high 0, medium 3, low 25, false 0, maybe-false 4
- findings:
  - Edge Case Hunter:
    - `low` `reject` איחוד ב-link עובר 200 מותגים — נדרשים מאות מותגים שנבחרו ידנית. מדיניות חריגה היא יותר מתיקון ישיר.
    - `low` `reject` אין מגבלת 200 בצד הלקוח — אותו נימוק.
    - `low` `reject` `unknown_brand` תוקע את המסך — קורה רק כשמותג נמחק בזמן שהמסך פתוח, וכניסה מחדש פותרת את זה. כמו ב-Story 1.3.
    - `low` `reject` טקסט קצר אחרי נרמול מציג "לא מצאנו" — ההודעה נכונה בפועל, ונרמול בצד הלקוח יכפיל את הכללים.
    - `low` `reject` החיתוך ל-20 תוצאות מסתיר התאמות — נדרשות 20 התאמות שכולן כבר נבחרו.
    - `medium` `patch` תווים בלתי נראים נשארים ב-`normalize_he` — כל תו `Cf` מוסר, עם בדיקות יחידה וחיפוש.
    - `low` `reject` מירוץ של מחיקת מותג נותן 500 — כמו ב-Story 1.3, וזה חלון של מילישניות.
    - `low` `reject` כשל שמירה אחרי יציאה מהמסך — כמו ב-Story 1.3. הפרופיל מציג מספר נכון.
  - Intent Alignment:
    - `maybe-false` `defer` AC1 מתקיים רק בפיתוח, ואף Story ב-Epic 3 לא יוצר `brands` — רשום ב-deferred.
    - `maybe-false` `defer` AC2 נבדק דרך `brand_ids_for_subject` בלבד — ההשוואה ב-Epic 5. כבר ב-deferred.
    - `maybe-false` `defer` ל-AC3 אין AC מקביל בהמשך — רשום ב-deferred.
    - `low` `reject` הטקסטים במסך מבטיחים תוצאה שעדיין לא קיימת — הניסוח מגיע ממסמכי ה-UX, ועדיין אין השוואה להשתמש בה.
    - `low` `reject` אין בדיקת אפליקציה להעברת מותגים בהרשמה — ההעברה נעשית בשרת ונבדקת שם.
    - `low` `reject` אין בדיקה שחוצה את הגבול בין האפליקציה לשרת — כמו ב-Story 1.3. CI בודק את הלקוח המיוצר.
  - Blind Hunter:
    - `low` `reject` איחוד מעל 200 — אותו ממצא כמו ב-Edge Case Hunter.
    - `low` `reject` אין מגבלה בצד הלקוח — אותו ממצא.
    - `low` `reject` `unknown_brand` — אותו ממצא.
    - `low` `reject` מירוץ שנותן 500 — אותו ממצא.
    - `medium` `patch` תווי כיוון ותווים בלתי נראים — אותו תיקון כמו ב-Edge Case Hunter.
    - `medium` `patch` מקף, מקאף ורווח לא מאוחדים — כולם הופכים לרווח ב-`normalize_he`, עם בדיקות.
    - `maybe-false` `defer` אין ייחודיות לפי `name_norm` — תלוי בנתונים אמיתיים. כדי להכריע: Story 3.1. רשום ב-deferred.
    - `low` `reject` הגדרה שונה של "חיפוש קצר" — אותו ממצא כמו ב-Edge Case Hunter.
    - `low` `patch` אזור המגע של ✕ קטן מ-48 ב-Android — ה-✕ עכשיו 48×48 בפועל, בלי `hitSlop`.
    - `low` `patch` אין משוב בזמן חיפוש — מוצג "מחפשים...". כפתור ניסיון חוזר לא נוסף: שינוי הטקסט מספיק.
    - `low` `reject` תוצאות שנבחרו מסתירות אחרות — אותו ממצא כמו ב-Edge Case Hunter.
    - `low` `reject` כשל שקט אחרי יציאה — אותו ממצא.
    - `low` `reject` סדר התגיות משתנה בכניסה הבאה — קוסמטי. תגית חדשה בסוף גם מראה מה נוסף.
    - `low` `reject` אינדקס trigram לא עוזר ב-2 תווים — טבלת המותגים קטנה, וזו סריקה זולה.
  - Verification Gap:
    - `low` `patch` רק 8 מתוך 14 הגרשיים נבדקו — `test_normalize_he_removes_every_quote`.
    - `low` `patch` `maxLength` של שדה החיפוש לא נבדק — נוספה בדיקה.
    - `low` `defer` הקשה ראשונה עם מקלדת פתוחה לא נבדקת — דורש מכשיר. רשום ב-deferred.
    - `low` `reject` (other) "חיפוש קצר" — אותו ממצא כמו ב-Edge Case Hunter.

## Design Notes

- **למה לא לשמור מזהים בלבד בתגובה:** במועדונים האפליקציה מקבלת את כל הרשימה. במותגים אין רשימה מלאה, ולכן `GET/PUT /me/brands` מחזירים גם שם, בשביל התגיות.
- **מותגים ב-production:** עד Epic 3 אין מותגים, והחיפוש מחזיר "לא מצאנו". בלי משתמשים בשלב הזה, זה לא פוגע באיש.
- **`normalize_he` חלקית:** הפונקציה הזו מכסה עכשיו רק את מה שמותגים צריכים בלי מילון. כל הרחבה בהמשך תיעשה רק בה.

## Verification

**Commands:**
- `cd backend && uv sync --locked && uv run ruff check . && uv run ruff format --check . && uv run mypy app && CARTWISE_REQUIRE_DOCKER=1 uv run pytest -q` -- expected: הכול עובר
- `cd mobile && npm run gen:api && npm run lint && npm run typecheck && npm test -- --ci` -- expected: עובר
- `cd mobile && npx expo export --platform android --output-dir <tmp>` -- expected: נבנה. אחר כך מוחקים את התיקייה.

## Auto Run Result

Status: done

**סיכום:** אפשר לחפש מותגים, להוסיף ולהסיר אותם במסך "מותגים רצויים", שנפתח מהפרופיל, גם כאורח. הבחירה נשמרת בשרת ועוברת לחשבון בהרשמה. לוגיקת השמירה של המועדונים הפכה למשותפת, בלי שינוי בהתנהגות.

**קבצים:**
- `backend/app/modules/catalog/*` -- `Brand`, `normalize_he`, `search_brands`, `ensure_brand` ו-`GET /v1/brands/search`.
- `backend/app/modules/identity/*` -- `UserBrand`, `GET/PUT /v1/me/brands`, העברה ב-`link`, ו-`brand_ids_for_subject` בשביל Epics 2 ו-5.
- `backend/migrations/versions/0005_brands.py` -- `brands`, אינדקס trigram ו-`user_brands`, בלי נתונים.
- `backend/scripts/seed_dev_catalog.py`, `backend/README.md` -- מותגים בדויים בלבד.
- `backend/tests/integration/test_brands.py`, `backend/tests/unit/test_normalize.py` -- המטריצה בצד השרת, נרמול, מקביליות וסכימה.
- `mobile/src/profile/savedSelection.ts`, `mobile/src/profile/useClubs.ts` -- המודול המשותף, והמועדונים שעברו אליו.
- `mobile/src/profile/useBrands.ts`, `mobile/app/brands.tsx` -- SCR-BRANDS.
- `mobile/src/components/CardsSkeleton.tsx`, `mobile/src/components/ClubsList.tsx` -- Skeleton משותף.
- `mobile/app/(tabs)/profile.tsx` -- שורת "מותגים רצויים" עם מספר.
- `mobile/src/i18n/he.json`, `mobile/openapi.json`, `mobile/src/api/schema.ts` -- מחרוזות ולקוח מיוצר.
- `mobile/__tests__/{use-brands,brands-screen,profile}.test.tsx` -- המטריצה בצד האפליקציה.

**ממצאי הסקירה:** 32 ממצאים. התיקונים כיסו 7 שורות: 3 medium ו-4 low. ה-medium מתחלקים לשתי קבוצות: תווים בלתי נראים (2 שורות) ומקפים (שורה אחת). 5 שורות נדחו ל-deferred. 20 נדחו, והנימוק של כל אחת רשום ב-Review Triage Log.

**המלצה לסקירת המשך:** `true`. תוקנו שתי קבוצות medium ב-`normalize_he`. הסיכון שלא אומת: התנהגות הנרמול מול שמות מותגים אמיתיים מהקבצים, כולל מקפים, שעדיין לא ראינו.

**אימות:**
- backend: ruff, format ו-mypy עברו. `CARTWISE_REQUIRE_DOCKER=1 pytest`: 319 עברו.
- mobile: `gen:api`, lint ו-typecheck עברו, ו-243 בדיקות עברו.
- `expo export` ל-Android: עבר.
- gitleaks על הקבצים שהשתנו: `no leaks found`.

**סיכונים שנשארו:**
- המסך לא נבדק במכשיר או באמולטור, ובמיוחד RTL בתגיות, הקשה עם מקלדת פתוחה, והמראה של התגיות עם ✕ ברוחב 48.
- אזהרת Jest על worker שלא יצא כראוי הופיעה בריצה אחת מלאה ולא בריצה אחרת. הסיבה לא נמצאה, והבדיקות עברו בכולן.
- ריצת `pytest` של הסוכן נמשכה כ-22 דקות, עם 1,296 שניות ב-`test_health_db_unavailable`. זה לא חזר בריצות שלי (5 שניות לאותה בדיקה), והסיבה לא נבדקה.
- `PUT` שפג לו ה-timeout יכול עדיין להישמר בשרת, כמו במועדונים.
