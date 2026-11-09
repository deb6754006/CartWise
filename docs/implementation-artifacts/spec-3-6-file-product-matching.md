---
title: 'Story 3.6: התאמת מוצרים מקבצים, מסלול הפריטים בלי ברקוד'
type: 'feature'
created: '2026-11-09'
status: 'done'
baseline_revision: '198b97b9c9311900a19f5a4a2088a0310f1878a3'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/docs/implementation-artifacts/spec-3-4-prices-promotions.md'
  - '{project-root}/docs/implementation-artifacts/spec-4-2-text-matching.md'
warnings: ['oversized']
deferred:
  - summary: >-
      פריט בלי ברקוד שמותאם כ-uncertain, או למוצר proposed, מקבל תצפית regular רשמית. כך מחיר עלול להיכתב על מוצר שגוי.
    evidence: |-
      זו החלטה מכוונת: בלעדיה, לפריטים בלי ברקוד אין מחיר בכלל. FR-39 קובע "צהוב לכל היותר" כל עוד ההתאמה לא סופית. כדי להכריע: ב-Epic 7 (reliability_level) להחיל את התקרה על תצפיות של מוצרים שהכינוי שלהם לא final, ולבדוק את זה.
    location: >-
      backend/app/modules/ingestion/prices.py (price_handler)
    severity: medium
  - summary: >-
      קוד הפריט הפנימי (ItemCode) לא נשמר, ולכן אי אפשר לקשר מבצעים של פריטים בלי ברקוד.
    evidence: |-
      ב-PromoFull לפריט יש רק ItemCode, בלי שם. כדי להכריע: לשמור את המיפוי (chain, item_code) → מוצר בזמן הקליטה של PriceFull, ולהשתמש בו ב-promo_handler.
    location: >-
      backend/app/modules/ingestion/prices.py (InternalItem)
    severity: low
---

<intent-contract>

## Intent

**Problem:** FR-17 כולל שני חלקים.
- **פריט עם ברקוד:** מותאם למוצר עם אותו ברקוד, ונוצר מוצר כשאין כזה. החלק הזה כבר נבנה ב-3.4 (`ensure_products_by_barcode`) וב-4.1 (`match_barcodes`).
- **פריט בלי ברקוד** (`ItemType=0`, למשל ירקות במשקל, כ-2% מהפריטים): צריך לעבור את מנגנון ההתאמה של Epic 4. היום הוא מדולג (`no_barcode`), ולכן אין לו מחיר.

**Approach:**
- `parse_price_file` מחזיר גם את הפריטים בלי ברקוד, כרשימה נפרדת.
- `price_handler` מעביר אותם דרך פונקציה חדשה, `matching.service.match_file_items`.
  - כשכבר יש כינוי שמצביע על מוצר, הפונקציה משתמשת בו בלי לחשב ניקוד מחדש.
  - אחרת היא קוראת ל-`match`.
- לכל פריט שקיבל `product_id` נכתבת תצפית `regular`, כמו לפריט עם ברקוד.

## Boundaries & Constraints

**Always:**
- **פענוח:** פריט עם `ItemType` שונה מ-1, או עם ברקוד לא תקין, נכנס ל-`PriceFile.internal_items`. כל פריט כזה הוא `InternalItem(name, price_agorot, per, is_weighted, pack_size, pack_unit, observed_at)`, עם אותם כללים כמו פריט רגיל: מחיר תקין, יש שם. ה-skips נשארים כמו שהם (`bad_price`, ‏`no_name`).
  - המונה `no_barcode` עובר להיות `internal`, וסופר את הפריטים שהועברו להתאמה.
  - שני פריטים פנימיים עם אותו `alias_norm` בקובץ: הראשון קובע, והשני נספר כ-`duplicate`.
- **`matching.service.match_file_items(session, chain_id, items: Sequence[tuple[alias_text, unit_price_agorot | None]]) -> list[UUID | None]`:** מחזירה product_id לכל פריט, באותו סדר, או None.
  1. מנקה את כל הטקסטים עם `clean_alias_text`. טקסט שמתנקה ל-None מקבל None.
  2. שאילתה אחת: כינויים קיימים לרשת עם `barcode IS NULL` ו-`alias_norm` מהרשימה. **כינוי קיים שיש לו product_id** (בכל state) מחזיר אותו, בלי ניקוד ובלי כתיבה.
  3. כל השאר עוברים ל-`match(session, text, chain_id, barcode=None, context=MatchContext(source="official_file", unit_price_agorot=price))`. התוצאה: `product_id` שלה. ב-`certain`, ב-`uncertain` וב-`new_product_proposal` יש product. ב-`unmatched` אין.
  4. לוג אחד, `matching_file_items`, עם items, ‏reused, ‏matched, ‏certain, ‏uncertain, ‏proposed ו-unmatched. בלי טקסטים.
- **תצפיות:** לכל פריט פנימי עם product_id נכתבת `OfficialPrice`, ונכנסת לאותה קריאה ל-`record_official_prices` שמשמשת את הפריטים עם הברקוד. אם שני פריטים בקובץ קיבלו אותו product_id, למשל מהברקוד ומהטקסט, הראשון קובע, כי הפריטים עם הברקוד באים קודם.
  - פריט שלא קיבל מוצר נספר כ-`internal_unmatched` בלוג `ingestion_prices`. יש גם `internal_priced`.
- **מחיר בהקשר:** `MatchContext.unit_price_agorot` מקבל את המחיר רק כש-`per == "unit"`. בפריט במשקל הוא None, כי `median_prices` של 4.2 מחשב רק ליחידה.
- **סדר בטרנזקציה:** ‏`ensure_products_by_barcode`, אחריו `match_barcodes`, אחריו `match_file_items`, ואחריו `record_official_prices`. הכל באותה טרנזקציה של הקובץ. כשל מכשיל את הקובץ כולו (3.2).
- **אין שינוי בכללי ההתאמה של 4.2,** ואין שינוי במסלול הברקוד.

**Never:**
- לא לחשב ניקוד מחדש לכינוי קיים שיש לו מוצר. זיכרון לפי `final` הוא 4.4, ותיקון כינויים הוא 4.3 ו-4.5.
- לא לקשר פריטים פנימיים במבצעים. ב-PromoFull יש ל-PromotionItem רק `ItemCode` פנימי, בלי שם (ראו Design Notes).
- לא לשמור את קוד הפריט הפנימי כברקוד.
- לא לשנות את קובצי ה-fixtures הקיימים. מוסיפים fixture או פריטים בדויים.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| פריט פנימי שמותאם | ‏PriceFull עם פריט ItemType 0 "עגבניות שרי במשקל", ובמאגר מוצר דומה מאוד | כינוי `certain`, ותצפית `regular` למוצר. ‏`current_prices` מכיל אותו | — |
| פריט פנימי חדש | שם שלא דומה לשום מוצר | מוצר `proposed`, כינוי `uncertain`, ותצפית למוצר המוצע | — |
| קובץ שני, אותו פריט | אותו טקסט, עם כינוי קיים | אין קריאה ל-`match`, לפי ספירת reused בלוג. אותו מוצר. תצפית רק אם המחיר השתנה | — |
| טקסט שמתנקה לריק | ‏ItemName "***" | אין מוצר ואין תצפית. נספר כ-`internal_unmatched` | — |
| פריט במשקל | ‏bIsWeighted 1, ‏ItemPrice 12.90 | ‏per `kg`, ‏1290. ‏context.unit_price_agorot None | — |
| שני פריטים פנימיים, אותו שם | פעמיים "בננה" | אחד מותאם, השני `duplicate` | — |
| פריט עם ברקוד, וגם פריט פנימי לאותו מוצר | ברקוד של מוצר X, ושם פנימי שמותאם ל-X | תצפית אחת, לפי הפריט עם הברקוד | — |
| ‏unit price בהקשר | פריט פנימי לא שקיל, 5.00 | ‏`match` נקרא עם ‏unit_price_agorot 500 | — |

</intent-contract>

## Code Map

- `backend/app/modules/ingestion/prices.py:193` -- `parse_price_file`: מדלג היום על `no_barcode` (שורה ~202). כאן נוסף `internal_items`. ‏`price_handler`: ‏`ensure_products_by_barcode`, אחריו `match_barcodes`, ואחריו `record_official_prices`. כאן נוסף `match_file_items` לפני ה-record.
- `backend/app/modules/matching/service.py:348` -- `match(session, alias_text, chain_id, barcode, context, now)`, ‏`MatchContext`, ‏`MatchResult`. כאן נוסף `match_file_items`.
- `backend/app/modules/catalog/service.py` -- `clean_alias_text`. מוסיפים `alias_products_by_norm(session, chain_id, norms) -> dict[str, UUID]`, שמחזירה כינויים בלי ברקוד שיש להם מוצר.
- `backend/app/modules/pricing/service.py` -- `OfficialPrice` ו-`record_official_prices`, בלי שינוי.
- `backend/tests/integration/test_prices.py` -- helpers ‏(`_item`, ‏`_price_file`, ‏`_store`). ‏`backend/tests/unit/test_ingestion_prices.py` -- בדיקות הפענוח, שבהן `no_barcode` משתנה ל-`internal`.

## Tasks & Acceptance

**Execution:**
- `backend/app/modules/ingestion/prices.py` -- `InternalItem`, ‏`internal_items` בפענוח, והחיבור ב-handler.
- `backend/app/modules/catalog/{repository,service}.py` -- `alias_products_by_norm`.
- `backend/app/modules/matching/service.py` -- `match_file_items`.
- `backend/tests/unit/test_ingestion_prices.py` -- הפענוח החדש.
- `backend/tests/integration/test_file_matching.py` -- כל שורות המטריצה.
- `deploy/README.md` -- הדילוג על פריטים בלי ברקוד מוחלף בהסבר על ההתאמה שלהם.

**Acceptance Criteria:**
- Given מוצר עם ברקוד בקובץ, when הוא נקלט, then הוא מותאם למוצר עם אותו ברקוד, ואם אין כזה, נוצר מוצר. כבר מתקיים מ-3.4 ו-4.1, ונבדק כאן פעם נוספת בבדיקה אחת.
- Given מוצר בלי ברקוד בקובץ, when הוא נקלט, then הוא עובר את מנגנון ההתאמה של Epic 4, ומקבל תצפית מחיר למוצר שנבחר.

## Spec Change Log

## Review Triage Log

### 2026-11-09 — Review pass
- verdicts: 28 findings — high 0, medium 1, low 25, false 2, maybe-false 0
- findings:
  - Intent Alignment:
    - `low` `reject` ‏(R2) פריטים פנימיים ב-PromoFull לא מותאמים — מתועד, ונרשם ב-deferred (ItemCode).
    - `low` `reject` ‏(R3) כינוי קיים בכל state נלקח שוב בלי ניקוד — החלטה של ה-spec, לטובת הנפח בקליטה. ‏4.3 ו-4.5 מסדרים כינויים.
    - `medium` `defer` ‏(R4) מחיר רשמי למוצר שההתאמה שלו uncertain או proposed — נרשם ב-deferred ל-Epic 7.
    - `false` `reject` ‏AC1 מתקיים בזכות קוד קיים — נכון, וזה מתועד. נוספה בדיקה.
  - Blind Hunter:
    - `low` `patch` שימוש חוזר במוצר שמוזג — JOIN, ודילוג על `merged_into`.
    - `low` `reject` שימוש חוזר לא בודק את ה-state — אותו נימוק כמו (R3).
    - `low` `patch` שני מפתחות כפילות שונים — `catalog_service.alias_norm` משותף.
    - `low` `defer` ‏ItemCode נזרק — נרשם ב-deferred.
    - `low` `patch` שני קודים פנימיים באותו שם — `duplicate_name`.
    - `low` `reject` אין savepoint לכל פריט — כשל ב-DB מכשיל את הקובץ, והוא נקלט שוב (3.2).
    - `low` `reject` אין last_seen לכינוי — לא נדרש היום.
    - `low` `reject` מחיר ליחידה בפריט ארוז — ההשוואה היא לחציון ליחידה של אותו מוצר.
    - `low` `patch` אין בדיקה ל-`internal_same_product` ולסדר ההפוך — נוספה, עם parametrize.
    - `low` `patch` אין בדיקה לשימוש חוזר באותה קריאה — נוספה.
    - `low` `patch` מילון עם מפתח None — לפי שם.
    - `low` `patch` בדיקה כפולה ב-repository — נמחקה.
    - `low` `reject` שדות ב-helper של הלוג בבדיקה — רק בבדיקות.
    - `low` `patch` שורה שבורה ב-docstring — תוקנה.
    - `false` `reject` ה-spec לא בתוך ה-diff — הוצא בכוונה.
    - `low` `patch` ה-README לא מסביר את הקפיצה ב-records — עכשיו מסביר.
  - Verification Gap:
    - `low` `patch` אין בדיקה לשתי רשתות — נוספה (spy == 2, ושני כינויים).
    - `low` `patch` (Other) מוצר `merged_into` — אותו תיקון.
  - Edge Case Hunter:
    - `low` `patch` ‏`merged_into` — אותו תיקון.
    - `low` `reject` כינוי uncertain לא מנוקד שוב — אותו נימוק כמו (R3).
    - `low` `patch` ‏final ו-disputed לא נספרים בלוג — נספרים.
    - `low` `patch` מוצר מוצע לפריט במשקל — `FileItem` מעביר `is_weighted` וגודל.
    - `low` `reject` ‏per שמתחלף בין קבצים — נדיר. הפריט עם הברקוד קובע בתוך קובץ.
    - `low` `patch` שני מפתחות כפילות — אותו תיקון.

## Design Notes

**מבצעים של פריטים פנימיים:** ב-PromoFull יש לפריט רק `ItemCode` פנימי. כדי לקשר אותו, צריך מיפוי של `(chain, item_code)` למוצר, מתוך ה-PriceFull של אותה רשת. זה שינוי בסכמה (עמודה או טבלה), ונדחה. בינתיים מבצעים על ירקות במשקל לא נכנסים, כמו היום.

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy` -- expected: נקי.
- `cd backend && CARTWISE_REQUIRE_DOCKER=1 uv run pytest` -- expected: הכל עובר.

## Auto Run Result

Status: done

**סיכום:** פריט בלי ברקוד מ-PriceFull כבר לא מדולג. הוא עובר את `matching.service.match_file_items`:
- **כינוי קיים של הרשת:** משמש שוב, בלי ניקוד (בלי מוצרים `merged_into`).
- **אחרת:** `match`, עם ההקשר של המחיר, ושל המשקל והגודל להצעה.

פריט שקיבל מוצר מקבל תצפית `regular`. כשאותו מוצר בא גם מפריט עם ברקוד, הפריט עם הברקוד קובע. ‏AC1 (ברקוד) כבר התקיים מ-3.4 ו-4.1, ונבדק כאן שוב.

**קבצים:**
- `backend/app/modules/ingestion/prices.py` -- `InternalItem`, ‏`internal_items`, ‏`duplicate_name` והחיבור.
- `backend/app/modules/matching/service.py` -- `FileItem` ו-`match_file_items`.
- `backend/app/modules/catalog/{repository,service}.py` -- `alias_products_by_norm`, ‏`alias_norm`, ו-`propose_product(is_weighted)`.
- `deploy/README.md`.
- הבדיקות.

**ממצאי הסקירה:** 28 ממצאים:
- **תוקנו:** 13 ברמת low.
- **נדחו ל-deferred:** 2. אחד מהם ברמת medium: מחיר של התאמה לא ודאית, שמחכה לתקרת האמינות של Epic 7.
- **נדחו לגמרי:** השאר.

**המלצה לסקירת המשך:** `false`. לא תוקן entry ברמת medium.

**אימות:**
- ruff, format ו-mypy נקיים.
- `CARTWISE_REQUIRE_DOCKER=1 pytest`: 914 עברו.
- gitleaks על כל מה שלא נדחף: `no leaks found`.
