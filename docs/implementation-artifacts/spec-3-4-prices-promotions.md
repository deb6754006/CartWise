---
title: 'Story 3.4: מחירים ומבצעים מקובצי PriceFull ו-PromoFull'
type: 'feature'
created: '2026-11-03'
status: 'done'
baseline_revision: '4b165de7b1b07053dca630a0b8ea3be301011a3f'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/docs/implementation-artifacts/epic-3-context.md'
  - '{project-root}/docs/implementation-artifacts/spec-3-3-stores-locations.md'
warnings: ['oversized']
deferred:
  - summary: >-
      מוצר שירד מ-PriceFull נשאר ב-current_prices עם המחיר האחרון שלו, ונכנס להשוואות.
    evidence: |-
      PromoFull מטופל כתמונה מלאה, אבל PriceFull לא. כדי להכריע: ב-Epic 7 (אמינות לפי גיל) או ב-Epic 5, לחשב "נראה לאחרונה" לפי קובץ ה-PriceFull האחרון של הסניף, ולהוציא מוצר שלא הופיע בו.
    location: >-
      backend/app/modules/pricing/service.py (current_prices)
    severity: medium
  - summary: >-
      אין רישום של מתי מחיר אומת לאחרונה. observed_at הוא הפעם הראשונה שהמחיר נראה.
    evidence: |-
      כשהמחיר לא משתנה, לא נכתבת תצפית (AD-3). Design Notes קובעים שהגיל נמדד לפי ingestion_files. כדי להכריע: Epic 7 צריך לממש את זה, או להוסיף עמודה של אישור אחרון בלי UPDATE למחיר.
    location: >-
      backend/app/modules/pricing/repository.py (record_official_prices)
    severity: medium
---

<intent-contract>

## Intent

**Problem:** הקליטה של 3.2 ו-3.3 שומרת סניפים, אבל קובצי PriceFull ו-PromoFull רק נספרים. אין עדיין מוצרים, תצפיות מחיר, מבצעים או "מחיר נוכחי". Epic 5 צריך את כל אלה כדי להשוות סלים.

**Approach:**
- **PriceFull:** ה-handler כותב לכל פריט עם ברקוד מוצר דרך `catalog.service`, לפי ברקוד. אם אין מוצר, הוא נוצר. אחר כך נכתבת תצפית "regular" דרך `pricing.service`, append-only, ורק כשהמחיר השתנה.
- **PromoFull:** ה-handler שומר מבצעים עם תוקף, תנאי כמות ושיוך שמרני למועדון.
- **אחרי כל ריצה:** `current_prices` מתרענן.
- **פריט בלי ברקוד (ItemType=0):** מדולג ונספר. ההתאמה שלו שייכת ל-3.6 ול-Epic 4.

## Boundaries & Constraints

**Always:**
- **בעלות על טבלאות (AD-2):**
  - `products` שייכת ל-catalog.
  - `price_observations`, ‏`promotions` ו-`promotion_products`, וגם ה-view ‏`current_prices`, שייכים ל-pricing.
  - ingestion כותב רק דרך `catalog.service` ו-`pricing.service`.
- **מבנה הקובץ (אומת ב-2026-11-03 בקבצים של שלוש הרשתות):**
  - שורש שהילדים שלו הם `ChainID`, ‏`SubChainID`, ‏`StoreID`, ואחר כך `Items > Item`, או `Promotions > Promotion`.
  - **Item:** ‏`ItemCode`, ‏`ItemType` (1 = ברקוד, 0 = קוד פנימי), ‏`ItemName`, ‏`UnitQty` (למשל "גרם", "קילוגרם", "ליטר", "מיליליטר", "יחידה"), ‏`Quantity`, ‏`bIsWeighted`, ‏`ItemPrice` (בשקלים, למשל `13.90`) ו-`PriceUpdateTime`.
  - **Promotion:** ‏`PromotionID`, ‏`PromotionDescription`, ‏`PromotionStartDateTime`, ‏`PromotionEndDateTime` (זמן מקומי, בלי אזור זמן), ‏`ClubID`, ‏`AdditionalIsCoupon` ו-`Groups > Group > PromotionItems > PromotionItem`.
  - **PromotionItem:** ‏`ItemCode`, ‏`ItemType`, ‏`RewardType`, ‏`MinQty`, ‏`DiscountRate` ו-`DiscountedPrice`.
  - שמות התגים מושווים לפי local name, בלי תלות באותיות גדולות (`decode.local_name`).
- **הסניף:** לפי `StoreID` שבשורש, בלי אפסים מובילים, ו-`chain_id`, דרך `catalog.service.store_id_by_code`. אם הסניף לא קיים, הקובץ נכשל עם השגיאה `unknown store <code>`, וייקלט שוב בריצה הבאה. Stores נקלט ראשון בכל ריצה (3.2).
- **מוצרים (`products`):**
  - העמודות: id, ‏barcode (unique, ‏nullable), ‏name, ‏name_norm (`normalize_he`), ‏brand_id null, ‏category_id null, ‏pack_size numeric null, ‏pack_unit null (`unit`, ‏`g`, ‏`kg`, ‏`ml`, ‏`l`), ‏is_weighted, ‏status (`active`), ‏created_at. אינדקס trigram על `name_norm`.
  - **ברקוד תקין:** `ItemType=1` ו-`ItemCode` של 8 עד 14 ספרות. נשמר כמו שהוא, בלי לגעת באפסים.
  - **מוצר קיים:** לא משנים את השם שלו. השם הראשון קובע.
  - **יצירה:** ב-bulk, עם `INSERT … ON CONFLICT (barcode) DO NOTHING`, ואחר כך SELECT של המיפוי.
  - **מיפוי UnitQty:** "גרם" → g, ‏"קילוגרם"/"ק"ג" → kg, ‏"מיליליטר"/"מ"ל" → ml, ‏"ליטר" → l, ‏"יחידה"/"יח'" → unit. כל ערך אחר → null.
- **תצפיות (`price_observations`, append-only לפי AD-3):**
  - העמודות: id, ‏product_id, ‏store_id, ‏chain_id, ‏source=`official_file`, ‏price_type=`regular`, ‏unit_price_agorot int, ‏per (`unit`, או `kg` כש-`bIsWeighted=1`), ‏observed_at (מ-`PriceUpdateTime` מקומי ל-UTC; אם חסר או לא תקין, זמן הריצה), ‏source_ref (שם הקובץ), ‏contributor_user_id null, ‏status=`valid`, ‏has_personal_discount=false, ‏created_at.
  - אינדקס על `(store_id, product_id, observed_at desc)`.
  - **מחיר באגורות:** `Decimal` עם עיגול חצי למעלה. מחיר שאינו מספר, או שקטן או שווה ל-0, מדולג.
  - **מתי נכתבת תצפית:** רק כשאין תצפית `valid` קודמת מאותו `source` לאותם `(store, product, price_type)`, או כשה-`unit_price_agorot` או ה-`per` שלה שונים. ההשוואה נעשית מול התצפית האחרונה, בשאילתה אחת לכל קובץ.
  - **אין UPDATE.**
  - **פריט כפול בקובץ (אותו ברקוד):** הראשון קובע.
- **מבצעים (`promotions` + `promotion_products`):**
  - העמודות: id, ‏chain_id, ‏store_id, ‏gov_promotion_id, ‏description, ‏club_id null, ‏kind (`fixed_price`, ‏`multi_buy`, ‏`percent`), ‏min_qty numeric, ‏bundle_price_agorot null, ‏percent numeric null, ‏starts_at, ‏ends_at, ‏source=`official_file`, ‏updated_at.
  - unique על `(store_id, gov_promotion_id)`.
  - ב-`promotion_products` יש `(promotion_id, product_id)` כ-PK.
  - **סוג המבצע:** נגזר מה-PromotionItem הראשון שיש לו מוצר:
    - **`RewardType=10`, או `MinQty` גדול מ-1:** ‏`multi_buy`. ‏`min_qty=MinQty`, ‏`bundle_price_agorot=DiscountedPrice`. למשל "2 ב-20": ‏MinQty 2, ‏DiscountedPrice 20.00.
    - **`RewardType=2`:** ‏`percent`. ‏`percent=DiscountRate`, ו-`bundle_price_agorot=DiscountedPrice`, אם יש.
    - **`RewardType=3`, או כל מבצע אחר עם `DiscountedPrice` חיובי ו-MinQty קטן או שווה ל-1:** ‏`fixed_price`. ‏`min_qty=1`, ‏`bundle_price_agorot=DiscountedPrice`. כולל `MinQty` כמו 0.010, בפריט במשקל.
    - **בלי `DiscountedPrice` חיובי, ולא `percent`:** המבצע מדולג.
  - **מבצעים שמדלגים עליהם, כדי לא להציג מחיר שאולי לא זמין:**
    - מבצע עם `AdditionalIsCoupon=1`.
    - מבצע שאף פריט שלו לא מתאים למוצר קיים, לפי ברקוד. כאן לא יוצרים מוצרים.
    - מבצע שה-`ends_at` שלו עבר כבר בזמן הקליטה.
  - **מועדון, לפי הכלל השמרני:**
    - `ClubID` שהוא בדיוק `0`, או מתחיל ב-`0 - כלל הלקוחות`, פירושו `club_id=null`.
    - כל ערך אחר, כולל ריק וכולל ביטויים עם `|` או `&`, פירושו המועדון של הרשת: `catalog.service.ensure_chain_club(session, chain_id)`, עם השם `מועדון <שם הרשת>`, אחד לרשת.
  - **זמנים:** מקומי `Asia/Jerusalem` ← UTC, דרך `zoneinfo`. מוסיפים את `tzdata` כתלות מפורשת (חינמית), כדי שה-image ב-Linux לא ייכשל. זמן התחלה חסר: זמן הריצה. זמן סיום חסר: המבצע מדולג.
  - **PromoFull הוא תמונה מלאה של הסניף:**
    - מבצע מהקובץ מעודכן לפי `(store_id, gov_promotion_id)`, והמוצרים שלו מוחלפים.
    - מבצע של הסניף שלא מופיע בקובץ, ועוד לא הסתיים, מקבל `ends_at` = זמן הריצה.
- **מבצע שפג תוקפו:** `pricing.service.active_promotions(session, store_ids, at)` מחזירה רק מבצעים עם `starts_at <= at < ends_at`. זו נקודת הכניסה של Epic 5 למחיר האפקטיבי.
- **`current_prices`:**
  - materialized view, עם התצפית `valid` האחרונה לכל `(store_id, product_id, price_type)`: ‏unit_price_agorot, ‏per, ‏observed_at ו-observation_id.
  - unique index, כדי לאפשר `REFRESH … CONCURRENTLY`.
  - `pricing.service.refresh_current_prices(session)` נקראת בסוף כל ריצה ב-`ingestion.service._run`, אחרי `finish_run`, גם בריצה partial. כשל בריענון נרשם בלוג, ולא משנה את ה-status של הריצה.
- **מה ה-handlers מחזירים:**
  - ‏price_full: מספר התצפיות החדשות + מספר הפריטים שלא השתנו. כלומר כל הפריטים שעובדו.
  - ‏promo_full: מספר המבצעים שנשמרו.
  - שני ה-handlers רושמים בלוג מונים לפי סיבת הדילוג, בלי שמות מוצרים ובלי מחירים.
- **מיגרציה:** `0009`.

**Never:**
- לא לבצע HTTP אמיתי בבדיקות. אין בריפו קבצים אמיתיים של רשתות. ה-fixtures בדויים: מוצרים, ברקודים ומחירים מומצאים.
- לא לבצע UPDATE ל-`unit_price_agorot` או ל-`per` של תצפית. לא למחוק תצפיות.
- לא להתאים פריט בלי ברקוד, ולא ליצור `product_aliases` (3.6 ו-Epic 4).
- לא לחשב מחיר אפקטיבי או השוואה (Epic 5). לא לחלק את `price_observations` למחיצות לפי חודש (ראו Design Notes).
- לא לשנות את ה-adapters, את הנעילה או את מבנה היומן של 3.2.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| ‏PriceFull ראשון | 3 פריטים עם ברקוד ופריט אחד עם ItemType 0, בסניף קיים | 3 מוצרים ו-3 תצפיות `regular` באגורות (13.90 → 1390). הפריט הפנימי מדולג. ‏`current_prices` מכיל 3 שורות אחרי הריצה | — |
| אותו מחיר שוב | קובץ חדש (hash אחר), עם אותם מחירים | אין תצפיות חדשות | — |
| מחיר השתנה | פריט אחד, 13.90 → 12.90 | תצפית אחת חדשה. הישנה נשארת. ‏`current_prices` מראה 1290 | — |
| פריט במשקל | ‏`bIsWeighted=1`, ‏ItemPrice 66.00 | ‏per `kg`, ‏6600 | — |
| מחיר לא תקין | ‏`ItemPrice` הוא `abc`, ‏`0` או `-1` | מדולג. שאר הפריטים נקלטים | — |
| מוצר קיים, בשם אחר | אותו ברקוד מרשת אחרת | אותו product_id. השם לא משתנה | — |
| סניף לא ידוע | ‏StoreID שאין לו שורה | הקובץ `failed` עם `unknown store`, ושאר הקבצים ממשיכים | הקובץ ייקלט שוב בריצה הבאה |
| ‏2 ב-20 | ‏RewardType 10, ‏MinQty 2, ‏DiscountedPrice 20.00, ‏ClubID `0` | ‏`multi_buy`, ‏min_qty 2, ‏bundle 2000, ‏club_id null | — |
| מחיר קבוע למועדון | ‏RewardType 3, ‏DiscountedPrice 24.90, ‏ClubID `(2=מועדון קרפור אשראי\|2=מועדון אפליקציה)` | ‏`fixed_price`, ‏2490, ‏club_id = המועדון של הרשת | — |
| ‏ClubID מוזר | ‏`(0=מועדון קרפור אשראי\|0=מועדון אפליקציה)`, או ריק | נשמר כמבצע מועדון | — |
| כלל הלקוחות | ‏`0 - כלל הלקוחות` | ‏club_id null | — |
| אחוז הנחה | ‏RewardType 2, ‏DiscountRate 5 | ‏`percent`, ‏percent 5 | — |
| קופון | ‏`AdditionalIsCoupon=1` | לא נשמר | — |
| פג תוקף | ‏`PromotionEndDateTime` שכבר עבר | לא נשמר | — |
| נעלם מהקובץ | מבצע פעיל של הסניף שלא מופיע ב-PromoFull החדש | ‏`ends_at` = זמן הריצה. ‏`active_promotions` לא מחזירה אותו | — |
| זמן מקומי | ‏`2026-11-01T00:00:00.000` | ‏`starts_at` = ‏`2026-10-31T22:00:00Z` (שעון חורף, UTC+2) | — |
| בלי מוצר מוכר | כל ה-PromotionItems בלי מוצר במאגר | לא נשמר | — |

</intent-contract>

## Code Map

- `backend/app/modules/ingestion/service.py` -- ‏`DEFAULT_HANDLERS` ו-`handlers_with_geocoder(geocoder)` (3.3). כאן מחליפים את `count_handler("Item")` ואת `count_handler("Promotion")` ב-handlers האמיתיים. ‏`_run`: מוסיפים את `refresh_current_prices` אחרי `finish_run`, ב-session משלו.
- `backend/app/modules/ingestion/stores.py` -- הדפוס לכתיבת handler: `_fields` ו-`local_name`, ה-closure, והלוג `ingestion_stores`.
- `backend/app/modules/ingestion/decode.py` -- `local_name`.
- `backend/app/modules/catalog/{models,repository,service}.py` -- ‏`Store`, ‏`Club`, ‏`ensure_club` (repository), ‏`normalize_he`, ‏`upsert_store`. מוסיפים כאן את `Product`, ‏`ensure_products_by_barcode` (bulk), ‏`product_ids_by_barcode`, ‏`store_id_by_code` ו-`ensure_chain_club`.
- `backend/app/modules/pricing/{models,repository,service}.py` -- היום stubs ריקים. כאן נכנסים התצפיות, המבצעים, `current_prices`, ‏`active_promotions` ו-`refresh_current_prices`.
- `backend/app/core/money.py` -- לבדוק אם כבר יש בו המרה משקלים לאגורות, ולהשתמש בה.
- `backend/migrations/versions/0008_stores.py` -- המיגרציה האחרונה. החדשה היא `0009`. ‏`pg_trgm` כבר מותקן (`0001`). ה-MV נוצר ב-SQL גולמי.
- `backend/tests/integration/test_ingestion.py`, ‏`test_stores.py` -- ‏`FakeAdapter`, fixtures ו-TRUNCATE. מוסיפים ל-TRUNCATE את הטבלאות החדשות, גם ב-`test_clubs`, ‏`test_brands` ו-`test_delete_account`.
- `backend/tests/fixtures/ingestion/{price_full.xml,promo_full.xml}` -- fixtures בדויים מ-3.2. אפשר להרחיב אותם.
- `backend/pyproject.toml` -- להוסיף `tzdata` ולהריץ `uv lock`. שגיאת תעודה (NetFree): עוצרים ומדווחים.

## Tasks & Acceptance

**Execution:**
- `backend/pyproject.toml`, `backend/uv.lock` -- תלות `tzdata`.
- `backend/app/modules/catalog/{models,repository,service}.py` -- ‏`Product`, ‏`ensure_products_by_barcode(session, items) -> dict[barcode, id]`, ‏`product_ids_by_barcode`, ‏`store_id_by_code` ו-`ensure_chain_club`.
- `backend/app/modules/pricing/{models,repository,service}.py` -- ‏`PriceObservation`, ‏`Promotion` ו-`PromotionProduct`. הפונקציות: `record_official_prices(session, store_id, chain_id, prices, source_ref, at) -> (new, unchanged)`, ‏`replace_store_promotions(session, store_id, chain_id, promos, at) -> saved`, ‏`active_promotions` ו-`refresh_current_prices`.
- `backend/migrations/versions/0009_products_prices.py` -- הטבלאות, האינדקסים, ה-CHECKs וה-MV, וגם downgrade.
- `backend/app/modules/ingestion/prices.py` (חדש) -- ‏`parse_price_file`, ‏`parse_promo_file`, ‏`club_is_everyone`, ‏`local_to_utc`, ‏`price_handler` ו-`promo_handler`.
- `backend/app/modules/ingestion/service.py` -- ה-handlers החדשים, והריענון בסוף הריצה.
- `backend/tests/unit/test_ingestion_prices.py` -- פענוח, אגורות, יחידות, מועדון, סוג מבצע וזמנים.
- `backend/tests/integration/test_prices.py` -- כל שורות המטריצה מול Postgres, כולל `current_prices` ו-`active_promotions`.
- `backend/tests/integration/{test_clubs,test_brands,test_delete_account,test_ingestion,test_stores}.py` -- הוספה ל-TRUNCATE.
- `deploy/README.md` -- סעיף קצר: מה נקלט ומה מדולג (פריט פנימי, קופון).

**Acceptance Criteria:**
- Given ריצה שקלטה Stores, ‏PriceFull ו-PromoFull של סניף, when הריצה מסתיימת, then ל-`current_prices` יש מחיר `regular` לכל פריט עם ברקוד, ו-`active_promotions` מחזירה את המבצעים התקפים של הסניף, עם הכמות, המחיר והמועדון שלהם.
- Given מבצע ש-`ends_at` שלו עבר, when שואלים את `active_promotions` בזמן מאוחר יותר, then הוא לא מוחזר.

## Spec Change Log

## Review Triage Log

### 2026-11-03 — Review pass
- verdicts: 36 findings — high 0, medium 5, low 23, false 8, maybe-false 0
- findings:
  - Intent Alignment:
    - `false` `reject` ‏AC4 נבדק ב-`active_promotions` ולא ב-effective_price — המחיר האפקטיבי שייך ל-Epic 5. ‏`active_promotions` היא נקודת הכניסה שלו, ומבצע שפג לא חוזר ממנה.
    - `false` `reject` ‏(1b) לא נכתבת תצפית לכל פריט בכל קובץ — AD-3 ו-epic-context קובעים "רק כשהמחיר שונה".
    - `low` `reject` ‏(1c) פריטים בלי ברקוד לא מקבלים תצפית — הם הועברו במפורש ל-3.6 ול-Epic 4.
    - `low` `reject` ‏(2b) מחיר מועדון לא נשמר כתצפית `club` — הארכיטקטורה מגדירה טבלת `promotions` עם `club_id` (FR-15, ‏EC-3), ו-Epic 5 גוזר ממנה.
    - `low` `reject` ‏(2c) לא כל מבצע נשמר — הדילוגים שמרניים (קופון, פג תוקף, בלי מוצר), כדי לא להציג מחיר שאולי לא זמין.
    - `low` `patch` ‏(3b) המועדונים של רשת מתמזגים — נכתב במפורש ב-README שזו החלטה ל-MVP.
    - `false` `reject` הכל נבדק רק בשכבת האחסון — זה ההיקף של Story קליטה. בנוסף, הורצה בדיקה חיה של הפרסרים מול קבצים אמיתיים של קרפור ושופרסל.
  - Verification Gap:
    - `low` `patch` עדכון של מבצע קיים לא נבדק — `test_a_promotion_saved_again_with_other_terms`.
    - `low` `patch` ‏`bad_dates` לא נבדק — נוסף ל-`test_promotions_that_are_not_saved`.
    - `low` `patch` ‏`count_handler` לא בשימוש — נמחק.
    - `low` `reject` מבצע שהיה שמור ועכשיו דולג נסגר, ואין לזה בדיקה — זו ההתנהגות של "תמונה מלאה" שה-spec קובע, וה-README מתעד אותה.
  - Blind Hunter:
    - `medium` `defer` מוצר שירד מ-PriceFull נשאר — נרשם ב-deferred (Epic 7 או Epic 5).
    - `medium` `defer` אין "אומת לאחרונה" — נרשם ב-deferred, ומופיע ב-Design Notes.
    - `medium` `patch` הפרס של הפריט הראשון חל על כל המבצע — נבדק בקבצים אמיתיים: 10 מתוך 1,595 בקרפור, ו-39 מתוך 1,022 בשופרסל. עכשיו במבצע `percent` אין bundle, ופריטים עם פרס אחר נשמטים ונספרים כ-`mixed_reward_items`.
    - `medium` `patch` קובץ PriceFull שנכשל מסיים את כל המבצעים — קובץ PromoFull בלי אף מוצר מוכר נכשל, עובר rollback, ונקלט שוב.
    - `false` `reject` אין הבטחה לסדר הקבצים — `latest_per_store` ממיין לפי `FILE_KINDS`: ‏stores, ‏price_full, ‏promo_full.
    - `false` `reject` ‏SubChainID — נבדק ב-3.3: אין StoreID כפול בין SubChains באף רשת.
    - `low` `reject` ‏ChainID שבקובץ לא נבדק — ה-adapter כבר מסנן לפי קוד הרשת שבשם הקובץ (3.2).
    - `low` `patch` ריענון בכל ריצה — עכשיו רק כשנקלט קובץ.
    - `low` `patch` חסר אינדקס על `promotion_products(product_id)` — נוסף.
    - `low` `reject` הנחות על מבנה הקבצים — הורצה בדיקה חיה: ‏PriceFull של קרפור (10,926 פריטים, 408 במשקל), ו-PromoFull של קרפור ושופרסל (multi_buy, ‏fixed_price, ‏percent).
    - `low` `patch` מיזוג המועדונים לא מוסבר — הוסבר ב-README.
    - `low` `reject` מבצעים שנזרקים בשקט ב-`replace_store_promotions` — ה-handler כבר מסנן מבצע בלי מוצרים ומבצע כפול, ואלה נספרים.
    - `low` `reject` אין בדיקות למקביליות ולשוויון של UUIDv7 — שתי רשתות עם אותו ברקוד מקבלות מוצר אחד, דרך ON CONFLICT. המונוטוניות של UUIDv7 בתוך אותה אלפית שנייה נבדקת ב-core.
    - `false` `reject` ה-spec לא בתוך ה-diff — הוא הוצא בכוונה. סקירת ה-Edge Case קוראת אותו כ-claims.
  - Edge Case Hunter:
    - `low` `patch` ‏`1e30` מכשיל את הקובץ — `ArithmeticError` נתפס.
    - `low` `patch` זמן קיצוני מכשיל את הקובץ — ‏`OverflowError` נתפס.
    - `false` `reject` תאריך בפורמט DD/MM — בקבצים של שלוש הרשתות הזמנים בפורמט ISO (`2026-11-01T00:00:00.000`).
    - `low` `reject` ‏EndDate בלי שעה — הרשתות משתמשות ב-`...DateTime`, וזה רק fallback.
    - `false` `reject` ‏PromotionItems > Item — בקבצים האמיתיים של שלוש הרשתות זה `PromotionItem`.
    - `low` `reject` ‏PromotionItem בלי ItemType — בקבצים האמיתיים יש תמיד ItemType.
    - `low` `patch` אחוז עם MinQty גדול מ-1 — ענף ה-percent נבדק ראשון.
    - `medium` `patch` ‏PromoFull בלי מוצרים נרשם כהצלחה — אותו תיקון (ValueError ו-rollback).
    - `low` `patch` ברקוד של אפסים — נחשב "בלי ברקוד".
    - `low` `patch` ‏`count_handler` — נמחק.
    - `low` `patch` רשימת הדילוגים ב-README חלקית — הושלמה.

## Design Notes

**ההחלטה על מוצרים מ-3.6:** תצפית צריכה `product_id`, ולכן ההתאמה לפי ברקוד (AC הראשון של 3.6: "מוצר עם ברקוד מותאם לאותו ברקוד, ואם אין, נוצר מוצר") נעשית כבר כאן. ב-3.6 נשאר המסלול של פריט בלי ברקוד, דרך `matching.service` (Epic 4).

**רעננות בלי UPDATE:** כשהמחיר לא השתנה לא נכתבת תצפית. לכן `observed_at` של המחיר הנוכחי יכול להיות ישן, גם כשהמחיר אומת עכשיו. את הגיל של המחיר (Epic 7) מחשבים לפי הקובץ האחרון של הסניף שנקלט בהצלחה (`ingestion_files`), ולא לפי `observed_at`. זה נרשם כאן כדי ש-Epic 7 יידע.

**נפח:** קליטה ראשונה היא בערך 10 אלפים פריטים לסניף, כפול כ-670 סניפים, כלומר כמה מיליוני שורות. לכן הכתיבה היא bulk ‏(`executemany` / ‏`insert().values([...])` בקבוצות), וההשוואה מול המחיר הקודם היא שאילתה אחת לקובץ ‏(`DISTINCT ON (product_id)`). חלוקה למחיצות לפי חודש נדחית: אפשר להוסיף אותה בלי לשנות את הקוד שקורא מה-view.

## Verification

**Commands:**
- `cd backend && uv lock && uv sync` -- expected: `tzdata` נוסף. שגיאת תעודה: עוצרים ומדווחים, בלי לעקוף.
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy` -- expected: נקי.
- `cd backend && CARTWISE_REQUIRE_DOCKER=1 uv run pytest` -- expected: הכל עובר, כולל roundtrip של המיגרציות.

## Auto Run Result

Status: done

**סיכום:**
- **PriceFull:** כל פריט עם ברקוד יוצר מוצר לפי ברקוד, אם הוא לא קיים. אחר כך נכתבת תצפית `regular` באגורות, append-only, ורק כשהמחיר השתנה.
- **PromoFull:**
  - הוא תמונה מלאה של הסניף. מבצעים נשמרים עם תוקף (מקומי ← UTC), תנאי כמות (`multi_buy`, ‏`fixed_price`, ‏`percent`) ושיוך שמרני למועדון של הרשת.
  - קופונים, מבצעים שפג תוקפם ומבצעים בלי מוצר מוכר לא נשמרים. מבצע שנעלם מהקובץ נסגר.
- **אחרי ריצה שקלטה קובץ:** `current_prices` מתרענן.
- **מבצעים תקפים:** `active_promotions` מחזירה רק אותם.

**קבצים:**
- `backend/app/modules/catalog/*` -- `Product`, ‏`ensure_products_by_barcode`, ‏`store_id_by_code` ו-`ensure_chain_club`.
- `backend/app/modules/pricing/*`, `backend/migrations/versions/0009_products_prices.py` -- תצפיות, מבצעים, `current_prices` (MV) ו-`active_promotions`.
- `backend/app/modules/ingestion/prices.py` -- הפרסרים וה-handlers.
- `backend/app/modules/ingestion/{service,decode,stores}.py` -- החיבור, הריענון, ו-helpers משותפים.
- `backend/pyproject.toml`, `backend/uv.lock` -- `tzdata`.
- `backend/tests/...` -- fixtures בדויים במבנה האמיתי, והמטריצה כולה.
- `deploy/README.md` -- מה נקלט ומה מדולג.

**ממצאי הסקירה:** 36 ממצאים:
- **תוקנו:** 2 entries ברמת medium (פרס מעורב במבצע, ו-PromoFull בלי מוצרים), ו-13 ברמת low.
- **נדחו ל-deferred:** 2 (מוצר שירד מהמדף, ואישור אחרון של מחיר).
- **נדחו לגמרי:** השאר. הנימוק של כל אחד רשום ב-Review Triage Log.

**המלצה לסקירת המשך:** `true`. תוקנו 2 entries ברמת medium. הסיכון שלא אומת: קליטה מלאה בנפח אמיתי, כמה מיליוני תצפיות, וזמן הריענון של ה-MV.

**אימות:**
- ruff, format ו-mypy נקיים.
- `CARTWISE_REQUIRE_DOCKER=1 pytest`: 702 עברו.
- gitleaks על הקבצים שהשתנו: `no leaks found`.
- **בדיקה חיה של הפרסרים מול קבצים אמיתיים, בלי DB:**
  - **PriceFull של קרפור:** 10,926 פריטים, 212 בלי ברקוד, 408 במשקל.
  - **PromoFull של קרפור:** 594 ‏multi_buy, ‏942 ‏fixed_price ו-16 ‏percent.
  - **PromoFull של שופרסל:** 626, ‏314 ו-5.
  - הכלל השמרני למועדון נבדק על כל הערכים האמיתיים.

**סיכונים שנשארו:**
- נפח וביצועים בקליטה ראשונה.
- המועדונים של רשת מאוחדים.
- מוצר שירד מהמדף, וגיל המחיר (deferred).
