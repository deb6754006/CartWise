---
title: 'Story 3.2: קליטה מתוזמנת של קובצי המחירים'
type: 'feature'
created: '2026-11-03'
status: 'done'
baseline_revision: '5c9518d9a054a81ec40384dc545037c08de996e5'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/docs/implementation-artifacts/epic-3-context.md'
  - '{project-root}/docs/implementation-artifacts/research-3-1-chains.md'
warnings: ['oversized']
deferred:
  - summary: >-
      הפענוח מחזיק את כל הקובץ בזיכרון: bytes, ‏str ועץ XML מלא. בקובץ שקרוב לתקרה של 500MB, זה כמה GB.
    evidence: |-
      ב-3.2 זה לא קרה בפועל: הקבצים שנבדקו חיים קטנים בהרבה. אבל ב-3.3 וב-3.4 ה-handlers יעבדו את העץ כולו. כדי להכריע: לעבור ל-iterparse כשכותבים את ה-handlers, או להוריד את התקרה לפי הזיכרון בשרת.
    location: >-
      backend/app/modules/ingestion/decode.py
    severity: medium
  - summary: >-
      אין בדיקה למקרה ש-unlock נכשל, ושה-connection עובר invalidate.
    evidence: |-
      מסלול כשל נדיר, שקשה לייצר מול Postgres אמיתי. בלי invalidate, רשת אחת יכולה להישאר נעולה עד restart. כדי להכריע: להוסיף בדיקה עם monkeypatch ל-repository.unlock, יחד עם הניטור של 3.5.
    location: >-
      backend/app/modules/ingestion/service.py
    severity: low
---

<intent-contract>

## Intent

**Problem:** אין עדיין שום קליטה של קובצי המחירים. Stories 3.3–3.6 צריכות תשתית שמורידה את הקבצים של שופרסל, רמי לוי וקרפור בכל כמה שעות, ומזינה אותם לשלבים הבאים. התשתית צריכה גם לדלג על קבצים שכבר נקלטו, ולרשום ביומן כל ריצה וכל קובץ.

**Approach:** מודול `ingestion` עם adapter משלנו לכל רשת (`list_files()` ו-`fetch(file)`), ושירות שמריץ ריצה אחת לרשת:
1. רשימת הקבצים.
2. בחירת הקובץ האחרון לכל סוג ולכל סניף.
3. הורדה, ו-hash.
4. דילוג על קובץ שכבר נקלט.
5. פענוח (gz, קידוד, XML) והעברה ל-handler לפי סוג הקובץ.
6. רישום ביומן.

ב-Story הזו ה-handler רק סופר רשומות. 3.3 ו-3.4 יחליפו אותו בכתיבה של סניפים, מחירים ומבצעים. ה-worker מתזמן ריצה לכל רשת, לפחות פעם ב-6 שעות.

## Boundaries & Constraints

**Always:**
- **קוד משלנו בלבד:** בלי `il-supermarket-scraper`, ובלי להעתיק ממנה קוד.
- **רק ספריות חינמיות.** אין תלות חדשה ב-Python. משתמשים ב-stdlib: `urllib`, `gzip`, `xml.etree`, `hashlib`.
- **שלושה adapters, עם פרטים שאומתו ב-2026-11-03:**
  - **שופרסל:** `GET https://prices.shufersal.co.il/FileObject/UpdateCategory?catID=<n>&storeId=0&page=<p>`. ערכי `catID`: ‏5 = Stores, ‏2 = PriceFull, ‏4 = PromoFull. בכל עמוד יש עד 20 שורות, ו-PriceFull מגיע לכ-22 עמודים. הקישורים הם `<a href="https://pricesprodpublic.blob.core.windows.net/...">`, עם חתימה זמנית ב-query. שם הקובץ הוא הקטע האחרון של ה-path. ממשיכים לעמוד הבא עד עמוד בלי שורות, ולכל היותר `MAX_PAGES` עמודים.
  - **רמי לוי (Cerberus):**
    - `GET https://url.publishedprices.co.il/login` ← `<meta name="csrftoken" content="...">`.
    - `POST /login/user` עם `r=''`, ‏`username=<settings>`, ‏`password=''` ו-`csrftoken`. מגיעים ל-`/file`, ושם יש csrftoken **חדש**.
    - `POST /file/json/dir` עם `sEcho=1`, ‏`iDisplayStart=0`, ‏`iDisplayLength=100000`, ‏`sSearch=''`, ‏`cd=/` ו-`csrftoken`. מקבלים `{"aaData":[{"fname":..., "size":..., "time":"<ISO>"}...]}`.
    - הורדה: `GET /file/d/<fname>`, עם אותן cookies.
  - **קרפור:** `GET https://prices.carrefour.co.il/`. בדף מוטמעים `const path = 'YYYYMMDD';` ו-`const files = [{"name":...,"size":...,"modified":...}, ...];`. הקובץ נמצא ב-`https://prices.carrefour.co.il/<path>/<name>`.
- **הגדרות ב-`Settings`, עם ברירות מחדל:** כתובות הבסיס של שלושת הפורטלים, ‏`CERBERUS_RAMI_LEVY_USERNAME="RamiLevi"` (ערך ציבורי, לא סוד), ו-`INGEST_INTERVAL_HOURS` (ברירת מחדל 6, ‏`ge=1`, ‏`le=6`).
- **סוגי קבצים ב-MVP:** `stores`, ‏`price_full` ו-`promo_full`. סוג נקבע לפי קידומת שם הקובץ: `Stores`, ‏`PriceFull`, ‏`PromoFull`. קבצים אחרים, כמו `Price` ו-`Promo` חלקיים, לא נבחרים. לכל `(kind, store_code)` נבחר הקובץ עם חותמת הזמן הגבוהה ביותר בשם.
- **זיהוי קובץ לפי AD-14:** `(chain_id, file_name, file_hash)`, כש-hash הוא sha256 של הבייטים שהורדו. אם כבר קיימת שורה `succeeded` עם אותו זיהוי, מדלגים על הקובץ ולא רושמים שורה חדשה. קובץ שנכשל ייקלט שוב בריצה הבאה.
- **פענוח:**
  - בייטים שמתחילים ב-`\x1f\x8b` עוברים gunzip, עם תקרה על הגודל אחרי הפריסה.
  - BOM של UTF-16 (`\xff\xfe` / `\xfe\xff`) מפוענח כ-UTF-16. אחרת `utf-8-sig`.
  - XML עם `xml.etree.ElementTree`.
  - ה-handler של 3.2 סופר את רשומות הסוג: `Store` ב-stores, ‏`Item` ב-price_full, ‏`Promotion` ב-promo_full.
- **טרנזקציה לכל קובץ:** קובץ שנכשל (הורדה, gz, קידוד, XML או handler) עושה rollback רק לעצמו. הוא נרשם `failed` עם הודעת שגיאה, והריצה ממשיכה לקובץ הבא.
- **ריצה:**
  - שורה `running` נשמרת בהתחלה.
  - בסוף הריצה הסטטוס הוא אחד מאלה:
    - `succeeded`: אין קבצים שנכשלו.
    - `partial`: נכשל לפחות קובץ אחד, אבל לפחות קובץ אחד הצליח או דולג.
    - `failed`: נכשלה רשימת הקבצים, או שכל הקבצים נכשלו.
  - לשורה יש `finished_at`, ומונים: `files_seen` (הקבצים שנבחרו), `files_ingested`, `files_skipped`, `files_failed` ו-`records`.
- **אין ריצה כפולה לאותה רשת:** `pg_try_advisory_lock` לפי הרשת, לכל אורך הריצה. אם הנעילה תפוסה, הריצה לא מתחילה: מחזירים `None` ולא נוצרת שורה. ריצה שנשארה `running`, כי התהליך נפל, מסומנת `abandoned` בתחילת הריצה הבאה של אותה רשת.
- **הרשתות נוצרות דרך `catalog.service`:** `ensure_chain(session, gov_chain_code, name)` מחזירה את ה-id אם הרשת קיימת, ואחרת יוצרת אותה. קודי הרשתות: שופרסל `7290027600007`, רמי לוי `7290058140886`, קרפור `7290055700007`. השמות: "שופרסל", "רמי לוי", "קרפור".
- **לוגים ושגיאות בלי סודות:** לוג JSON מובנה עם `chain`, ‏`file_name`, מונים וסוג השגיאה. **אסור** לרשום URL מלא, כי בשופרסל יש בו חתימה. הודעת שגיאה נשמרת כ-`<ExceptionType>: <message>`, וקוצרה ל-500 תווים לכל היותר.
- **תקרות גודל:** קובץ שהורד עד 100MB. XML אחרי gunzip עד 500MB. timeout של 60 שניות לבקשת HTTP. מעבר לתקרה, הקובץ נכשל.

**Never:**
- לא לכתוב סניפים, מחירים, מבצעים או מוצרים. זה Stories 3.3–3.6.
- לא לבצע HTTP אמיתי בבדיקות. כל adapter מקבל פונקציית HTTP שאפשר להחליף.
- בריפו אין קבצים אמיתיים של רשתות. ה-fixtures בדויים וקטנים, באותו מבנה: שמות סניפים, כתובות ומוצרים מומצאים.
- לא לבטל אימות TLS, ולא לשנות `CARTWISE_EXTRA_CA`.
- לא להוסיף endpoint ל-API, ולא לבנות ניטור או התראות (3.5).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| ריצה תקינה | adapter מזויף עם Stores (UTF-16, לא מכווץ), ‏PriceFull ו-PromoFull (gz, ‏UTF-8) | run `succeeded`. שלוש שורות `ingestion_files` במצב `succeeded`, עם hash, גודל ו-records. ה-records של הריצה הוא הסכום | — |
| קובץ פגום | ‏gz שבור, או XML לא תקין, בין שני קבצים תקינים | שני הקבצים התקינים `succeeded`. השבור `failed`, עם `error` שמתחיל בסוג החריגה. run `partial` | rollback רק לקובץ |
| הורדה נכשלת | `fetch` זורק `OSError` לקובץ אחד | הקובץ `failed`, והשאר ממשיכים | כמו קובץ פגום |
| ריצה חוזרת | אותם קבצים, אותם בייטים | `files_skipped`=3, ‏`files_ingested`=0, ואין שורות קבצים חדשות. run `succeeded` | — |
| אותו שם, תוכן אחר | אותו `file_name`, עם בייטים אחרים | נקלט כקובץ חדש, כי ה-hash שונה | — |
| קובץ שנכשל קודם | אותו זיהוי, ובריצה הקודמת `failed` | נקלט שוב | — |
| כמה גרסאות לאותו סניף | ‏`PriceFull…-001-005-20261103-010000` וגם `…-20261103-070000` | רק המאוחר נבחר | — |
| רשימה נכשלת | `list_files` זורק | run `failed`, ‏`error` מלא, ואין שורות קבצים | הריצה לא זורקת החוצה מה-job |
| ריצה מקבילה | נעילה תפוסה לאותה רשת | הקריאה השנייה מחזירה `None`, ולא נוצרת שורה | — |
| ריצה שננטשה | שורה `running` ישנה לאותה רשת | מסומנת `abandoned`, עם `finished_at`, לפני הריצה החדשה | — |
| חריגת גודל | gz שגודלו אחרי פריסה מעל התקרה | הקובץ `failed` | — |
| Cerberus | דף login מזויף עם csrftoken, ‏`/file` עם token חדש, ו-JSON של dir | ה-POST של dir נשלח עם ה-token **החדש**, ושמות הקבצים נלקחים מ-`fname` | אין token: `list_files` זורק |
| שופרסל, כמה עמודים | עמוד 1 ו-2 עם שורות, עמוד 3 ריק | נאספים הקבצים משני העמודים. שם הקובץ בלי ה-query | — |
| קרפור | דף מזויף עם `path` ו-`files` | ‏URL הוא `<base>/<path>/<name>` | אין `files`: `list_files` זורק |

</intent-contract>

## Code Map

- `backend/app/worker/main.py` -- `schedule_jobs` מוסיף כרגע את `purge_deleted` (CronTrigger, ‏`coalesce`, ‏`max_instances=1`). כאן נוסף job לכל רשת: `IntervalTrigger(hours=INGEST_INTERVAL_HOURS)`, עם id בצורה `ingest_<chain_key>`.
- `backend/app/worker/jobs/purge_deleted.py` -- הדפוס לכתוב לפיו את `ingest_chain.py`: `run(session_factory=SessionLocal, ...)` ולוג מובנה.
- `backend/app/modules/ingestion/{models,repository,service,schemas}.py` -- כרגע stubs ריקים. כאן נכנס התוכן החדש. את `routes.py` לא משנים.
- `backend/app/modules/geo/service.py` -- הדפוס ל-adapter מול שירות חיצוני: ‏`Protocol`, ‏`fetch` שמוזרק, `User-Agent` מזהה, timeout, תקרת גודל, ולוג לפי סוג החריגה בלבד.
- `backend/app/modules/catalog/service.py:78` -- `ensure_chain_with_club`. מוסיפים לידה את `ensure_chain`. ‏`catalog/models.py` כבר מגדיר את `Chain.gov_chain_code` כ-unique.
- `backend/app/core/config.py` -- `Settings`. מוסיפים כאן את ההגדרות החדשות. הדפוס: `NOMINATIM_URL` עם קבוע ברירת מחדל.
- `backend/app/core/ids.py` -- `new_id` (UUIDv7) למפתחות.
- `backend/migrations/versions/0006_user_prefs.py` -- המיגרציה האחרונה. החדשה היא `0007`. מוסכמת השמות: `op.f(...)` ו-`NAMING_CONVENTION` ב-`core/db.py`.
- `backend/tests/integration/conftest.py` -- `db_url`: ‏PostGIS ב-testcontainers, אחרי `upgrade head`. גם בדיקות ingestion בצד ה-DB רצות כאן.
- `backend/tests/unit/test_worker.py` -- בודקת היום ש-`get_jobs()` הוא בדיוק `[PURGE_DELETED_JOB_ID]`. צריך לעדכן אותה לרשימה החדשה.

## Tasks & Acceptance

**Execution:**
- `backend/app/core/config.py` -- להוסיף `SHUFERSAL_PRICES_URL`, ‏`CERBERUS_URL`, ‏`CARREFOUR_PRICES_URL`, ‏`CERBERUS_RAMI_LEVY_USERNAME` ו-`INGEST_INTERVAL_HOURS` -- אפשר לשנות פורטל או שם משתמש בלי לשנות קוד.
- `backend/app/modules/catalog/service.py` -- `ensure_chain(session, gov_chain_code, name) -> uuid.UUID`, ‏idempotent -- רק catalog יוצר רשתות.
- `backend/app/modules/ingestion/models.py` + `backend/migrations/versions/0007_ingestion.py`:
  - `ingestion_runs`: ‏id, ‏chain_id FK, ‏started_at, ‏finished_at null, ‏status, ‏files_seen, ‏files_ingested, ‏files_skipped, ‏files_failed, ‏records, ‏error null. אינדקס על `(chain_id, started_at)`.
  - `ingestion_files`: ‏id, ‏run_id FK, ‏chain_id, ‏file_name, ‏kind, ‏file_hash char(64), ‏size_bytes, ‏status, ‏records, ‏error null, ‏created_at. אינדקס unique חלקי על `(chain_id, file_name, file_hash)` `WHERE status='succeeded'`.
  - CHECK על ערכי `status` ו-`kind`.
- `backend/app/modules/ingestion/adapters.py` (חדש):
  - ‏`RemoteFile(name, kind, store_code, stamp, url)`.
  - ‏`ChainAdapter` Protocol: ‏`key`, ‏`gov_chain_code`, ‏`name`, ‏`list_files()`, ‏`fetch(file)`.
  - ‏`parse_file_name` ו-`latest_per_store`.
  - ‏`ShufersalAdapter`, ‏`CerberusAdapter` (עם cookie jar) ו-`CarrefourAdapter`. כל אחד מקבל פונקציות HTTP שמוזרקות.
  - ‏`build_adapters(settings)` -- ‏adapter נפרד לכל רשת, עם HTTP שאפשר להחליף בבדיקות.
- `backend/app/modules/ingestion/decode.py` (חדש) -- `decode_xml(data) -> Element`: ‏gzip עם תקרה, ‏BOM ו-XML. ‏`count_records(kind, root)` -- אחידות בין רשתות שמשתמשות בקידודים שונים.
- `backend/app/modules/ingestion/repository.py` + `service.py`:
  - ‏`ingest_chain(session_factory, adapter, handlers=DEFAULT_HANDLERS, now=...) -> RunSummary | None`: ‏נעילה, ‏abandoned, ‏run, ‏קובץ אחר קובץ, ואז סיכום.
  - ‏`handlers: dict[kind, Callable[[Session, uuid.UUID, Element], int]]` -- נקודת ההרחבה ל-3.3 ו-3.4.
- `backend/app/worker/jobs/ingest_chain.py` (חדש) -- `run(chain_key, session_factory=SessionLocal)`, ו-`__main__` לריצה ידנית: `python -m app.worker.jobs.ingest_chain shufersal`. אף פעם לא זורק חריגה מתוך ה-scheduler.
- `backend/app/worker/main.py` -- job לכל adapter.
- `backend/tests/fixtures/ingestion/` -- XML ו-HTML בדויים וקטנים: Stores ב-UTF-16, ו-PriceFull ו-PromoFull ב-gz. ה-gz אפשר לייצר בזמן הבדיקה.
- `backend/tests/unit/test_ingestion_adapters.py`, `test_ingestion_decode.py` -- adapters, בחירת הקובץ האחרון, ופענוח.
- `backend/tests/integration/test_ingestion.py` -- כל שורות המטריצה בצד ה-DB, כולל ריצה מקבילה.
- `backend/tests/unit/test_worker.py` -- עדכון: ‏job `purge_deleted` ועוד שלושה jobs לרשתות. הרווח בין הרצות קטן או שווה ל-6 שעות, ו-`max_instances=1`.
- `deploy/README.md` -- סעיף קצר על הקליטה: ההגדרות, והפקודה לריצה ידנית.

**Acceptance Criteria:**
- Given worker שעלה, when בודקים את ה-jobs, then יש job לכל אחת משלוש הרשתות, והרווח בין שתי הרצות קטן או שווה ל-6 שעות.
- Given ריצה שהסתיימה, when קוראים את `ingestion_runs` ואת `ingestion_files`, then רואים את זמן ההתחלה והסיום, את הקבצים, את מספר הרשומות לכל קובץ ולריצה, ואת השגיאות.
- Given קובץ פגום באמצע ריצה, when הריצה מסתיימת, then שאר הקבצים נקלטו, והשגיאה רשומה בשורת הקובץ.

## Spec Change Log

## Review Triage Log

### 2026-11-03 — Review pass
- verdicts: 34 findings — high 0, medium 5, low 15, false 9, maybe-false 5
- findings:
  - Verification Gap:
    - `low` `patch` אין בדיקה ל-URLError עם סיבה של SSL (המקרה של NetFree) — נוסף מקרה עם `SSLCertVerificationError`: הפרטים נשמרים ואין `sig=`.
    - `low` `patch` לא נבדקים הפיזור של זמני ההתחלה ו-`misfire_grace_time` — נוספה בדיקה ב-test_worker.
    - `low` `patch` קוד היציאה של `ingest_chain.main` לא נבדק — נבדקים 0, 1 ו-1.
    - `low` `defer` אין בדיקה ל-invalidate כש-unlock נכשל — נרשם ב-deferred.
    - `maybe-false` `reject` (Other) כשגם הרישום של הקובץ שנכשל זורק, הריצה נשארת running — זה קורה רק כשה-DB נפל, ואז גם `finish_run` לא היה מצליח. הריצה הבאה מסמנת `abandoned`, ו-ingest_job רושם את החריגה בלוג. גם אם זה נכון, הדירוג low.
  - Edge Case Hunter:
    - `medium` `patch` רשימה ריקה נרשמת succeeded — עכשיו `failed`, עם "no files listed".
    - `low` `reject` חיתוך שקט ב-`SHUFERSAL_MAX_PAGES` — נבדק חי: יש 22 עמודים לעומת תקרה של 60. זה לא צפוי בשימוש רגיל, והתיקון מוסיף ענף.
    - `medium` `patch` קוד הרשת שבשם הקובץ לא נבדק — `remote_file` מדלג על קובץ של רשת אחרת.
    - `low` `reject` redirect מ-https ל-http עוקף את הבדיקה — שלושת הפורטלים מפנים ל-https. התיקון דורש redirect handler משלנו.
    - `low` `reject` כשל ברישום שורת הקובץ שנכשל — אותו נימוק כמו ב-Verification Gap.
    - `maybe-false` `defer` זיכרון בקובץ שקרוב ל-500MB — הקבצים האמיתיים קטנים בהרבה. medium (unverified), ונרשם ב-deferred.
    - `false` `reject` קידוד שמוצהר בתוך ה-XML (windows-1255) — בבדיקה החיה, קבצים של שלוש הרשתות פוענחו כ-UTF-8 או כ-UTF-16 עם BOM.
    - `maybe-false` `reject` connection של הנעילה ננתק אחרי שעות של חוסר פעילות — ב-Postgres ברירת המחדל של `idle_session_timeout` היא 0, וריצה נמשכת כחצי שעה. גם אם זה נכון, הדירוג low.
    - `medium` `patch` החתימה של שופרסל פגה באמצע הריצה — אומת חי: `se=` הוא 30 דקות קדימה, ורשימת הקבצים לוקחת כ-12 דקות. עכשיו `fetch` מבקש מחדש, אחרי 403, את העמוד של הסניף (`storeId`), ומנסה שוב פעם אחת.
    - `false` `reject` רשת כפולה לפי שם (`ensure_chain_with_club`) — רק סקריפט ה-seed של dev יוצר רשתות לפי שם, והשמות בו בדויים. רשתות אמיתיות נוצרות רק לפי `gov_chain_code`.
  - Blind Hunter:
    - `medium` `patch` קוד רשת לא נבדק — אותו תיקון.
    - `low` `patch` התחברות כושלת ל-Cerberus לא מזוהה — `PortalFormatError("Cerberus login failed")` כשטופס ה-login מופיע שוב.
    - `medium` `patch` החתימות של שופרסל פגות — אותו תיקון.
    - `low` `reject` חיתוך שקט בתקרת העמודים — אותו נימוק.
    - `low` `reject` כל קובץ מורד מחדש בכל ריצה — AD-14 מזהה קובץ לפי hash. רוחב הפס חינמי, והקצב סביר.
    - `maybe-false` `defer` זיכרון — אותו נימוק, ונרשם ב-deferred.
    - `false` `reject` קידוד מוצהר — אותו נימוק.
    - `maybe-false` `reject` אין הגנה על סיום הריצה — אותו נימוק כמו ב-Verification Gap.
    - `false` `reject` נרמול של `store_code` ושל `stamp` — ההשוואה נעשית בתוך אותה רשת, באותו פורמט, ולכן הסדר נשמר. ההתאמה לקובץ ה-Stores שייכת ל-3.3.
    - `false` `reject` רשת כפולה לפי שם — אותו נימוק.
    - `false` `reject` אין קליטה ברשת המסוננת — CLAUDE.md קובע שלא עוקפים, ושהשגיאה נרשמת. זה נבדק עכשיו.
    - `low` `reject` הטבלאות גדלות בלי הגבלה — קובץ שדולג לא מוסיף שורה, וזה בערך אלף שורות ביום.
    - `low` `patch` חורים בבדיקות (SSL, רשת זרה, Cerberus) — נוספו. הבדיקה של unlock רשומה ב-deferred. `test_listing_json_is_parsed_as_utf8` נמחקה, והרשימה נבדקת דרך ה-adapter.
    - `low` `patch` `HTTPError` לא נסגר — נוסף `exc.close()`.
    - `low` `patch` `Mapped[str]` במקום Literal — הוחלף ב-`RunStatus`, ‏`FileStatus` ו-`FileKind`.
  - Intent Alignment:
    - `false` `reject` לא נכתבים נתונים לטבלאות הדומיין (R2) — Stories 3.3, ‏3.4 ו-3.6 באותו Epic מגדירות את הכתיבה הזו.
    - `false` `reject` אין בדיקה מול הפורטלים האמיתיים (R3) — ה-intent אוסר קבצים אמיתיים בבדיקות. בנוסף, הורצה בדיקה חיה אחת ידנית (ראו אימות).
    - `false` `reject` שם המשתמש של Cerberus הוא ברירת מחדל בקוד (R4b) — זה ערך ציבורי, ו-env מחליף אותו. ה-intent מבקש "via env config".
    - `low` `patch` בריצה partial השדה `error` ריק — עכשיו נכתב "N of M files failed".

## Design Notes

**נעילה:** `pg_try_advisory_lock` מוחזקת על connection נפרד מה-sessions של הקבצים, לכל אורך הריצה, ומשוחררת ב-`finally`. המפתח: `hashtext('ingest:' || gov_chain_code)`.

**הנקודה ש-3.3 ו-3.4 יחליפו:**
```python
DEFAULT_HANDLERS = {
    "stores": count_handler("Store"),
    "price_full": count_handler("Item"),
    "promo_full": count_handler("Promotion"),
}
```

**פירוש שם הקובץ:** `^(Stores|PriceFull|PromoFull)(\d{13})-(\d+)(?:-(\d+))?-(\d{8})-?(\d{3,6})?`, עם סיומת `.gz` או `.xml` (אופציונלית). ב-Stores אין קוד סניף. אם שתי גרסאות מקבלות אותה חותמת זמן, השם הגדול יותר בסדר מילוני מנצח.

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy` -- expected: נקי.
- `cd backend && CARTWISE_REQUIRE_DOCKER=1 uv run pytest` -- expected: הכל עובר, כולל ה-integration החדשים.
- `cd backend && uv run alembic upgrade head` מול DB זמני, ואז `downgrade -1` -- expected: עובר בשני הכיוונים. בדיקות ה-integration כבר מריצות את ה-upgrade.

## Auto Run Result

Status: done

**סיכום:** ה-worker קולט כל 6 שעות את הקבצים של שופרסל, רמי לוי וקרפור: Stores, ‏PriceFull ו-PromoFull, הגרסה האחרונה לכל סניף. כל ריצה וכל קובץ נרשמים ב-`ingestion_runs` וב-`ingestion_files`, עם זמנים, רשומות ושגיאות. קובץ שכבר נקלט, באותו hash, מדולג. קובץ פגום נכשל לבד, והשאר נקלטים. ה-handlers סופרים רשומות בלבד. 3.3 ו-3.4 יחליפו אותם בכתיבה.

**קבצים:**
- `backend/app/modules/ingestion/adapters.py` -- שלושה adapters, ‏`UrllibClient` ובחירת הקובץ האחרון.
- `backend/app/modules/ingestion/decode.py` -- gz, ‏UTF-8/UTF-16 ו-XML עם תקרות.
- `backend/app/modules/ingestion/{service,repository,models}.py`, `backend/migrations/versions/0007_ingestion.py` -- הריצה, הנעילה, היומן ו-AD-14.
- `backend/app/modules/catalog/{service,repository}.py` -- `ensure_chain` לפי `gov_chain_code`.
- `backend/app/core/config.py` -- הכתובות של הפורטלים, שם המשתמש ב-Cerberus ו-`INGEST_INTERVAL_HOURS`.
- `backend/app/worker/{main.py,jobs/ingest_chain.py}` -- job לכל רשת, ופקודה לריצה ידנית.
- `backend/tests/...` -- fixtures בדויים, ובדיקות unit ו-integration לכל המטריצה.
- `deploy/README.md`, `.gitattributes` -- תיעוד, ו-fixture ב-UTF-16 כקובץ בינארי.

**ממצאי הסקירה:** 34 ממצאים:
- **תוקנו:** 3 entries ברמת medium (חתימות שופרסל, קוד רשת, רשימה ריקה), ו-8 ברמת low.
- **נדחו ל-deferred:** 2 (זיכרון, בדיקת unlock).
- **נדחו לגמרי:** השאר. הנימוק של כל אחד רשום ב-Review Triage Log.

**המלצה לסקירת המשך:** `true`. תוקנו 3 entries ברמת medium. הסיכון שלא אומת: רענון הקישור אחרי 403 בשופרסל נבדק רק עם fakes. ריצה מלאה ארוכה מול הפורטל עוד לא הורצה.

**אימות:**
- ruff, format ו-mypy נקיים.
- `CARTWISE_REQUIRE_DOCKER=1 pytest`: 523 עברו.
- המיגרציה נבדקה ב-roundtrip בבדיקות הקיימות.
- gitleaks על 32 הקבצים שהשתנו: `no leaks found`.
- **בדיקה חיה (ידנית, בלי DB) מול שלושת הפורטלים:**
  - **שופרסל:** 856 קבצים, ו-417 סניפים ב-Stores.
  - **רמי לוי:** 195 קבצים נבחרו, ו-99 סניפים.
  - **קרפור:** 293 קבצים, ו-147 סניפים.
  - בכל רשת פוענח גם קובץ PromoFull.

**סיכונים שנשארו:**
- רשימת הקבצים של שופרסל איטית: כ-15 שניות לעמוד, ובערך 12 דקות לרשימה כולה.
- ריצה מלאה עם כתיבה ל-DB לא הורצה מול הפורטלים.
- הזיכרון בקבצים גדולים (ב-deferred).
