---
title: 'Story 3.5: ניטור תקינות הקליטה והתראות למפעיל'
type: 'feature'
created: '2026-11-03'
status: 'done'
baseline_revision: '3bd3fa000f8a2e460fa2dda1a36b64c086962852'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/docs/implementation-artifacts/epic-3-context.md'
  - '{project-root}/docs/implementation-artifacts/spec-3-2-scheduled-ingestion.md'
warnings: ['oversized']
deferred:
  - summary: >-
      record_drop מסכם את כל הסדרות, ולכן סניף אחד שקרס יכול להיבלע בתוך הסכום.
    evidence: |-
      ה-AC מדבר על "מספר הרשומות" של הרשת. בדיקה לפי סדרה בודדת תהיה רועשת, כי מספר המבצעים בכל סניף משתנה. כדי להכריע: לבדוק בנתונים אמיתיים, אחרי שבועות של קליטה, אם להוסיף לפרטי ההתראה את "הסדרה הגרועה ביותר".
    location: >-
      backend/app/modules/ingestion/health.py
    severity: low
---

<intent-contract>

## Intent

**Problem:** כשהקליטה של רשת מפסיקה, או מתחילה להחזיר פחות נתונים, אף אחד לא יודע. המחירים מתיישנים בשקט. FR-16 דורש התראה למפעיל בשלושה מצבים: אין קליטה 24 שעות, ירידה של יותר מ-30% ברשומות, או יותר מ-5% שגיאות parsing.

**Approach:**
- מודול ingestion בודק את שלושת התנאים מתוך `ingestion_runs` ו-`ingestion_files`:
  - בסוף כל ריצה, את הירידה ואת השגיאות של אותה ריצה.
  - ב-job שעתי, את תנאי ה-24 שעות לכל רשת.
- התראה נפתחת פעם אחת לכל `(chain, kind)`, ונשלחת דרך adapter: לוג מובנה תמיד, ומייל ב-SMTP כשהוגדר. כל עוד המצב לא נפתר, היא נשלחת שוב פעם ב-24 שעות. כשהמצב נפתר, היא נסגרת.

## Boundaries & Constraints

**Always:**
- **ספים, ב-`Settings` עם env:**
  - `INGEST_STALE_HOURS=24`
  - `INGEST_RECORD_DROP_PCT=30`
  - `INGEST_FILE_ERROR_PCT=5`
  - `INGEST_ALERT_REPEAT_HOURS=24`
  - כולם חיוביים, עם `ge`/`le` סבירים.
- **תנאי `stale`:**
  - לרשת אין ריצה עם status `succeeded` או `partial` שהסתיימה ב-`INGEST_STALE_HOURS` האחרונות.
  - רשת בלי אף ריצה כזו נמדדת מה-`started_at` של הריצה הראשונה שלה. רשת שלא רצה אף פעם לא מתריעה.
  - ריצה שבה כל הקבצים דולגו (hash זהה) היא `succeeded`, ולכן נחשבת עדכון.
- **תנאי `record_drop`:**
  - לכל קובץ `succeeded` בריצה, מוצאים את הקובץ ה-`succeeded` הקודם מאותה סדרה. סדרה מוגדרת לפי `(chain_id, series_key)`.
  - `series_key` הוא `"<kind>:<store_code or ->"`. הוא עמודה חדשה ב-`ingestion_files` (מיגרציה `0010`), ונכתב בזמן הרישום מתוך `RemoteFile`.
  - שורות ישנות בלי `series_key` לא משתתפות.
  - **החישוב:** ‏`prev = Σ records` של הקבצים הקודמים שנמצאו, ו-`cur = Σ records` של הקבצים המתאימים בריצה. ההתראה נפתחת כש-`prev > 0` וגם `(prev - cur) / prev * 100 > INGEST_RECORD_DROP_PCT`.
  - ריצה שלא קלטה אף קובץ (הכל דולג) לא משנה את מצב ההתראה.
- **תנאי `file_errors`:**
  - בריצה שיש בה לפחות קובץ אחד שנוסה (`files_ingested + files_failed > 0`), ההתראה נפתחת כש-`files_failed / (files_ingested + files_failed) * 100 > INGEST_FILE_ERROR_PCT`.
  - ריצה עם status `failed`, כי רשימת הקבצים נכשלה, נחשבת כ-100% שגיאות.
- **מחזור החיים של התראה:**
  - **הטבלה:** `ingestion_alerts` (שייכת ל-ingestion), עם id, ‏chain_id, ‏kind (`stale`, ‏`record_drop` או `file_errors`), ‏opened_at, ‏last_sent_at, ‏resolved_at null, ‏details (JSON) ו-run_id null.
  - **אילוץ:** unique חלקי על `(chain_id, kind) WHERE resolved_at IS NULL`.
  - **תנאי מתקיים ואין התראה פתוחה:** נפתחת התראה ונשלחת.
  - **תנאי מתקיים ויש התראה פתוחה:** היא נשלחת שוב רק אם `now - last_sent_at >= INGEST_ALERT_REPEAT_HOURS`.
  - **התנאי כבר לא מתקיים:** ההתראה מקבלת `resolved_at=now`, ונרשמת שורת לוג `ingestion_alert_resolved`. לא נשלח מייל.
  - **מתי כל תנאי נבדק:**
    - `stale` נבדק רק ב-job.
    - `record_drop` ו-`file_errors` נבדקים בסוף כל ריצה שקלטה או ניסתה קבצים, וכן בריצה `failed`.
- **Adapter, ‏`AlertSink` (Protocol `send(alert: AlertMessage) -> None`):**
  - **`LogAlertSink`:** פעיל תמיד. רושם `logger.error("ingestion_alert", extra={chain, kind, details})`.
  - **`EmailAlertSink`:** פעיל רק כשכל ההגדרות האלה קיימות: `ALERT_SMTP_HOST`, ‏`ALERT_SMTP_PORT` (ברירת מחדל 587), ‏`ALERT_SMTP_USER`, ‏`ALERT_SMTP_PASSWORD`, ‏`ALERT_EMAIL_FROM`, ‏`ALERT_EMAIL_TO`.
    - עובד עם `smtplib` ו-STARTTLS, עם `ssl.create_default_context()`. **אימות התעודה פעיל תמיד.**
    - timeout של 30 שניות.
    - נושא ותוכן בעברית: שם הרשת, סוג ההתראה, המספרים, והזמן ב-UTC.
    - כשל בשליחה נרשם בלוג (סוג החריגה בלבד). הוא לא מכשיל את הריצה או את ה-job, וההתראה נשארת עם ה-`last_sent_at` הקודם. אם עוד לא נשלחה אף פעם, `last_sent_at=null`, ולכן ניסיון חוזר יקרה בבדיקה הבאה.
  - **`build_alert_sinks(settings)`:** מחזירה את רשימת ה-sinks.
  - הסיסמה רק ב-`.env` שבשרת. בריפו אין שום ערך שלה.
- **Job חדש, `check_ingestion_health`:**
  - רץ כל שעה, עם `IntervalTrigger`, ‏`coalesce` ו-`max_instances=1`, ומתחיל כמה דקות אחרי העלייה.
  - לעולם לא זורק חריגה.
  - אפשר להריץ אותו ידנית: `python -m app.worker.jobs.check_ingestion_health`.
- **החיבור לריצה (3.2):** בסוף `_run`, אחרי `finish_run` והריענון, נקרא `evaluate_run(...)` ב-session משלו. כשל בהערכה נרשם בלוג, ולא משנה את ה-status של הריצה.
- **מה נדחה מ-3.2:** בדיקה שמוודאת ש-`ingest_chain` מחזיר summary גם כש-`repository.unlock` זורק, ושהריצה הבאה של אותה רשת לא נחסמת.

**Never:**
- לא להוסיף Sentry או תלות בתשלום, ולא שירות חדש. Sentry ייכנס כשהוא יוגדר לכל השרת.
- לא לבטל אימות TLS ב-SMTP. לא לשים בריפו סיסמה, כתובת מייל אמיתית או `.env`.
- לא לבצע SMTP אמיתי בבדיקות: מזריקים `smtp_factory` מזויף.
- לא לשנות את הקליטה עצמה: ה-handlers, ה-adapters, הנעילה. מלבד רישום `series_key` והקריאה ל-`evaluate_run`.
- לא לבנות endpoint או מסך. מספיקים CLI ולוג.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| ריצה תקינה | ריצה `succeeded`, ‏records דומים לקודמת | אין התראה | — |
| ירידה של 40% | ‏PriceFull של סניף 1: הקודם 1000, הנוכחי 600 | נפתחת התראה `record_drop` אחת, עם `details` = ‏prev 1000, ‏cur 600, ‏pct 40. ה-sink נקרא פעם אחת | — |
| ירידה של 20% | 1000 → 800 | אין התראה | — |
| ריצה שדילגה על הכל | ‏files_ingested 0, ‏failed 0, והתראת drop פתוחה | ההתראה נשארת פתוחה, ואין שליחה | — |
| ההתאוששות | ריצה אחרי drop, עם 1000 → 990 | ‏`record_drop` נסגרת (resolved_at), ואין שליחה | — |
| שגיאות קבצים | 2 מתוך 20 קבצים נכשלו (10%) | ‏`file_errors` נפתחת | — |
| ריצה failed | רשימת הקבצים נכשלה | ‏`file_errors` נפתחת | — |
| עבר יום בלי קליטה | הריצה המוצלחת האחרונה לפני 25 שעות. ה-job רץ | ‏`stale` נפתחת. בהרצה חוזרת אחרי שעה אין שליחה נוספת | — |
| שליחה חוזרת | ‏`stale` פתוחה, ו-last_sent_at לפני 25 שעות | נשלחת שוב, ו-last_sent_at מתעדכן | — |
| קליטה חזרה | יש ריצה מוצלחת חדשה. ה-job רץ | ‏`stale` נסגרת | — |
| רשת חדשה | אין ריצות בכלל | אין התראה | — |
| מייל לא מוגדר | חסר אחד מערכי ה-SMTP | רק `LogAlertSink` | — |
| מייל נכשל | ה-SMTP המזויף זורק `OSError` | ההתראה נשמרת. ‏`last_sent_at` לא מתעדכן. הריצה וה-job לא נכשלים | כשל השליחה נרשם בלוג |
| unlock נכשל (מ-3.2) | ‏`repository.unlock` זורק | ‏`ingest_chain` מחזיר summary, והריצה הבאה לא מחזירה None | — |

</intent-contract>

## Code Map

- `backend/app/modules/ingestion/service.py` -- `_run`: ‏`finish_run`, ואחריו `_refresh_current_prices`, ב-session נפרד (3.4). כאן נוספת הקריאה ל-`evaluate_run`. ‏`_ingest_file` רושם את `repository.add_file`, וצריך להעביר לו גם `series_key`.
- `backend/app/modules/ingestion/repository.py` -- `add_file`, ‏`create_run`, ‏`finish_run`, ו-`try_lock`/`unlock` (הנעילה, ולשם הבדיקה שנדחתה מ-3.2).
- `backend/app/modules/ingestion/adapters.py` -- `RemoteFile(name, kind, store_code, stamp, url)`. משם מגיע `series_key`.
- `backend/app/modules/ingestion/models.py` -- `IngestionRun` ו-`IngestionFile`, עם `RunStatus` ו-`FileStatus`. מוסיפים כאן את `IngestionAlert`.
- `backend/app/worker/main.py` -- `schedule_jobs` ו-`INGEST_JOB_IDS`. כאן נוסף ה-job השעתי. ‏`backend/tests/unit/test_worker.py` בודק את רשימת ה-jobs, וצריך לעדכן אותו.
- `backend/app/worker/jobs/ingest_chain.py` -- הדפוס ל-job שלא זורק חריגה, עם `main` ידני.
- `backend/app/core/config.py` -- `Settings`, עם הדפוס `Field(ge, le)`.
- `backend/migrations/versions/0009_products_prices.py` -- המיגרציה האחרונה. החדשה היא `0010`.
- `backend/tests/integration/test_ingestion.py` -- `FakeAdapter`, ‏TRUNCATE, ו-`test_a_run_while_another_holds_the_lock`, שאפשר ללמוד ממנה לבדיקת ה-unlock.
- `deploy/README.md` -- סעיף "ניטור והתראות": ההגדרות, איפה רואים התראות, ופקודה ידנית.

## Tasks & Acceptance

**Execution:**
- `backend/app/core/config.py` -- הספים והגדרות ה-SMTP. ‏`ALERT_SMTP_PASSWORD` מוגדר כ-`SecretStr`.
- `backend/app/modules/ingestion/models.py` + `backend/migrations/versions/0010_ingestion_health.py` -- `series_key` ב-`ingestion_files`, עם אינדקס על `(chain_id, series_key, created_at)`. ‏`ingestion_alerts`, עם unique חלקי ו-CHECK על kind.
- `backend/app/modules/ingestion/alerts.py` (חדש) -- `AlertMessage`, ‏`AlertSink`, ‏`LogAlertSink`, ‏`EmailAlertSink(smtp_factory=smtplib.SMTP)` ו-`build_alert_sinks`.
- `backend/app/modules/ingestion/health.py` (חדש) -- `evaluate_run(session, run_id, sinks, settings, now)`, ‏`check_stale(session, sinks, settings, now)`, ו-`_raise_or_resolve`: פתיחה, שליחה חוזרת וסגירה.
- `backend/app/modules/ingestion/{repository,service}.py` -- `series_key` בזמן הרישום, הקריאה ל-`evaluate_run`, ושאילתות ההתראות.
- `backend/app/worker/jobs/check_ingestion_health.py` (חדש) + `backend/app/worker/main.py` -- ה-job השעתי.
- `backend/tests/unit/test_ingestion_alerts.py` -- ה-sinks, ההגדרות החסרות, תוכן המייל, ו-STARTTLS עם context.
- `backend/tests/integration/test_ingestion_health.py` -- כל שורות המטריצה מול Postgres.
- `backend/tests/integration/*.py` -- הוספת `ingestion_alerts` ל-TRUNCATE בכל מקום שמנקה את `ingestion_runs`.
- `backend/tests/unit/test_worker.py` -- ה-job החדש.
- `deploy/README.md` -- הסעיף.

**Acceptance Criteria:**
- Given רשת שלא עודכנה 24 שעות, when ה-job השעתי רץ, then נשלחת למפעיל התראה אחת. היא לא נשלחת שוב באותו יום, והיא נסגרת כשהקליטה חוזרת.
- Given ריצה שבה מספר הרשומות ירד ביותר מ-30% לעומת הקבצים הקודמים של אותן סדרות, when הריצה מסתיימת, then נשלחת למפעיל התראה, עם המספרים.

## Spec Change Log

## Review Triage Log

### 2026-11-03 — Review pass
- verdicts: 37 findings — high 0, medium 6, low 24, false 7, maybe-false 0
- findings:
  - Blind Hunter:
    - `low` `patch` התראות של record_drop ושל file_errors לא נשלחות שוב בלי ריצה שמודדת אותן — ה-job השעתי שולח תזכורת (`remind_open`).
    - `medium` `patch` ‏record_drop נסגר בגלל סדרות אחרות — `series_keys` נשמרים ב-details, וההתראה נסגרת רק כשהסדרות שלה נבדקו.
    - `low` `defer` הסכום מסתיר קריסה של סניף אחד — נרשם ב-deferred.
    - `medium` `patch` שליחת המייל קורית בתוך טרנזקציה פתוחה — עכשיו יש commit לפני השליחה, ו-commit אחרי.
    - `medium` `patch` טרנזקציה אחת לכל הרשתות, ותחרות על ה-unique — עכשיו יש commit לכל רשת ולכל kind, ו-`ON CONFLICT DO NOTHING` עם קריאה חוזרת.
    - `medium` `patch` כשאחד ה-sinks נכשל, כולם נשלחים שוב כל שעה — ההתראה נחשבת נשלחה כשלפחות sink אחד קיבל אותה. זו סטייה מכוונת משורת המטריצה "מייל נכשל: last_sent_at לא מתעדכן". עם השורה הזו הלוג היה מתריע כל שעה בלי סוף.
    - `low` `patch` אין בדיקה בין הגדרות שתלויות זו בזו — validator דוחה `INGEST_STALE_HOURS <= INGEST_INTERVAL_HOURS`.
    - `low` `patch` פורט 465 — `SMTP_SSL`, עם אותו context.
    - `low` `reject` התראת stale אחרי שה-worker היה למטה — ההתראה נכונה: הנתונים באמת ישנים.
    - `low` `patch` רשת שכבר לא נקלטת מתריעה לתמיד — רק רשתות מוגדרות נבדקות.
    - `low` `patch` אין backfill ל-`series_key` — ה-README מסביר את זה.
    - `low` `patch` מקרי קצה בלי בדיקות — נוספו (סדרה אחרונה, partial, תזכורת).
    - `low` `patch` פורמט הזמן במייל — `_utc()`.
    - `low` `reject` הלוג של קריסה רושם רק את סוג החריגה — זה הכלל בפרויקט, כדי לא לחשוף סודות.
    - `false` `reject` ה-spec לא בתוך ה-diff — הוא הוצא בכוונה.
  - Verification Gap:
    - `low` `patch` ריצה partial כעדכון — `test_a_partial_run_counts_as_an_update`.
    - `low` `patch` השוואה מול הקובץ האחרון בסדרה — 100, אחר כך 1000, אחר כך 600, ‏prev 1000.
    - `medium` `patch` ה-sinks של ברירת המחדל לא נבדקו — נבדק דרך caplog ש-`ingestion_alert` נרשם ו-last_sent_at מתעדכן.
    - `low` `reject` ‏`_send` עם רשימה ריקה מחזיר True — ‏`build_alert_sinks` תמיד כולל את `LogAlertSink`.
  - Intent Alignment:
    - `medium` `patch` ‏(a) ה-worker לא מקבל את הגדרות ה-SMTP — `${VAR:-}` ב-compose, ‏`env_ignore_empty`, ותיעוד ב-README.
    - `low` `reject` ‏(b) לפי ה-PRD כל קובץ שנכשל מתריע — הארכיטקטורה קובעת סף של 5%, והוא מונע רעש.
    - `low` `reject` ‏(c) "לא עודכן" כטריות של המקור — הרשתות מפרסמות קבצים בשם חדש כל יום, וזה נבדק.
    - `false` `reject` ‏(d) השוואה לפי סדרה ולא לפי ריצה — Design Notes מסבירים: הדילוג לפי hash.
    - `false` `reject` ‏(e) היקף מעבר ל-AC — לפי הארכיטקטורה.
    - `false` `reject` ‏(f) ‏FR-44 — שייך ל-Epic 7.
  - Edge Case Hunter:
    - `low` `patch` שליחה כל שעה כש-sink נכשל — אותו תיקון.
    - `low` `reject` אין backoff כשהמייל לא מוגדר נכון — אחרי התיקון יש לכל היותר מייל אחד כל `INGEST_ALERT_REPEAT_HOURS`.
    - `low` `patch` rollback של רשת A בגלל רשת B — commit לכל רשת.
    - `low` `patch` המייל נשלח וה-commit נכשל — commit לפני השליחה.
    - `low` `patch` תחרות על ה-unique — ON CONFLICT.
    - `low` `patch` עיגול לפני ההשוואה לסף — ההשוואה מול הערך המלא.
    - `low` `reject` סדרה שנעלמה מהרשימה — זה מצב רגיל כשסניפים משתנים.
    - `low` `patch` רשת שהוסרה — אותו תיקון.
    - `low` `patch` פורט 465 — אותו תיקון.
    - `false` `reject` (claim) "שגיאות parsing" כולל שגיאות הורדה — המטריצה מגדירה כשל ברמת קובץ.
    - `low` `patch` (claim) תזכורת ל-record_drop ול-file_errors — `remind_open`.
    - `false` `reject` (claim) שליחה כל שעה כשהמייל נכשל — תוקן.

## Design Notes

**למה השוואה לפי סדרה, ולא לפי ריצה:** בגלל הדילוג לפי hash (AD-14), ריצה שבה רוב הקבצים לא השתנו קולטת רק חלק מהקבצים. השוואה של `records` בין שתי ריצות הייתה מתריעה סתם. השוואה של כל קובץ לקודם בסדרה שלו, כמו PriceFull של אותו סניף, מודדת את מה שבאמת השתנה.

**"ההשוואות ממשיכות לעבוד" (FR-16):** כבר מתקיים, כי `current_prices` שומר את המחיר האחרון גם כשהקליטה נכשלת. רמת האמינות לפי גיל שייכת ל-Epic 7.

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy` -- expected: נקי.
- `cd backend && CARTWISE_REQUIRE_DOCKER=1 uv run pytest` -- expected: הכל עובר.

## Auto Run Result

Status: done

**סיכום:** מוגדרות שלוש התראות למפעיל: `stale` (24 שעות בלי קליטה מוצלחת, נבדק כל שעה), ‏`record_drop` (ירידה של יותר מ-30% לעומת הקובץ הקודם בכל סדרה) ו-`file_errors` (יותר מ-5% קבצים שנכשלו).
- **מחזור החיים:** התראה נפתחת פעם אחת, נשלחת שוב פעם ב-24 שעות כל עוד המצב נמשך, ונסגרת כשהוא נפתר.
- **ערוצים:** תמיד לוג מובנה. מייל דרך SMTP כשההגדרות מוגדרות: STARTTLS או SSL על פורט 465, עם אימות תעודה.
- **פריסה:** compose מעביר את ההגדרות ל-worker.
- **מ-3.2:** נוספה בדיקה ל-unlock שנכשל.

**קבצים:**
- `backend/app/modules/ingestion/{alerts,health}.py` (חדשים), `repository.py`, `service.py`, `models.py`.
- `backend/migrations/versions/0010_ingestion_health.py`.
- `backend/app/worker/{main.py,jobs/check_ingestion_health.py}`.
- `backend/app/core/config.py`.
- `backend/app/modules/catalog/{repository,service}.py` (`chains_by_gov_codes`).
- `deploy/{docker-compose.yml,README.md}`.
- הבדיקות.

**ממצאי הסקירה:** 37 ממצאים:
- **תוקנו:** 6 ברמת medium, ו-17 ברמת low.
- **נדחה ל-deferred:** אחד.
- **נדחו לגמרי:** השאר.
- **סטייה מכוונת אחת מהמטריצה:** כשמייל נכשל, ‏`last_sent_at` מתעדכן, כי הלוג קיבל את ההתראה. כך ההתראה לא חוזרת כל שעה.

**המלצה לסקירת המשך:** `true`. תוקנו 6 entries ברמת medium. הסיכון שלא אומת: שליחה דרך SMTP אמיתי.

**אימות:**
- ruff, format ו-mypy נקיים.
- `CARTWISE_REQUIRE_DOCKER=1 pytest`: 757 עברו. בריצה מוקדמת הבדיקות נתקעו פעם אחת, וזה לא חזר בשתי ריצות נוספות.
- `docker compose config`: תקין.
- gitleaks על כל מה שלא נדחף: `no leaks found`.

**סיכונים שנשארו:**
- SMTP אמיתי לא נבדק.
- הבדיקות נתקעו פעם אחת בלי סיבה ברורה.
- הסכום ב-record_drop (ב-deferred).
