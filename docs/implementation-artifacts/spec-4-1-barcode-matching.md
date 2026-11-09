---
title: 'Story 4.1: התאמה לפי ברקוד'
type: 'feature'
created: '2026-11-09'
status: 'done'
baseline_revision: '0166b02b3527d9c8270fbcec7c11625ca0fff5ed'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/docs/implementation-artifacts/epic-4-context.md'
  - '{project-root}/docs/implementation-artifacts/spec-3-4-prices-promotions.md'
warnings: ['oversized']
deferred:
  - summary: >-
      alias_norm נשמר כעותק של normalize_he. כשהנרמול ישתנה (איחוד כתיב וקיצורים, NFR-21), שורות קיימות ישמרו את הנרמול הישן, ויווצרו כינויים כפולים.
    evidence: |-
      המפתח הייחודי בנוי מהפלט של normalize_he. כדי להכריע: מיגרציה שמחשבת מחדש את alias_norm, ומאחדת כינויים כפולים, בכל שינוי ב-normalize_he.
    location: >-
      backend/app/modules/catalog/models.py (ProductAlias.alias_norm)
    severity: low
---

<intent-contract>

## Intent

**Problem:** עדיין אין `product_aliases`, ואין `matching.service.match`. מוצרים מהקבצים הרשמיים נוצרים לפי ברקוד (3.4), אבל השם שהרשת נותנת להם לא נשמר ככינוי. גם אין נקודת כניסה אחת שחשבוניות (Epic 6) ופריטים בלי ברקוד (3.6) יוכלו לקרוא לה.

**Approach:**
- מוסיפים את הטבלה `product_aliases` (שייכת ל-catalog) ואת `matching.service.match`.
- כינוי עם ברקוד תקין שקיים ב-`products` מקבל כינוי `certain`, עם confidence 1.0, ומוחזר כהתאמה ודאית, בלי שום מגע עם המשתמש.
- כל השאר מוחזר כ-`unmatched`. ‏4.2 תמלא את המסלול של טקסט.
- קליטת PriceFull רושמת את הכינויים של פריטים עם ברקוד בבת אחת, דרך `matching.service.match_barcodes`.

## Boundaries & Constraints

**Always:**
- **`product_aliases` (שייכת ל-catalog, ו-matching כותב אליה רק דרך `catalog.service`):**
  - העמודות: id (UUIDv7), ‏chain_id FK, ‏alias_text (NFC, אחרי כיווץ רווחים), ‏alias_norm (`normalize_he(alias_text)`), ‏barcode null, ‏product_id FK null, ‏state (`certain`, ‏`uncertain`, ‏`final`, ‏`disputed`), ‏confidence numeric(4,3) null, ‏created_at, ‏updated_at.
  - unique על `(chain_id, alias_norm, barcode)` עם `NULLS NOT DISTINCT` (PG16).
  - אינדקס על `product_id`, ו-CHECK על `state` ועל `confidence` (בין 0 ל-1).
- **ברקוד תקין:** אותו כלל כמו ב-3.4. 8 עד 14 ספרות, לא רק אפסים, ונשמר כמו שהוא.
  - הכלל עובר לפונקציה ציבורית, `catalog.service.valid_barcode(code: str) -> str | None`, שמנקה רווחים בקצוות.
  - `ingestion.prices.barcode_of` משתמשת בה (כש-`ItemType=1`).
  - **אין בדיקת ספרת ביקורת:** בקבצים האמיתיים 3% מהברקודים לא עוברים אותה, והם עדיין מוצרים אמיתיים (נבדק ב-PriceFull של קרפור, 358 מתוך 10,926).
- **`matching.service.match(session, alias_text, chain_id, barcode=None, context=None) -> MatchResult`:**
  - `MatchResult(state, product_id, alias_id, confidence, candidates)`. ‏state הוא `certain`, ‏`uncertain`, ‏`new_product_proposal` או `unmatched`. ‏candidates הוא tuple, ריק ב-4.1.
  - `context` הוא `MatchContext(source: "official_file" | "receipt", unit_price_agorot: int | None)`. ב-4.1 לא משתמשים בו. הוא קיים בשביל 4.2.
  - **ברקוד תקין שיש לו מוצר:**
    - נוצר כינוי, או נשמר הקיים לאותו `(chain_id, alias_norm, barcode)`, עם product_id של המוצר, ‏state=`certain` ו-confidence=1.
    - **כינוי קיים במצב `final` או `disputed`:** לא משנים אותו. מחזירים את המצב שלו ואת ה-product_id שלו.
    - **כינוי קיים במצב `certain` שמצביע על מוצר אחר:** מעדכנים למוצר של הברקוד. הברקוד קובע.
    - מחזירים `certain`, עם ה-product_id וה-alias_id.
  - **אחרת** (אין ברקוד, הברקוד לא תקין, או שאין מוצר עם הברקוד): מחזירים `unmatched`, עם product_id=None ו-alias_id=None. **לא** נוצרים כינוי ומוצר. זה התפקיד של 4.2.
  - טקסט ריק אחרי נרמול: מחזירים `unmatched`.
- **`matching.service.match_barcodes(session, chain_id, items: Iterable[tuple[alias_text, barcode]]) -> int`:**
  - הגרסה של המסלול שלמעלה ל-bulk, לקליטה.
  - פריטים שהברקוד שלהם תקין ויש לו מוצר נכתבים עם `INSERT … ON CONFLICT (chain_id, alias_norm, barcode) DO NOTHING`, באצוות של 1000. ממיינים לפי המפתח, כדי ששתי רשתות במקביל לא ייתקעו זו על זו (deadlock).
  - מחזירה את מספר הכינויים החדשים.
  - לא נוגעת בכינויים קיימים.
- **הקליטה:** `price_handler` (3.4) קורא ל-`match_barcodes` אחרי `ensure_products_by_barcode`, עם `(item.name, item.barcode)` לכל פריט, באותה טרנזקציה. הלוג `ingestion_prices` מקבל את `aliases_new`.
- **כלל ברזל:** רק matching יוצר כינויים, ורק catalog יוצר מוצרים. matching לא יוצר מוצר ב-4.1.
- **לוג:** `matching_match` עם state, ‏source ו-had_barcode. בלי טקסט הכינוי.
- **מיגרציה:** `0011`.

**Never:**
- לא לבצע התאמה לפי טקסט, ולא ליצור הצעה למוצר חדש (4.2). לא לשמור הצבעות (4.3).
- לא לשנות ברקודים קיימים, לא להוסיף אפסים בהתחלה, ולא לאחד UPC-A עם EAN-13 (ראו Design Notes).
- לא לכתוב ישירות לטבלאות של catalog מתוך matching. לא להוסיף endpoint.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| ברקוד קיים | ‏"חלב 3% 1ל", ברקוד `7290000000001` שיש לו מוצר | ‏`certain`, ‏confidence 1, ה-product_id של המוצר. נוצר כינוי אחד | — |
| קריאה חוזרת | אותו טקסט, ברקוד ורשת | אותו alias_id. לא נוצרת שורה נוספת | — |
| טקסט שונה, אותו ברקוד | ‏"חלב תנובה 3%" | כינוי שני לאותו מוצר | — |
| רשת אחרת | אותו טקסט וברקוד, ‏chain_id אחר | כינוי נפרד, לאותו מוצר | — |
| ברקוד לא קיים | ברקוד תקין שאין לו מוצר | ‏`unmatched`. אין כינוי ואין מוצר | — |
| ברקוד לא תקין | ‏`123`, ‏`00000000`, ‏`abc`, ריק | ‏`unmatched` | — |
| אין ברקוד | ‏barcode=None | ‏`unmatched` | — |
| ‏final לא נדרס | כינוי `final` למוצר A, והברקוד שייך עכשיו למוצר B | מחזיר `final` ואת A. השורה לא משתנה | — |
| ‏certain מתעדכן | כינוי `certain` למוצר A, והברקוד שייך למוצר B | השורה עוברת ל-B. מחזיר `certain` ואת B | — |
| הקליטה | ‏PriceFull עם 3 פריטים עם ברקוד ופריט פנימי | 3 כינויים `certain` לרשת. בקובץ שני אין כינויים חדשים | — |
| טקסט ריק | ‏"   " עם ברקוד קיים | ‏`unmatched` | — |

</intent-contract>

## Code Map

- `backend/app/modules/catalog/{models,repository,service}.py` -- `Product`, ‏`ProductRecord`, ‏`ensure_products_by_barcode` (שורה 344), ‏`product_ids_by_barcode` (379) ו-`normalize_he`. כאן נוספים `ProductAlias`, ‏`valid_barcode`, ‏`upsert_certain_alias` ו-`ensure_certain_aliases` (bulk).
- `backend/app/modules/matching/{models,repository,service,schemas}.py` -- stubs ריקים. ‏`service.py` מקבל את `MatchResult`, ‏`MatchContext`, ‏`match` ו-`match_barcodes`. ‏`models.py` נשאר ריק עד 4.2 (`match_candidates`).
- `backend/app/modules/ingestion/prices.py` -- `barcode_of` (משתמשת ב-`valid_barcode`) ו-`price_handler`, שקורא ל-`match_barcodes`.
- `backend/migrations/versions/0010_ingestion_health.py` -- המיגרציה האחרונה. החדשה היא `0011`.
- `backend/tests/integration/test_prices.py`, ‏`test_ingestion*.py`, ‏`test_stores.py`, ‏`test_clubs.py`, ‏`test_brands.py`, ‏`test_delete_account.py` -- להוסיף `product_aliases` לכל TRUNCATE של `products` או `chains`.

## Tasks & Acceptance

**Execution:**
- `backend/app/modules/catalog/{models,repository,service}.py` + `backend/migrations/versions/0011_product_aliases.py` -- הטבלה, ‏`valid_barcode`, והכתיבה הבודדת ו-ה-bulk.
- `backend/app/modules/matching/service.py` -- `MatchResult`, ‏`MatchContext`, ‏`match` ו-`match_barcodes`.
- `backend/app/modules/ingestion/prices.py` -- `valid_barcode`, והקריאה ל-`match_barcodes`.
- `backend/tests/integration/test_matching_barcode.py` -- כל שורות המטריצה.
- `backend/tests/unit/test_matching.py` -- `valid_barcode`, וש-`MatchResult` של `unmatched` לא נוגע ב-DB (בלי session אמיתי).
- `backend/tests/integration/*.py` -- הוספה ל-TRUNCATE.

**Acceptance Criteria:**
- Given כינוי עם ברקוד תקין שיש לו מוצר במאגר, when קוראים ל-`match`, then מתקבלת התאמה `certain` למוצר, נשמר כינוי, ואין שום שאלה למשתמש.
- Given קובץ PriceFull שנקלט, when הריצה מסתיימת, then לכל פריט עם ברקוד ברשת יש כינוי `certain` למוצר שלו.

## Spec Change Log

## Review Triage Log

### 2026-11-09 — Review pass
- verdicts: 24 findings — high 0, medium 3, low 17, false 4, maybe-false 0
- findings:
  - Verification Gap:
    - `low` `patch` אין בדיקה לחוקיות של confidence — `test_a_lower_confidence_becomes_one`.
  - Edge Case Hunter:
    - `low` `patch` שם ארוך מאוד מכשיל את כל ה-PriceFull — `clean_alias_text` מחזיר None מעל 500 תווים.
    - `low` `reject` מרוץ ב-SELECT שאחרי ה-upsert — כינויים לא נמחקים, וב-READ COMMITTED השורה קיימת.
    - `low` `patch` ‏disputed עם product_id ריק — מתועד ב-`MatchState`: משתמשים ב-product_id רק כשהוא לא None.
    - `medium` `patch` (claim) המסלול ה-bulk לא מעדכן כינוי ישן — `ON CONFLICT DO UPDATE` עם אותו תנאי כמו ב-match.
  - Blind Hunter:
    - `medium` `patch` שני מסלולי הכתיבה לא עקביים כשברקוד עובר למוצר אחר — אותו תיקון. ‏`test_match_barcodes_follows_the_barcode`.
    - `low` `patch` חיפוש ברקודים כפול בקליטה — `match_barcodes` מקבל את `product_ids`.
    - `low` `reject` פריט עם `bad_price` לא מקבל כינוי — ההגדרה של ה-spec היא הפריטים שנקלטו. השם הראשון קובע, כמו ב-3.4.
    - `low` `defer` אין תוכנית לנרמול מחדש של alias_norm — נרשם ב-deferred.
    - `low` `patch` ‏`pytest.raises(Exception)` — עכשיו `IntegrityError` ושם האילוץ.
    - `low` `reject` אין בדיקת מקביליות למיון — אותו דפוס כמו `ensure_products_by_barcode` (3.4).
    - `low` `reject` ‏FK בלי `ON DELETE` — מוצרים לא נמחקים. ב-4.5 המיזוג יעביר את הכינויים במפורש.
    - `low` `reject` רשימת ה-states כתובה פעמיים — כמקובל במיגרציות. ‏alembic check משווה את המבנה.
    - `low` `patch` ‏`match_barcodes` לא כותב לוג — נוסף `matching_match_bulk` עם מונים.
    - `low` `reject` ייבוא של helpers פרטיים מבדיקה אחרת — רק בבדיקות. אפשר להעביר אותם כשיהיה צרכן נוסף.
    - `low` `patch` הטקסט נוקה פעמיים, וענף שלא מגיעים אליו — ניקוי אחד, והענף נמחק.
    - `low` `patch` ‏`MatchState` רחב יותר מה-spec — מתועד ב-docstring.
  - Intent Alignment:
    - `false` `reject` ‏(a) "בלי לערב את המשתמש" לא נבדק במסך — מסך אישור החשבונית שייך ל-Epic 6. ‏`match` לא מכיל שום צעד של משתמש.
    - `false` `reject` ‏(b) הענף "אין מוצר" לא מופעל בקליטה — זה מכוון: 3.4 יוצרת את המוצרים לפני. הענף נבדק ב-`match`.
    - `medium` `patch` ‏(c) המסלולים לא עקביים — אותו תיקון.
    - `low` `patch` ‏(d) ה-bulk עוקף את נקודת הכניסה של AD-9 — הוא בתוך matching, וכותב לוג משלו. ‏AD-9 מדבר על המודול, לא על פונקציה אחת.
    - `low` `reject` ‏(e) מוצר `proposed` או `merged_into` נחשב "קיים" — היום כל המוצרים `active`. ב-4.5 המיזוג יעביר את הברקוד.
    - `false` `reject` ‏(f) אין בדיקת ספרת ביקורת — מכוון, ומבוסס על נתונים אמיתיים (358 מתוך 10,926).
    - `false` `reject` ‏(g) הבדיקות לא מגיעות למסך — אותו נימוק כמו ב-(a).

## Design Notes

**למה לא לאחד UPC-A ו-EAN-13 עכשיו:** קוד של 12 ספרות וקוד של 13 ספרות עם 0 בהתחלה הם אותו GTIN. אבל ב-3.4 הברקודים נשמרים כמו שהם, ובקבצים יש גם קודים של 10 ו-11 ספרות, כנראה אחרי שאיבדו אפסים. איחוד דורש מיגרציה של `products.barcode` ומיזוג מוצרים, ולכן הוא נדחה. אפשר לחזור אליו עם כלי המיזוג של 4.5.

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy` -- expected: נקי.
- `cd backend && CARTWISE_REQUIRE_DOCKER=1 uv run pytest` -- expected: הכל עובר.

## Auto Run Result

Status: done

**סיכום:**
- נוספה הטבלה `product_aliases`, שייכת ל-catalog, עם unique `NULLS NOT DISTINCT` על `(chain_id, alias_norm, barcode)`.
- נוסף `matching.service.match`: כינוי עם ברקוד תקין, שיש לו מוצר, מקבל כינוי `certain` עם confidence 1. כינוי `final` או `disputed` לא משתנה. כל השאר מוחזר כ-`unmatched`, בלי כתיבה.
- נוסף `match_barcodes` ל-bulk, שהקליטה של PriceFull קוראת לו. גם הוא מעביר כינוי `certain` או `uncertain` לברקוד הנוכחי.
- ‏`valid_barcode` עבר ל-catalog, ואין בו בדיקת ספרת ביקורת.

**קבצים:**
- `backend/app/modules/catalog/{models,repository,service}.py`, `backend/migrations/versions/0011_product_aliases.py` -- הטבלה, ‏`valid_barcode`, ‏`clean_alias_text`, וה-upserts.
- `backend/app/modules/matching/service.py` -- `MatchResult`, ‏`MatchContext`, ‏`match` ו-`match_barcodes`.
- `backend/app/modules/ingestion/prices.py` -- הכינויים בזמן הקליטה.
- `backend/tests/...` -- המטריצה, ה-bulk והסכמה.

**ממצאי הסקירה:** 24 ממצאים:
- **תוקנו:** entry אחד ברמת medium (המסלול ה-bulk מעדכן כינוי ישן), ו-10 ברמת low.
- **נדחה ל-deferred:** אחד (נרמול מחדש).
- **נדחו לגמרי:** השאר.

**המלצה לסקירת המשך:** `true`. ה-entry ברמת medium שתוקן משנה את המסלול שהקליטה בפועל משתמשת בו. הסיכון שלא אומת: הזמן של `ON CONFLICT DO UPDATE` בנפח אמיתי.

**אימות:**
- ruff, format ו-mypy נקיים.
- `CARTWISE_REQUIRE_DOCKER=1 pytest`: 811 עברו.
- gitleaks על הקבצים שהשתנו: `no leaks found`.
