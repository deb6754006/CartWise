# deploy

סביבת dev מקומית: Postgres עם PostGIS, API ו-worker.

```bash
cd deploy
docker compose up -d --build
curl http://localhost:8000/v1/health   # {"status":"ok","db":"ok"}
docker compose down
```

## worker

השירות `worker` משתמש באותו image ובאותו קוד כמו ה-`api`, עם פקודה אחרת: `python -m app.worker.main`. הוא מריץ את המשימות המתוזמנות עם APScheduler. כרגע יש משימה אחת: `purge_deleted`, פעם ביום ב-03:00 UTC. היא מוחקת סופית חשבונות שנמחקו לפני יותר מ-29 יום, כך שכל חשבון נמחק סופית תוך 30 יום.

ה-worker מוגדר עם `restart: unless-stopped`, כך שהוא עולה מחדש אחרי קריסה, ועם `init: true`, כך ש-`docker compose stop` עוצר אותו מיד (SIGTERM), בלי לחכות ל-SIGKILL.

```bash
cd deploy
docker compose logs -f worker      # הלוגים של ה-worker
docker compose restart worker      # הפעלה מחדש אחרי שינוי קוד (אחרי build)
```

הרצה ידנית של המחיקה הסופית, בלי לחכות לתזמון:

```bash
docker compose exec worker python -c "from app.worker.jobs import purge_deleted; print(purge_deleted.run())"
```

המיגרציות רצות ב-`api`, ולכן ה-worker עולה אחריו.

### קליטת קובצי המחירים

ה-worker קולט את הקבצים הרשמיים של שופרסל, רמי לוי וקרפור: job לכל רשת (`ingest_shufersal`, `ingest_rami_levy`, `ingest_carrefour`). הריצה הראשונה מתחילה כמה דקות אחרי שה-worker עולה, ואחר כך כל `INGEST_INTERVAL_HOURS` שעות. בכל ריצה נקלט הקובץ האחרון של כל סוג (Stores, PriceFull, PromoFull) ולכל סניף. קובץ שכבר נקלט, עם אותו שם ואותו תוכן, מדולג. כל ריצה נרשמת ב-`ingestion_runs`, וכל קובץ ב-`ingestion_files`, עם מספר הרשומות והשגיאה, אם הייתה.

ההגדרות (משתני סביבה), עם ברירות המחדל:

| משתנה | ברירת מחדל | |
|---|---|---|
| `INGEST_INTERVAL_HOURS` | `6` | בין 1 ל-6 |
| `SHUFERSAL_PRICES_URL` | `https://prices.shufersal.co.il` | |
| `CERBERUS_URL` | `https://url.publishedprices.co.il` | הפורטל של רמי לוי |
| `CERBERUS_RAMI_LEVY_USERNAME` | `RamiLevi` | שם משתמש ציבורי, בלי סיסמה. לא סוד |
| `CARREFOUR_PRICES_URL` | `https://prices.carrefour.co.il` | |

הרצה ידנית של רשת אחת, בלי לחכות לתזמון:

```bash
docker compose exec worker python -m app.worker.jobs.ingest_chain shufersal   # או rami_levy, carrefour
```

שגיאת תעודה (certificate) בריצה כזו, ברשת מסוננת, נובעת מהסינון. היא נרשמת בשורת הריצה, ולא מבטלים בגללה את בדיקת ה-TLS.

#### סניפים ומיקומים

קובץ ה-Stores של כל רשת יוצר ומעדכן את הסניפים בטבלה `stores`. לסניף פיזי בלי מיקום, או שהכתובת שלו השתנתה, ה-worker מחפש מיקום ב-Nominatim (`NOMINATIM_URL`), לפי "כתובת, שם יישוב". לכל היותר 1,000 בקשות לקובץ, בקצב של בקשה אחת בשנייה. לכן בריצה הראשונה של רשת גדולה, ה-geocoding לבדו עשוי להימשך עד כ-17 דקות. אם Nominatim לא זמין, הקובץ מפסיק לשלוח בקשות, והסניפים שנשארו מנוסים בריצה הבאה. סניף אינטרנטי (`StoreType=2`) לא מקבל מיקום, ולא נכנס להשוואות.

סניף שלא נמצא לו מיקום מקבל `status='needs_location'`, ולא נכנס להשוואות. כתובת שלא נמצאה לא נבדקת שוב במשך 24 שעות. אפשר לראות את הסניפים האלה ולהזין להם מיקום ידני. מיקום ידני לא נדרס בקליטות הבאות, גם אם הכתובת משתנה:

```bash
docker compose exec api python -m scripts.store_locations list                        # מזהה, רשת, קוד סניף, שם, כתובת, קוד יישוב
docker compose exec api python -m scripts.store_locations set <store_id> 31.7767 35.2345   # lat lng
```

שמות היישובים נלקחים מקוד היישוב של הלמ"ס, לפי `backend/app/modules/catalog/data/settlements.csv`. המקור: המאגר "יישובים בישראל" של רשות האוכלוסין וההגירה, ב-data.gov.il (`resource_id=5c78e9fa-c2e2-4771-93ff-7f400a12f7ba`), ברישיון Other (Open).

המיקומים שנמצאים ב-geocoding נשמרים בטבלה, ומקורם ב-OpenStreetMap, דרך Nominatim: © OpenStreetMap contributors, ODbL.

#### מחירים ומבצעים

**PriceFull:** כל פריט עם ברקוד (`ItemType=1`, ‏8 עד 14 ספרות) משויך למוצר עם אותו ברקוד, ואם אין כזה, נוצר מוצר. מוצר קיים שומר על השם הראשון שלו. מחיר נכתב כתצפית `regular` חדשה ב-`price_observations` רק כשהוא שונה מהמחיר האחרון של המוצר באותו סניף. תצפית לא מתעדכנת ולא נמחקת.

**PromoFull:** הקובץ הוא התמונה המלאה של המבצעים בסניף. מבצע שמופיע בו נשמר או מתעדכן, ומבצע של הסניף שנעלם ממנו מסתיים בזמן הריצה. מבצע שאינו בדיוק `0` או `0 - כלל הלקוחות` ב-`ClubID` נשמר כמבצע של מועדון הרשת, כדי לא להציג מחיר שאולי לא זמין. ב-MVP כל המועדונים של רשת (למשל מועדון האשראי ומועדון האפליקציה) מאוחדים למועדון אחד, "מועדון <שם הרשת>". סוג המבצע נקבע לפי הפריט הראשון שמוכר במאגר, ורק הפריטים עם אותו תנאי נכללים בו. במבצע אחוז נשמר האחוז, ולא המחיר של כל פריט.

**פריט בלי ברקוד:** `ItemType=0`, קוד פנימי (למשל ירקות במשקל), או ברקוד לא תקין, כמו ברקוד של אפסים בלבד. פריט כזה מותאם למוצר לפי השם שלו, במנגנון ההתאמה של המוצרים:
- **כינוי קיים:** אם לרשת כבר יש כינוי בלי ברקוד לאותו שם, והוא מצביע על מוצר שלא מוזג למוצר אחר, משתמשים במוצר הזה בלי לחשב ניקוד מחדש.
- **המוצר לא משתנה:** התאמה לפי שם לא משנה את השם, הגודל או היחידה של מוצר קיים. רק מוצר חדש מוצע מקבל את הגודל, היחידה וה"במשקל" של הפריט.
- **אחרת:** ההתאמה לפי טקסט. התוצאה היא התאמה ודאית (`certain`), התאמה לא ודאית (`uncertain`), או מוצר חדש מוצע (`proposed`). בפריט שאינו במשקל, המחיר משמש גם לבדיקת סבירות.
- **תצפית:** פריט שקיבל מוצר מקבל תצפית `regular`, כמו פריט עם ברקוד. אם גם פריט עם ברקוד באותו קובץ מצביע על אותו מוצר, הפריט עם הברקוד קובע.
- **בלי מוצר:** פריט שהשם שלו לא מאפשר התאמה, למשל `***`, לא מקבל מחיר.
- **בלוג `ingestion_prices`:** ‏`internal` (כמה פריטים הועברו להתאמה), ‏`internal_priced`, ‏`internal_unmatched`, ו-`internal_same_product` (פריט שהמוצר שלו כבר קיבל מחיר מפריט אחר בקובץ). הלוג `matching_file_items` סופר כמה פריטים השתמשו בכינוי קיים, וכמה הותאמו בכל אחד מהמצבים.
- **מבצעים:** מבצע על פריט בלי ברקוד עדיין לא נקלט, כי ב-PromoFull יש לפריט רק קוד פנימי, בלי שם.
- **מספר הרשומות:** ה-`records` של קובץ ושל ריצה כולל מעכשיו גם פריטים בלי ברקוד שקיבלו מחיר. לכן הסיכומים קופצים בכ-2% בריצה הראשונה אחרי השינוי.
- **כפילות:** שני פריטים בלי ברקוד עם אותו שם מנורמל, גם עם `ItemCode` שונה: הראשון קובע, והשני נספר כ-`duplicate_name`.

**מה מדולג** (ונספר בלוג `ingestion_prices` או `ingestion_promotions`, בלי שמות ובלי מחירים):
- פריט עם מחיר לא תקין, או מחיר 0 ומטה (`bad_price`), ופריט בלי שם (`no_name`).
- פריט או מבצע שמופיע שוב באותו קובץ (`duplicate`). הראשון קובע. פריט בלי ברקוד עם שם כפול נספר בנפרד (`duplicate_name`).
- מבצע קופון (`coupon`), מבצע שפג תוקפו (`expired`), מבצע בלי תאריך סיום (`no_end`), ומבצע שמסתיים לפני שהוא מתחיל (`bad_dates`).
- מבצע שאף פריט שלו לא מוכר במאגר (`no_product`), ומבצע בלי תנאי שאפשר לחשב, כלומר בלי מחיר מבצע ובלי אחוז (`no_reward`).
- פריטים של מבצע שהתנאי שלהם שונה מזה של הפריט הראשון (`mixed_reward_items`).

קובץ מבצעים שאף מבצע בו לא נשמר, ולפחות אחד מהם דולג כי אין לו מוצר מוכר, נכשל (`no promotion matched a known product`). זה קורה כשקובץ המחירים של הסניף נכשל, או כשהסניף חדש. המבצעים הקיימים של הסניף נשארים כמו שהם, והקובץ ייקלט שוב בריצה הבאה.

קובץ של סניף שלא מופיע עדיין ב-`stores` נכשל (`unknown store`), וייקלט שוב בריצה הבאה. בסוף כל ריצה שקלטה לפחות קובץ אחד מתרענן ה-view ‏`current_prices`, המחיר הנוכחי של כל מוצר בכל סניף.

#### ניטור והתראות

ה-worker מתריע למפעיל בשלושה מצבים, לכל רשת:

- **`stale`:** אין ריצה `succeeded` או `partial` שהסתיימה ב-`INGEST_STALE_HOURS` השעות האחרונות. רשת שאף ריצה שלה לא הצליחה נמדדת מהריצה הראשונה שלה, ורשת שלא רצה אף פעם לא מתריעה. נבדק ב-job השעתי `check_ingestion_health`.
- **`record_drop`:** בריצה, מספר הרשומות בקבצים שנקלטו ירד ביותר מ-`INGEST_RECORD_DROP_PCT` אחוז, לעומת הקובץ הקודם של כל סדרה (למשל ה-PriceFull של אותו סניף). נבדק בסוף כל ריצה.
- **`file_errors`:** יותר מ-`INGEST_FILE_ERROR_PCT` אחוז מהקבצים שנוסו בריצה נכשלו. ריצה שרשימת הקבצים שלה נכשלה נחשבת 100%. נבדק בסוף כל ריצה.

ריצה שכל הקבצים בה דולגו לא משנה את מצב ההתראות של הריצה. לכל רשת ולכל סוג יש לכל היותר התראה פתוחה אחת, בטבלה `ingestion_alerts`. היא נשלחת כשהיא נפתחת, ושוב כל `INGEST_ALERT_REPEAT_HOURS` שעות כל עוד המצב נמשך. כשהמצב נפתר היא נסגרת (`resolved_at`), עם שורת לוג `ingestion_alert_resolved`, בלי מייל.

ההתראה נרשמת תמיד בלוג, כשורת `ingestion_alert` ברמת `ERROR`. בנוסף נשלח מייל, אבל רק כשכל הגדרות ה-SMTP קיימות. המייל נשלח עם STARTTLS ואימות תעודה. בפורט 465 החיבור מוצפן מההתחלה (SMTPS), גם הוא עם אימות תעודה. ההתראה נחשבת נשלחה אם לפחות יעד אחד קיבל אותה, למשל הלוג. יעד שנכשל נרשם בלוג (`ingestion_alert_send_failed`). ה-job השעתי גם שולח תזכורת לכל התראת `record_drop` או `file_errors` פתוחה, שלא נשלחה `INGEST_ALERT_REPEAT_HOURS` שעות.

רק הרשתות שה-worker קולט (שופרסל, רמי לוי וקרפור) נבדקות ל-`stale`. `INGEST_STALE_HOURS` חייב להיות גדול מ-`INGEST_INTERVAL_HOURS`, אחרת ה-worker לא עולה.

`record_drop` מתחיל לעבוד רק אחרי המיגרציה `0010`, כשלכל סדרה יש לפחות שני קבצים שנקלטו אחריה. לשורות הישנות אין `series_key`, והן לא משתתפות בהשוואה.

**איפה מגדירים:** ה-compose מעביר ל-worker את המשתנים האלה מהסביבה של `docker compose`: מהקובץ `deploy/.env`, שלא נכנס ל-git, או מה-shell. בריפו אין להם ערכים. משתנה ריק פירושו ברירת המחדל.

| משתנה | ברירת מחדל | |
|---|---|---|
| `INGEST_STALE_HOURS` | `24` | בין 1 ל-168 |
| `INGEST_RECORD_DROP_PCT` | `30` | בין 1 ל-99 |
| `INGEST_FILE_ERROR_PCT` | `5` | בין 1 ל-99 |
| `INGEST_ALERT_REPEAT_HOURS` | `24` | בין 1 ל-168 |
| `ALERT_SMTP_HOST` | ריק | בלי ערך אין מייל |
| `ALERT_SMTP_PORT` | `587` | STARTTLS |
| `ALERT_SMTP_USER` | ריק | |
| `ALERT_SMTP_PASSWORD` | ריק | **סוד:** רק ב-`.env` שבשרת, לעולם לא בריפו |
| `ALERT_EMAIL_FROM` | ריק | |
| `ALERT_EMAIL_TO` | ריק | כתובת אחת, או כמה מופרדות בפסיקים |

איפה רואים התראות:

```bash
docker compose logs worker | grep ingestion_alert
docker compose exec db psql -U cartwise -c "SELECT chain_id, kind, opened_at, last_sent_at, details FROM ingestion_alerts WHERE resolved_at IS NULL"
```

בדיקה ידנית של `stale`, בלי לחכות לתזמון:

```bash
docker compose exec worker python -m app.worker.jobs.check_ingestion_health
```

## כלי ניהול ההתאמות (Story 4.5)

המפעיל רואה התאמות במחלוקת, תור של התאמות לא ודאיות (המופיעות הכי הרבה קודם), ומוצרים חדשים שממתינים לאישור. הוא יכול לאשר התאמה (היא הופכת לסופית), לאשר מוצר חדש, ולמזג שני מוצרים כפולים. במיזוג, הכינויים, התצפיות, המבצעים וההצבעות של המוצר המוסר עוברים למוצר שנשאר, והמוצר המוסר מסומן `merged_into`. המחירים עצמם לא משתנים.

**מי מפעיל:** משתמש רשום (התחבר עם Google לפחות פעם אחת), שה-Firebase UID שלו מופיע במשתנה `OPERATOR_FIREBASE_UIDS`. כמה מפעילים מפרידים בפסיקים. ברירת המחדל ריקה: אין מפעילים. ה-UID מופיע ב-Firebase Console, תחת Authentication > Users.

**איפה מגדירים:** בקובץ `deploy/.env` שבשרת, שלא נכנס ל-git, או ב-shell. ה-compose מעביר ל-api את `OPERATOR_FIREBASE_UIDS` ואת `FIREBASE_PROJECT_ID`. **לא מכניסים UID אמיתי לריפו.**

```bash
# deploy/.env
FIREBASE_PROJECT_ID=<project id>
OPERATOR_FIREBASE_UIDS=<uid1>,<uid2>
```

**API:** ‏`/v1/admin/matches/disputed`, ‏`/v1/admin/matches/uncertain`, ‏`/v1/admin/products/proposed` (עם `limit`, עד 200, ו-`offset`), ‏`POST /v1/admin/matches/{alias_id}/approve`, ‏`POST /v1/admin/products/{product_id}/approve` ו-`POST /v1/admin/products/merge`. כולם דורשים Firebase ID token של מפעיל. בלי token: ‏401. משתמש שאינו מפעיל, או token של אורח: ‏403. בלי `FIREBASE_PROJECT_ID`: ‏503.

**CLI:** אותם שירותים, ישירות מול בסיס הנתונים. `--operator` הוא ה-Firebase UID של המפעיל, והוא חייב להופיע ב-`OPERATOR_FIREBASE_UIDS` שבסביבה של ה-container. הסקריפט מסרב לרוץ בלי בסיס נתונים.

```bash
docker compose exec api python -m scripts.matches disputed --operator <uid>         # כינוי, רשת, טקסט, מוצר, קולות לכל מוצר
docker compose exec api python -m scripts.matches uncertain --operator <uid>        # כינוי, הופעות, רשת, טקסט, מוצר, ביטחון, מועמדים
docker compose exec api python -m scripts.matches proposed --operator <uid>         # מוצר, מספר כינויים, ברקוד, שם
docker compose exec api python -m scripts.matches approve <alias_id> [<product_id>] --operator <uid>
docker compose exec api python -m scripts.matches approve-product <product_id> --operator <uid>
docker compose exec api python -m scripts.matches merge <keep_id> <remove_id> --operator <uid>
```

לרשימות יש `--limit` (ברירת מחדל 50, עד 200) ו-`--offset`. כל פעולה נרשמת בלוג כשורת `admin_action`, עם הפעולה, המזהים וה-`user_id` הפנימי של המפעיל, בלי טקסט של כינוי.

## רשת עם סינון TLS (למשל NetFree)

אם בניית ה-image נכשלת בשגיאת תעודה (certificate) בשלב `uv sync`, צריך להגדיר את משתנה הסביבה `CARTWISE_EXTRA_CA`, עם הנתיב לקובץ התעודות **המלא** של הרשת. התעודה משמשת רק בזמן הבנייה, ולא נכנסת ל-image.

```bash
# bash
export CARTWISE_EXTRA_CA="C:/ProgramData/NetFree/CA/netfree-ca-bundle-curl.crt"
```

```powershell
# PowerShell
$env:CARTWISE_EXTRA_CA = "C:/ProgramData/NetFree/CA/netfree-ca-bundle-curl.crt"
```
