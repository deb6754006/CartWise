---
title: 'Story 4.4: זיכרון התאמות ברמת הרשת'
type: 'feature'
created: '2026-11-09'
status: 'done'
baseline_revision: 'bc048417748d57564be94b6336641b99f43f04c1'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/docs/implementation-artifacts/epic-4-context.md'
  - '{project-root}/docs/implementation-artifacts/spec-4-3-vote-finalization.md'
warnings: []
deferred:
  - summary: >-
      כינויי final שהזיכרון יוצר לא מסומנים כנגזרים. אם ההתאמה הסופית המקורית תתוקן (disputed או אישור מפעיל למוצר אחר), ההעתקים יישארו על המוצר הישן, וגם ימשיכו להזין את הזיכרון.
    evidence: |-
      ‏final לא משתנה מהצבעות או מהתאמה. כדי להכריע: ב-4.5 (כלי ניהול), כשמפעיל משנה התאמה סופית, לעדכן גם את כל הכינויים ה-final של אותו (chain_id, alias_norm), או לסמן מקור (source) לכינויים נגזרים.
    location: >-
      backend/app/modules/matching/service.py (match, chain memory)
    severity: medium
  - summary: >-
      אין בדיקה לענף המרוץ, שבו upsert_alias מחזיר כינוי שהתיישב בינתיים על ידי טרנזקציה אחרת.
    evidence: |-
      הענף מחזיר את הכינוי השמור. כדי לבדוק אותו צריך שתי טרנזקציות במקביל, וזה לא פרופורציונלי ל-Story הזו. כדי להכריע: בדיקת threads, אם יתגלה באג במרוץ.
    location: >-
      backend/app/modules/matching/service.py (match)
    severity: low
---

<intent-contract>

## Intent

**Problem:** FR-40 דורש שכינוי שיש לו התאמה סופית ברשת יותאם אוטומטית, ולא יוצג לאישור, כשהוא מופיע שוב באותה רשת. היום `match()` מוצא כינוי `final` רק לפי המפתח המלא `(chain_id, alias_norm, barcode)`. לכן אותו טקסט באותה רשת, בלי ברקוד או עם ברקוד אחר (למשל שורת חשבונית בלי ברקוד), לא נמצא, ועובר שוב התאמה לפי טקסט. בנוסף, אין לקוראים סימן אחד שאומר אם צריך לשאול את המשתמש.

**Approach:**
- ב-`match()` נוסף שלב זיכרון ברמת הרשת, לפי `(chain_id, alias_norm)`, בלי קשר לברקוד, לכינויים `final`. השלב רץ אחרי מסלול הברקוד ואחרי הזיכרון לפי המפתח המלא, ולפני מסלול הטקסט.
- `MatchResult` מקבל את המאפיין `needs_confirmation`.

## Boundaries & Constraints

**Always:**
- **סדר ב-`match()`:**
  1. כינוי עם הצבעות, או `final`/`disputed`, לפי המפתח המלא. מוחזר כמו שהוא (4.3).
  2. ברקוד תקין שיש לו מוצר (4.1).
  3. **חדש, זיכרון לפי `(chain_id, alias_norm)`:** כל הכינויים ה-`final` של הרשת עם אותו `alias_norm`, ובכל ברקוד, שה-product_id שלהם לא NULL ולא `merged_into`.
     - **מוצר אחד בדיוק:**
       - הכינוי של המפתח הנוכחי נשמר כ-`final` למוצר הזה, עם confidence=1, דרך `catalog_service.upsert_alias`. אם הוא כבר קיים ולא מיושב, הוא מתעדכן ל-`final`.
       - מוחזר `MatchResult(state="final", path="memory")`.
     - **יותר ממוצר אחד** (הזיכרון לא חד-משמעי): ממשיכים לשלב 4, ונרשם ב-`matching_match` השדה `memory_ambiguous=True`.
  4. מסלול הטקסט (4.2).
- **קלט בלי ברקוד:** הזיכרון לפי רשת חל. **קלט עם ברקוד תקין שיש לו מוצר:** הברקוד גובר, ושלב 3 לא רץ.
- **`MatchResult.needs_confirmation`:** ‏property. ‏True רק כש-state הוא `uncertain` או `new_product_proposal`. ‏`final`, ‏`certain` ו-`disputed` לא מוצגים לאישור. ‏`disputed` מחכה למפעיל (4.5).
- **`match_file_items` (3.6):** משתמש באותו זיכרון. השאילתה `alias_products_by_norm` מחזירה מוצר גם מכינוי `final` עם ברקוד, כשהוא יחיד ל-norm הזה. כך השם של פריט בלי ברקוד, שהיה `final` בגרסה עם ברקוד, יקבל את אותו מוצר. כשיש יותר ממוצר אחד, ההתנהגות נשארת כמו היום: רק כינויים בלי ברקוד.
- **הלוג:** ב-`matching_match`, ‏`path='memory'` גם לזיכרון לפי רשת. נוסף השדה `memory_scope`: ‏`key` או `chain`.
- **אין מיגרציה.**

**Never:**
- לא ליצור זיכרון בין רשתות. כינוי `final` ברשת A לא משפיע על רשת B.
- לא לשנות כינוי עם הצבעות, `final` או `disputed`.
- לא לשנות את הניקוד או את ספי 4.2.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| זיכרון ברשת | כינוי `final` "עגבניות שרי" למוצר X ברשת A, עם ברקוד B1. קלט: אותו טקסט ברשת A בלי ברקוד | ‏`final`, ‏X, ‏path `memory`, ‏needs_confirmation False. נשמר כינוי `final` לברקוד NULL | — |
| רשת אחרת | אותו מצב, וקלט ברשת B | לא מהזיכרון. עובר למסלול הטקסט | — |
| זיכרון לא חד-משמעי | שני כינויים `final` לאותו norm ברשת A, למוצרים X ו-Y | מסלול הטקסט, ו-`memory_ambiguous` בלוג | — |
| ברקוד גובר | כינוי `final` ל-X לטקסט. קלט עם ברקוד תקין של מוצר Z | ‏`certain` ל-Z (מסלול הברקוד) | — |
| ‏certain לא נחשב זיכרון | כינוי `certain` (לא `final`) לטקסט, עם ברקוד אחר | אין זיכרון. עובר למסלול הטקסט | — |
| מוצר ממוזג | כינוי `final` למוצר `merged_into` | לא נלקח | — |
| ‏needs_confirmation | התוצאות של `uncertain`, ‏`new_product_proposal`, ‏`certain`, ‏`final` ו-`disputed` | ‏True, ‏True, ‏False, ‏False, ‏False | — |
| פריט מקובץ | כינוי `final` עם ברקוד לשם N, ופריט פנימי בשם N | אותו מוצר, בלי `match` | — |

</intent-contract>

## Code Map

- `backend/app/modules/matching/service.py` -- `match()`, עם הסדר הנוכחי (votes/settled, ברקוד, טקסט), ‏`MatchResult`, ‏`_log` ו-`match_file_items`. כאן נוסף שלב 3, ו-`needs_confirmation`.
- `backend/app/modules/catalog/{repository,service}.py` -- `alias_by_key`, ‏`upsert_alias`, ‏`alias_products_by_norm` (3.6) ו-`product_statuses`. כאן נוסף `final_products_by_norm(chain_id, alias_norm) -> set[UUID]`, ומעודכן `alias_products_by_norm`.
- `backend/tests/integration/test_matching_text.py`, ‏`test_file_matching.py` -- ה-helpers ליצירת כינויים ומוצרים.

## Tasks & Acceptance

**Execution:**
- `backend/app/modules/catalog/{repository,service}.py` -- `final_products_by_norm`, והעדכון של `alias_products_by_norm`.
- `backend/app/modules/matching/service.py` -- שלב הזיכרון, ‏`needs_confirmation` והלוג.
- `backend/tests/integration/test_match_memory.py` -- כל שורות המטריצה.

**Acceptance Criteria:**
- Given כינוי עם התאמה סופית ברשת א', when אותו כינוי מופיע שוב ברשת א', then הוא מותאם אוטומטית (`final`), ו-`needs_confirmation` הוא False, כלומר הוא לא מוצג לאישור.

## Spec Change Log

## Review Triage Log

### 2026-11-10 — Review pass
- verdicts: 23 findings — high 0, medium 5, low 15, false 3, maybe-false 0
- findings:
  - Verification Gap:
    - `low` `patch` סדר העדיפויות ב-`alias_products_by_norm` לא נבדק — בדיקות (a) ו-(b).
    - `low` `defer` ענף המרוץ אחרי ה-upsert — נרשם ב-deferred.
    - `low` `patch` (Other) ‏memory_scope בענף המרוץ — `chain`.
  - Intent Alignment:
    - `false` `reject` ‏(a) אף אחד לא משתמש ב-`needs_confirmation` — מסך אישור החשבונית שייך ל-Epic 6.
    - `low` `reject` ‏(b) הבדיקות קובעות final ב-UPDATE — בדיקת ה-AC משתמשת ב-approve_match האמיתי.
    - `false` `reject` ‏(c) זיכרון לפי המפתח המלא כבר היה קיים מ-4.3 — נכון. החידוש כאן הוא זיכרון לפי רשת.
    - `medium` `patch` ‏(d) זיכרון גם עם ברקוד שונה ולא מוכר — הזיכרון לפי רשת רץ רק כשאין ברקוד תקין.
    - `medium` `defer` ‏(e) העתקי final לא מתעדכנים כשהמקור מתוקן — נרשם ב-deferred ל-4.5.
    - `low` `reject` ‏(f) זיכרון לא חד-משמעי חוזר למסלול הטקסט — זה מכוון: לא מנחשים.
    - `low` `reject` ‏(g) מסלול הקבצים לא כותב — הוא קורא בלבד, לפי ה-spec. ‏`match()` כותב.
  - Edge Case Hunter:
    - `low` `reject` מוצר מוצע יתום — כבר רשום ב-deferred של 4.2.
    - `medium` `patch` ברקוד בלי מוצר ננעל כ-final — אותו תיקון כמו (d).
    - `low` `reject` מועמדים ישנים אחרי מרוץ — נדיר, ולא משפיע על ההחלטה.
    - `low` `reject` ‏final למוצר proposed — רק כשאדם אישר אותו. אישור המוצר עצמו שייך ל-4.5.
    - `low` `patch` ‏memory_ambiguous לא נרשם בענף אחד — עובר עכשיו בכל return.
  - Blind Hunter:
    - `medium` `patch` זיכרון נועל ברקוד — אותו תיקון.
    - `medium` `defer` כינויים נגזרים בלי סימון מקור — אותו entry.
    - `low` `patch` ‏`alias_products_by_norm` שונה מ-`match()` כשיש הצבעות — `match_file_items` משתמש במוצר של כינוי עם הצבעות.
    - `low` `patch` לוג במרוץ — אותו תיקון.
    - `low` `patch` ארגומנטים לפי מיקום, ו-normalize כפול — keyword-only, וחישוב אחד.
    - `low` `patch` בדיקות חסרות — (c), (d), (e), וברקוד בלי מוצר.
    - `low` `patch` ‏`unmatched` לא מתועד — מתועד.
    - `false` `reject` ‏sprint-status וה-spec לא בתוך ה-diff — מתעדכנים ב-commit. ה-spec הוצא בכוונה.

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy` -- expected: נקי.
- `cd backend && CARTWISE_REQUIRE_DOCKER=1 uv run pytest` -- expected: הכל עובר.

## Auto Run Result

Status: done

**סיכום:**
- **שלב זיכרון חדש ב-`match()` לפי `(chain_id, alias_norm)`:** רץ רק כשאין ברקוד תקין, ולוקח רק כינויים `final` ומוצרים שלא מוזגו. כשיש מוצר אחד בלבד, הכינוי נשמר כ-`final`, וההתאמה לא מוצגת לאישור.
- **`MatchResult.needs_confirmation`:** ‏True רק ל-`uncertain` ול-`new_product_proposal`.
- **`match_file_items`:** משתמש באותו זיכרון, ושומר על כינוי שיש עליו הצבעות.

**קבצים:**
- `backend/app/modules/matching/{service,repository}.py`.
- `backend/app/modules/catalog/{repository,service}.py`.
- `backend/tests/integration/test_match_memory.py`.

**ממצאי הסקירה:** 23 ממצאים:
- **תוקנו:** entry אחד ברמת medium (זיכרון רק בלי ברקוד), ו-8 ברמת low.
- **נדחו ל-deferred:** 2. אחד מהם ברמת medium: עדכון של העתקי final, ב-4.5.
- **נדחו לגמרי:** השאר.

**המלצה לסקירת המשך:** `true`. העתקי final שנגזרו מהזיכרון מחכים ל-4.5, ועד אז הם עלולים להפיץ תיקון שגוי.

**אימות:**
- ruff, format ו-mypy נקיים.
- `CARTWISE_REQUIRE_DOCKER=1 pytest`: 973 עברו.
- gitleaks על הקבצים שהשתנו: `no leaks found`.
