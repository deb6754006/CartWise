---
title: 'Story 3.3: סניפים ומיקומים מקובצי Stores'
type: 'feature'
created: '2026-11-03'
status: 'done'
baseline_revision: '33056baffd9289c21b388ab3e5cbdb1d830b4b9a'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/docs/implementation-artifacts/epic-3-context.md'
  - '{project-root}/docs/implementation-artifacts/spec-3-2-scheduled-ingestion.md'
warnings: ['oversized']
deferred:
  - summary: >-
      סניף שנסגר, ולכן נעלם מקובץ ה-Stores, נשאר active ונכנס להשוואות לתמיד.
    evidence: |-
      ‏`last_seen_at` נכתב, אבל אף אחד לא קורא אותו. ה-spec קבע לא לשנות status לסניף שלא מופיע בקובץ. כדי להכריע: ב-Epic 5 (סינון סניפים) או ב-3.5, להוציא מההשוואות סניף ש-`last_seen_at` שלו ישן יותר מקובץ ה-Stores האחרון שנקלט לרשת.
    location: >-
      backend/app/modules/catalog/repository.py (comparable_store_ids)
    severity: medium
---

<intent-contract>

## Intent

**Problem:** הקליטה של Story 3.2 רק סופרת את הסניפים בקובצי Stores. אין טבלת `stores`, ואין לסניפים מיקום. בלי מיקום אי אפשר לסנן לפי טווח (Epic 5), ובלי סניפים אי אפשר לשייך מחירים (3.4).

**Approach:**
- ה-handler של `stores` ב-ingestion מפרסר את הקובץ לרשומות, ומעביר אותן ל-`catalog.service`. שם הסניפים נוצרים או מתעדכנים לפי `(chain_id, gov_store_code)`.
- סניף פיזי בלי מיקום, או שהכתובת שלו השתנתה, מקבל מיקום דרך ה-Geocoder הקיים (Nominatim), לפי "כתובת, שם יישוב".
- את שם היישוב לוקחים מקוד היישוב של הלמ"ס, מקובץ נתונים פתוח שנשמר בריפו.
- סניף שלא נמצא לו מיקום מקבל `status='needs_location'`. הוא לא נכנס להשוואות, ומופיע ברשימת חריגים. מפעיל יכול להזין לו מיקום ידנית, עם פקודת CLI.

## Boundaries & Constraints

**Always:**
- **בעלות על הטבלה:** הטבלה `stores` שייכת ל-catalog (AD-2). ingestion לא נוגע בה ישירות, רק דרך `catalog.service`. גם ה-geocoding נעשה דרך `geo.service` (`Geocoder`, ‏`NominatimGeocoder`), ולא דרך קוד HTTP חדש.
- **מבנה הקובץ (אומת ב-2026-11-03 בקבצים של שלוש הרשתות):** `Root|Chain > SubChains > SubChain(SubChainID) > Stores > Store`. בתוך כל `Store` יש `StoreID`, ‏`StoreType`, ‏`StoreName`, ‏`Address`, ‏`City` (קוד יישוב מספרי, ולפעמים ריק) ו-`ZIPCode`. שמות התגים מושווים לפי local name, בלי תלות באותיות גדולות, כמו ב-`decode.count_elements`.
- **מפתח הסניף:** `gov_store_code` הוא `StoreID` בלי אפסים מובילים. למשל `"001"` הופך ל-`"1"`, ו-`"000"` הופך ל-`"0"`. בטבלה יש unique על `(chain_id, gov_store_code)`. `SubChainID` נשמר כ-`sub_chain_code`.
- **עמודות `stores`:**
  - ‏id (UUIDv7), ‏chain_id FK, ‏gov_store_code, ‏sub_chain_code, ‏name, ‏name_norm (דרך `normalize_he`), ‏address, ‏city_code null, ‏zip_code null, ‏store_type smallint null.
  - ‏`location geography(Point,4326)` null, ‏`location_source` null, עם הערכים `geocoded` או `manual`.
  - ‏`geocoded_query` null: המחרוזת שנשלחה ל-geocoder, כדי לדעת שהכתובת השתנתה.
  - ‏`geocode_attempted_at` null.
  - ‏`status`: ‏`active`, ‏`needs_location` או `online`.
  - ‏`last_seen_at`, ‏`created_at`, ‏`updated_at` (timestamptz UTC).
- **רשומה לא תקינה:** רשומה בלי `StoreID` ספרתי, או בלי `StoreName`, מדולגת. היא לא מכשילה את הקובץ, ומספר הרשומות שדולגו נרשם בלוג. ה-handler מחזיר את מספר הסניפים שנקלטו.
- **סוג סניף:** `StoreType=2` הוא סניף אינטרנטי. הוא מקבל `status='online'`, לא עובר geocoding, ולא נכנס להשוואות. כל סוג אחר, או סוג חסר, הוא סניף פיזי.
- **מתי מבצעים geocoding לסניף פיזי:**
  - לסניף אין מיקום, או שהמחרוזת `query` שלו שונה מ-`geocoded_query`.
  - **וגם** `location_source` שונה מ-`manual`. מיקום ידני לא נדרס לעולם, גם אם הכתובת השתנתה.
  - **וגם** אין ניסיון כושל ב-24 השעות האחרונות לאותה `query`.
- **מחרוזת ה-query:**
  - `"<Address>, <שם היישוב>"`, כששם היישוב מגיע מ-`settlements.csv` לפי `City`.
  - אם הקוד לא נמצא בקובץ, או ש-`City` ריק: `"<Address>"` בלבד.
  - כש-`City` אינו מספר, משתמשים בו עצמו כשם היישוב.
  - הטקסט עובר `NFC`, ורווחים כפולים מצטמצמים.
- **תוצאה של geocoding:**
  - **נמצא מיקום:** `location` מתעדכן, `location_source='geocoded'`, `geocoded_query=query`, `status='active'`.
  - **לא נמצא (None):** `status='needs_location'` ו-`geocode_attempted_at=now`. אם יש לסניף מיקום ישן מ-geocoding, הוא נשאר, וה-status נשאר `active`.
  - **שגיאת geocoder (AppError 503):** כמו "לא נמצא". הקובץ **לא** נכשל.
- **תקרה:** לכל היותר `MAX_GEOCODES_PER_FILE=1000` בקשות לקובץ. סניף שלא הגיע תורו נשאר כמו שהוא: חדש בלי מיקום מקבל `needs_location`, וינוסה בריצה הבאה.
- **שם וכתובת מתעדכנים בכל קליטה.** `last_seen_at=now`. סניף שלא מופיע בקובץ האחרון לא נמחק, ולא משנה status.
- **`settlements.csv`:**
  - המיקום: `backend/app/modules/catalog/data/settlements.csv`. עמודות `code,name`, ‏UTF-8, ‏1,316 שורות.
  - המקור: מאגר "יישובים בישראל" של רשות האוכלוסין, ב-data.gov.il (`resource_id=5c78e9fa-c2e2-4771-93ff-7f400a12f7ba`, רישיון Other (Open)). הקובץ מוכן ב-scratchpad: `C:\Users\User\AppData\Local\Temp\claude\c--Users-User-Desktop-practicum-CartWise\0cb0b662-18fc-4979-90e0-e7426273d05f\scratchpad\cbs\settlements.csv`. מעתיקים אותו כמו שהוא.
  - הייחוס נכתב ב-`deploy/README.md`, בסעיף הקליטה.
- **רשימת חריגים ומיקום ידני:**
  - `catalog.service.stores_needing_location(session) -> list[StoreRef]`.
  - `catalog.service.set_store_location_manual(session, store_id, lat, lng)`: בודקת שהערכים בטווח. מגדירה `location_source='manual'` ו-`status='active'`.
  - הסקריפט `backend/scripts/store_locations.py` עם שתי פקודות: `list` (רשימת החריגים) ו-`set <store_id> <lat> <lng>`.
- **מה נכנס להשוואות:** `catalog.service.comparable_store_ids(session, chain_id=None)` מחזירה רק סניפים עם `status='active'` ו-`location IS NOT NULL`. זו נקודת הכניסה של Epic 5.
- **סוג העמודה:** בלי תלות חדשה, כלומר בלי geoalchemy2. משתמשים ב-`UserDefinedType` קטן ל-`geography(Point,4326)`. הכתיבה דרך `ST_SetSRID(ST_MakePoint(lng, lat), 4326)::geography`, והקריאה דרך `ST_Y` ו-`ST_X` על `::geometry`. יש אינדקס GIST על `location`.
- **מיגרציה:** `0008`.

**Never:**
- לא לכתוב מחירים, מבצעים או מוצרים (3.4 ו-3.6). לא להוסיף endpoint ל-API.
- לא לבצע HTTP אמיתי בבדיקות. ה-Geocoder מוזרק ל-handler. בבדיקות זה fake.
- לא לרשום כתובות של סניפים בלוג. אמנם הן לא מידע אישי, אבל `geo.service` כבר נמנע מזה, ונשמרת עקביות.
- לא לשנות `ingest_chain`, הנעילה או היומן של Story 3.2, מלבד החלפת ה-handler של `stores`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| סניף חדש עם מיקום | ‏Store עם StoreID `001`, ‏City `3000`. ה-geocoder מחזיר נקודה | שורה עם gov_store_code `1`, ‏status `active` ו-location. query: `"<Address>, ירושלים"` | — |
| סניף חדש בלי מיקום | ה-geocoder מחזיר None | ‏status `needs_location`. הסניף מופיע ב-`stores_needing_location`, ולא ב-`comparable_store_ids` | — |
| geocoder לא זמין | ה-geocoder זורק AppError 503 | כמו None. הקובץ `succeeded` | — |
| קליטה חוזרת, אותה כתובת | סניף `active` עם אותו query | שם ו-last_seen_at מתעדכנים. אין קריאה ל-geocoder | — |
| הכתובת השתנתה | אותו StoreID, ‏Address אחר | נשלחת קריאה חדשה ל-geocoder, ו-location מתעדכן | — |
| מיקום ידני | ‏location_source `manual`, והכתובת השתנתה | אין קריאה ל-geocoder. המיקום נשמר | — |
| ניסיון כושל לאחרונה | ‏`needs_location`, עם ניסיון לפני שעה לאותו query | אין קריאה ל-geocoder | — |
| ניסיון כושל ישן | אותו מצב, עם ניסיון לפני יותר מ-24 שעות | נשלחת קריאה חדשה ל-geocoder | — |
| סניף אינטרנטי | ‏StoreType `2` | ‏status `online`. אין קריאה ל-geocoder, ולא נכנס להשוואות | — |
| קוד יישוב לא ידוע או ריק | ‏City `99999` או `""` | query הוא `"<Address>"` בלבד | — |
| רשומה פגומה | Store בלי StoreID, או עם StoreID לא ספרתי | מדולגת. שאר הרשומות נקלטות. ה-handler מחזיר את מספר הסניפים שנקלטו | — |
| תקרת geocoding | ‏N+1 סניפים חדשים, תקרה N (בבדיקה) | ‏N קריאות. הסניף האחרון `needs_location`, בלי `geocode_attempted_at` | — |
| UTF-16, תגים באותיות גדולות | ‏fixture בדוי, עם `<STORE>` ו-`<STOREID>` | נקלט כרגיל | — |
| מיקום ידני ב-CLI | ‏`set <id> 31.77 35.21` | ‏`manual`, ‏`active`, ונכנס להשוואות. מחוץ לטווח: שגיאה, בלי שינוי | ‏ValueError |

</intent-contract>

## Code Map

- `backend/app/modules/ingestion/service.py` -- `DEFAULT_HANDLERS["stores"]` הוא היום `count_handler("Store")`. מחליפים אותו ב-handler שבונה את הרשומות וקורא ל-catalog. החתימה של `Handler` היא `(session, chain_id, root) -> int`. ה-Geocoder מגיע דרך closure, או `functools.partial`, שנבנה ב-`DEFAULT_HANDLERS` או ב-job.
- `backend/app/worker/jobs/ingest_chain.py` -- `run()` קורא ל-`ingest_chain(session_factory, adapter)`. כאן אפשר להעביר handlers עם ה-geocoder האמיתי (`geo.service._geocoder_for(settings.NOMINATIM_URL)`, או פונקציה ציבורית חדשה ב-geo.service שמחזירה אותו).
- `backend/app/modules/ingestion/decode.py` -- `_local_name`, ו-`count_elements` שמשווה בלי תלות באותיות. משתמשים באותה השוואה לשמות התגים של Store.
- `backend/app/modules/geo/service.py:66-142` -- `Geocoder`, ‏`NominatimGeocoder.locate(address) -> GeoPoint | None`, שזורק `AppError` 503. גם `RequestSpacer`: בקשה אחת לשנייה, ועד 3 שניות המתנה. בלולאה סדרתית זה מספיק. `get_geocoder` (שורה 157) הוא תלות של FastAPI, אז ב-worker צריך פונקציה שלא דורשת Depends.
- `backend/app/modules/catalog/{models,repository,service}.py` -- `Chain`, ‏`Club`, ‏`Brand`, ‏`normalize_he` (שורה 47) ו-`ensure_chain` (Story 3.2). כאן נוספים `Store` והפונקציות החדשות.
- `backend/migrations/versions/0007_ingestion.py` -- המיגרציה האחרונה, והדפוס לפיו כותבים מיגרציה. PostGIS כבר מותקן ב-`0001_extensions.py`.
- `backend/tests/integration/test_ingestion.py` -- `FakeAdapter` ו-fixtures. ‏`test_clubs.py`, ‏`test_brands.py` ו-`test_delete_account.py` עושים TRUNCATE ל-`chains`, וצריך להוסיף להם את `stores`.
- `backend/tests/fixtures/ingestion/stores.utf16.xml` -- ה-fixture הבדוי הקיים (Story 3.2). אפשר להרחיב אותו או להוסיף fixture.
- `deploy/README.md` -- סעיף הקליטה: הייחוס ל-data.gov.il ופקודות `store_locations`.

## Tasks & Acceptance

**Execution:**
- `backend/app/modules/catalog/data/settlements.csv` -- העתקה מה-scratchpad -- המיפוי מקוד יישוב לשם, מנתונים פתוחים.
- `backend/app/modules/catalog/models.py` + `backend/migrations/versions/0008_stores.py`:
  - `Store`, עם הטיפוס `Geography`.
  - unique על `(chain_id, gov_store_code)`, ‏GIST על `location`, ו-CHECK על `status` ועל `location_source`.
- `backend/app/modules/catalog/{repository,service}.py`:
  - `StoreRecord` ו-`upsert_store`, שמחזירה את מצב הסניף לפני ואחרי.
  - `set_store_geocode_result`, ‏`stores_needing_location`, ‏`set_store_location_manual` ו-`comparable_store_ids`.
  - `settlement_name(code)` (טעינה עצלה של ה-CSV) ו-`store_geocode_query(record)`.
- `backend/app/modules/geo/service.py` -- `default_geocoder(settings) -> Geocoder` בלי Depends. `get_geocoder` משתמש בה.
- `backend/app/modules/ingestion/stores.py` (חדש) -- `parse_stores(root) -> (records, skipped)` ו-`stores_handler(geocoder, now, max_geocodes)`: מחליטים מי עובר geocoding, קוראים לו, ושומרים את התוצאה.
- `backend/app/modules/ingestion/service.py` + `backend/app/worker/jobs/ingest_chain.py` -- ה-handler של `stores` עם geocoder אמיתי. ב-`DEFAULT_HANDLERS` של הבדיקות אין HTTP.
- `backend/scripts/store_locations.py` -- ‏`list` ו-`set`. מסרב לרוץ בלי DB.
- `backend/tests/unit/test_ingestion_stores.py` -- `parse_stores`, ה-query ושם היישוב.
- `backend/tests/integration/test_stores.py` -- כל שורות המטריצה, מול Postgres אמיתי, עם geocoder מזויף.
- `backend/tests/integration/{test_clubs,test_brands,test_delete_account}.py` -- להוסיף `stores` ל-TRUNCATE.
- `deploy/README.md` -- ייחוס, ופקודות למפעיל.

**Acceptance Criteria:**
- Given קובץ Stores שנקלט, when הריצה מסתיימת, then בטבלה `stores` יש שורה לכל סניף, עם שם, כתובת, ומיקום לכל סניף שה-geocoder מצא לו מיקום.
- Given סניף פיזי שה-geocoder לא מצא לו מיקום, when מבקשים את הסניפים שנכנסים להשוואה, then הוא לא שם. הוא מופיע ב-`stores_needing_location`, ומפעיל יכול לקבוע לו מיקום ידני שנשמר.

## Spec Change Log

## Review Triage Log

### 2026-11-03 — Review pass
- verdicts: 44 findings — high 0, medium 8, low 27, false 9, maybe-false 0
- findings:
  - Verification Gap:
    - `low` `patch` ה-geocoder של ברירת המחדל של ה-job לא נבדק — `test_the_job_uses_the_worker_geocoder_by_default`, עם monkeypatch.
    - `low` `patch` ‏StoreType גדול מ-32767 מכשיל את הקובץ — ערך מחוץ לטווח נשמר כ-None.
    - `low` `reject` טרנזקציה ארוכה לקובץ Stores — ההחלטה מתועדת ב-Design Notes. כשל מאוחר אפשרי רק עם AppError שאינו 503, וזה נדיר.
    - `low` `patch` מיקום ידני הופך סניף online לפעיל — ValueError, והשורה לא משתנה.
    - `false` `reject` סניפים שנדחו מחכים לקובץ אחר — שמות קובצי ה-Stores כוללים תאריך ומשתנים כל יום (נבדק: ‎`-20261101-`‎, ‎`-20261103-`‎). לכן יש ניסיון חוזר תוך יום.
  - Edge Case Hunter:
    - `false` `reject` דילוג לפי hash מונע ניסיון חוזר — אותו נימוק: שם חדש בכל יום.
    - `medium` `patch` שגיאת 503 חוסמת ל-24 שעות, והבקשות ממשיכות — אחרי 503 הקובץ מפסיק לשלוח בקשות. שאר הסניפים נדחים בלי `geocode_attempted_at`, ונוסף `geocode_unavailable` ללוג.
    - `medium` `patch` ‏spacer משותף לרשתות במקביל — `worker_geocoder` עם `max_wait=None`.
    - `low` `reject` טרנזקציה ארוכה — אותו נימוק.
    - `low` `patch` ‏StoreType — אותו תיקון.
    - `false` `reject` אותו StoreID בשני SubChains — נבדק בקבצים האמיתיים: בשופרסל 11 SubChains, ואין בשום רשת StoreID כפול.
    - `low` `reject` כתובת שהתרוקנה משאירה מיקום ישן — לא נצפה בקבצים, והתיקון מוסיף ענף.
    - `low` `patch` מיקום ידני לסניף online — אותו תיקון.
    - `medium` `defer` סניף שנסגר נשאר בהשוואות — נרשם ב-deferred (Epic 5 או 3.5).
    - `low` `reject` ‏City כמו "3000.0" — בקבצים האמיתיים ‏City הוא ספרות או ריק.
    - `low` `reject` טאב בשם הרשת שובר את ה-TSV — שמות הרשתות קבועים בקוד.
    - `false` `reject` (claim) הסניפים שנדחו ייקלטו "בריצה הבאה" — שם הקובץ משתנה כל יום, אז זה קורה.
    - `false` `reject` (claim) לא לכל סניף יש שורה — אין קודים כפולים בקבצים. רשומה פגומה מדולגת, כפי שה-spec קובע.
  - Blind Hunter:
    - `medium` `patch` ‏503 הופך לחסימה של 24 שעות — אותו תיקון.
    - `medium` `patch` אין עצירה כש-Nominatim נופל — אותו תיקון.
    - `low` `reject` טרנזקציה ארוכה — אותו נימוק.
    - `medium` `patch` ‏spacer משותף — אותו תיקון.
    - `low` `reject` הקצב הכולל של ה-API וה-worker — ה-API שולח בקשות רק כשמשתמש מזין כתובת, וזה נדיר.
    - `medium` `patch` חסר ייחוס ל-OpenStreetMap ‏(ODbL) — נוסף ב-README. הייחוס בממשק יגיע עם המסכים שמציגים מיקום.
    - `low` `patch` ‏CLI ‏set על סניף online — אותו תיקון.
    - `low` `patch` ‏lat ו-lng הפוכים — נבדקת מסגרת של ישראל (lat 29–33.5, ‏lng 34–36).
    - `low` `reject` אין `unset` למיקום ידני — אפשר לקבוע מיקום ידני חדש, וזה מספיק.
    - `low` `reject` סניף שעבר כתובת שלא נמצאה לא נראה ברשימה — שמירת המיקום הישן היא החלטה של ה-spec (Design Notes).
    - `low` `reject` אין backoff לכתובת שלא נמצאת — זה לכל היותר בקשה אחת ביום לכל סניף כזה.
    - `low` `patch` ‏SELECT מיותר ב-`upsert_store` — נמחק.
    - `false` `reject` ‏StoreID כפול באותו קובץ — אין כפילויות בקבצים האמיתיים.
    - `low` `patch` הלוג לא מראה 503 — `geocode_unavailable`, ורמת warning.
    - `low` `patch` ההערכה ב-README — עכשיו כתוב "עד כ-17 דקות".
    - `low` `patch` בדיקות חסרות (online והחזרה, AppError שאינו 503, ברירת המחדל) — נוספו.
    - `low` `patch` הבדיקה עם `== 1316` שבירה — עכשיו `>= 1300`, ושלושה קודים ידועים דרך `settlement_name`.
    - `false` `reject` ‏settlements.csv לא ב-diff — הוא הוצא מה-diff בכוונה. הקובץ נבנה מ-data.gov.il ונבדק: כותרת `code,name`, ‏1,316 שורות, ורק קוד ושם.
    - `low` `reject` ה-image כולל את `seed_dev_catalog` — הסקריפט מסרב לרוץ ב-prod.
  - Intent Alignment:
    - `false` `reject` (a) CLI במקום ממשק למפעיל — ה-AC דורש רשימת חריגים והזנה ידנית, וה-CLI נותן את שתיהן. אין ממשק ניהול בהיקף.
    - `low` `reject` (b) גם סניף שלא נוסה מופיע ברשימה — אין לו מיקום, ולכן מקומו ברשימה.
    - `false` `reject` (c) אף אחד לא קורא ל-`comparable_store_ids` — היא נקודת הכניסה של Epic 5.
    - `low` `reject` (d) אין בדיקה מול Nominatim אמיתי — הורצה בדיקה חיה ידנית: 5 מתוך 6 כתובות אמיתיות נמצאו, ואחת עברה לרשימת החריגים.
    - `low` `reject` (e) אין עמודת `source (official, user_added)` — היא תידרש ל-FR-31 (סניפים שמשתמשים מוסיפים) ותתווסף שם.
    - `low` `reject` (f) סניף שעבר כתובת ונכשל לא ברשימה — אותו נימוק.
    - `medium` `defer` (g) סניפים שנסגרו — אותו entry.

## Design Notes

**לא דורסים מיקום טוב בכישלון:** אם ה-geocoding של כתובת חדשה נכשל, הסניף שומר את המיקום הקודם, וה-status שלו נשאר `active`. בסניף פיזי, מיקום לא מדויק עדיף על העלמות מההשוואות. הכשל נרשם ב-`geocode_attempted_at`.

**ה-handler רץ בתוך הטרנזקציה של הקובץ (3.2):** קריאות geocoding לא יוצרות כתיבה חיצונית, ולכן rollback של קובץ שנכשל לא משאיר מצב חלקי. ב-geocoding ראשון, כ-663 סניפים, הטרנזקציה עשויה להימשך כ-11 דקות. זה מקובל: אין לה מתחרים, כי הנעילה היא לפי רשת.

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy` -- expected: נקי.
- `cd backend && CARTWISE_REQUIRE_DOCKER=1 uv run pytest` -- expected: הכל עובר. בדיקות ה-roundtrip של המיגרציות הקיימות כוללות את `0008`.

## Auto Run Result

Status: done

**סיכום:** כל קובץ Stores שנקלט יוצר ומעדכן את הטבלה `stores`, עם שם, כתובת, קוד יישוב וסוג סניף.
- **מיקום:** כל סניף פיזי מקבל מיקום מ-Nominatim, לפי "כתובת, שם יישוב". שם היישוב מגיע מ-`settlements.csv`, הקובץ הפתוח של data.gov.il.
- **מתי נשלחת בקשה:** רק לסניף חדש, או לסניף שהכתובת שלו השתנתה. מיקום ידני לא נדרס לעולם. כתובת שלא נמצאה מנוסה שוב רק אחרי 24 שעות.
- **סניף בלי מיקום:** מקבל `needs_location`. הוא לא נכנס ל-`comparable_store_ids`, ומופיע ב-`scripts.store_locations list`. מפעיל יכול לקבוע לו מיקום עם `set`.
- **סניף אינטרנטי:** מסומן `online`.
- **Nominatim לא זמין:** הקובץ מפסיק לשלוח בקשות, ולא נכשל.

**קבצים:**
- `backend/app/modules/catalog/{models,repository,service}.py`, `backend/migrations/versions/0008_stores.py` -- `Store`, `Geography`, ‏upsert, תוצאת geocoding, מיקום ידני, ההשוואות ושם היישוב.
- `backend/app/modules/catalog/data/settlements.csv` -- 1,316 יישובים (data.gov.il, Other (Open)).
- `backend/app/modules/ingestion/stores.py` -- `parse_stores`, ‏`needs_geocode` ו-`stores_handler`.
- `backend/app/modules/ingestion/{service,decode}.py` -- `handlers_with_geocoder`, ו-`local_name` ציבורי.
- `backend/app/modules/geo/service.py` -- `default_geocoder`, ‏`worker_geocoder`, ו-`max_wait` ב-`RequestSpacer`.
- `backend/app/worker/jobs/ingest_chain.py` -- ה-job משתמש ב-`worker_geocoder`.
- `backend/scripts/store_locations.py`, `backend/Dockerfile` -- CLI למפעיל, וההעתקה שלו ל-image.
- `backend/tests/...` -- המטריצה, מקרי קצה ובדיקות של המיגרציה.
- `deploy/README.md` -- פקודות, וייחוס ל-data.gov.il ול-OpenStreetMap.

**ממצאי הסקירה:** 44 ממצאים:
- **תוקנו:** 3 entries ברמת medium (עצירה אחרי 503, ‏spacer ל-worker, ייחוס OSM), ו-9 ברמת low.
- **נדחה ל-deferred:** אחד (סניפים שנסגרו).
- **נדחו לגמרי:** השאר. הנימוק של כל אחד רשום ב-Review Triage Log.

**המלצה לסקירת המשך:** `true`. תוקנו 3 entries ברמת medium. הסיכון שלא אומת: ריצה מלאה של geocoding ראשון, כ-663 סניפים, מול Nominatim, בתוך הטרנזקציה של הקובץ.

**אימות:**
- ruff, format ו-mypy נקיים.
- `CARTWISE_REQUIRE_DOCKER=1 pytest`: 587 עברו.
- gitleaks על הקבצים שהשתנו: `no leaks found`.
- **בדיקה חיה של 6 כתובות אמיתיות מול Nominatim:** 5 נמצאו בעיר הנכונה. "ריינס 6 שכונת קרית משה, ירושלים" לא נמצאה, ותעבור לרשימת החריגים.

**סיכונים שנשארו:**
- geocoding ראשון לוקח עד כ-17 דקות לקובץ.
- סניפים שנסגרו (deferred).
- מיקום ישן נשאר לסניף שעבר כתובת שלא נמצאה.
