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

**מה מדולג** (ונספר בלוג `ingestion_prices` או `ingestion_promotions`, בלי שמות ובלי מחירים):
- פריט בלי ברקוד (`no_barcode`): `ItemType=0`, קוד פנימי (למשל ירקות במשקל), או ברקוד של אפסים בלבד. ההתאמה שלו תגיע בהמשך.
- פריט עם מחיר לא תקין, או מחיר 0 ומטה (`bad_price`), ופריט בלי שם (`no_name`).
- פריט או מבצע שמופיע שוב באותו קובץ (`duplicate`). הראשון קובע.
- מבצע קופון (`coupon`), מבצע שפג תוקפו (`expired`), מבצע בלי תאריך סיום (`no_end`), ומבצע שמסתיים לפני שהוא מתחיל (`bad_dates`).
- מבצע שאף פריט שלו לא מוכר במאגר (`no_product`), ומבצע בלי תנאי שאפשר לחשב, כלומר בלי מחיר מבצע ובלי אחוז (`no_reward`).
- פריטים של מבצע שהתנאי שלהם שונה מזה של הפריט הראשון (`mixed_reward_items`).

קובץ מבצעים שאף מבצע בו לא נשמר, ולפחות אחד מהם דולג כי אין לו מוצר מוכר, נכשל (`no promotion matched a known product`). זה קורה כשקובץ המחירים של הסניף נכשל, או כשהסניף חדש. המבצעים הקיימים של הסניף נשארים כמו שהם, והקובץ ייקלט שוב בריצה הבאה.

קובץ של סניף שלא מופיע עדיין ב-`stores` נכשל (`unknown store`), וייקלט שוב בריצה הבאה. בסוף כל ריצה שקלטה לפחות קובץ אחד מתרענן ה-view ‏`current_prices`, המחיר הנוכחי של כל מוצר בכל סניף.

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
