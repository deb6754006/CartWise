---
name: 'CartWise'
type: architecture-spine
purpose: build-substrate
altitude: initiative
paradigm: 'Modular monolith, hexagonal (ports & adapters); pipes-and-filters for ingestion and receipt pipelines'
scope: 'CartWise MVP: mobile app, API, workers, data store (epics E1–E9)'
status: final
created: '2026-10-26'
updated: '2026-10-26'
binds: [E1, E2, E3, E4, E5, E6, E7, E8, E9, FR-1..FR-51, NFR-1..NFR-26]
sources:
  - ../../prds/prd-CartWise-2026-10-26/prd.md
  - ../../prds/prd-CartWise-2026-10-26/epics.md
  - ../../prds/prd-CartWise-2026-10-26/addendum.md
  - ../../ux-designs/ux-CartWise-2026-10-26/EXPERIENCE.md
  - ../../ux-designs/ux-CartWise-2026-10-26/DESIGN.md
companions:
  - architecture.md
---

# Architecture Spine: CartWise

> המסמך המלא, עם הנימוקים, האלגוריתמים ותוכנית הבדיקות: [architecture.md](architecture.md).
> ההחלטות בקובץ הזה מחייבות. אם יש סתירה, הקובץ הזה קובע.

## Design Paradigm

**Modular monolith, hexagonal.**
- **שירות אחד** (API ו-workers) עם מודולים לפי תחום, שכל אחד מהם בנוי בשכבות של domain, ports ו-adapters.
- **הצינורות** (קליטת קבצים, עיבוד חשבונית) בנויים כ-pipes-and-filters: שלבים טהורים שמחוברים בתור.

```
backend/
  cartwise/
    <module>/            # identity, lists, catalog, pricing, ingestion, receipts, matching, trust, quota, spending
      domain/            # entities, value objects, pure rules - no I/O
      ports.py           # interfaces the domain needs (repositories, gateways)
      service.py         # use cases (application layer)
      adapters/          # postgres repo, http clients, LLM, Routes API
      api.py             # FastAPI router for this module
    shared/              # ids, money, time, errors, auth context
  workers/               # entrypoints for Cloud Run Jobs / task handlers
mobile/                  # Expo app (TypeScript)
```

```mermaid
graph TD
  api[module/api.py] --> svc[module/service.py]
  worker[workers/*] --> svc
  svc --> dom[module/domain]
  svc --> ports[module/ports.py]
  adapters[module/adapters] --> ports
  adapters --> dom
  svc --> shared[shared]
  dom --> shared
  svc -. "other module only via its service.py" .-> svc2[other module service.py]
```

## Invariants & Rules

### AD-1: מבנה המערכת והסטאק [ADOPTED]
- **Binds:** all
- **Prevents:** בחירות סטאק שונות במודולים שונים, או ריבוי שירותים.
- **Rule:**
  - **אפליקציה:** React Native ו-Expo SDK 56, ב-TypeScript.
  - **Backend:** Python 3.13 ומעלה ו-FastAPI, כשירות אחד (API) ב-Cloud Run.
  - **Workers:** אותו קוד, עם entrypoint שונה, ב-Cloud Run Jobs ו-Cloud Tasks.
  - **מסד נתונים:** PostgreSQL ו-PostGIS ב-Cloud SQL.
  - **הזדהות:** Firebase Auth.
  - **אזור:** כל משאב שמעבד נתונים רץ ב-GCP me-west1 (תל אביב).
  - אין מיקרו-שירותים נוספים ב-MVP.

### AD-2: גבולות בין מודולים
- **Binds:** all backend modules
- **Prevents:** מודול שקורא או כותב ישירות לטבלאות של מודול אחר.
- **Rule:**
  - כל טבלה שייכת למודול אחד (ראו טבלת הבעלות).
  - מודול אחר ניגש לנתונים רק דרך `service.py` של המודול הבעלים.
  - domain לא מייבא adapters, FastAPI או SQLAlchemy.

| בעלים | טבלאות |
|---|---|
| identity | users, devices, user_clubs, user_brands, user_prefs |
| lists | shopping_lists, list_items |
| catalog | chains, clubs, stores, brands, categories, products, product_aliases |
| pricing | price_observations, promotions, promotion_products, stock_reports |
| ingestion | ingestion_runs, ingestion_files |
| receipts | receipts, receipt_lines |
| matching | match_candidates, match_votes |
| trust | user_trust, observation_reviews, blocks |
| quota | quota_ledger |
| spending | (views over receipts and receipt_lines; owns no tables) |
| geo | travel_time_cache |

### AD-3: תצפית מחיר היא רשומה שלא משתנה, והמצב נגזר
- **Binds:** pricing, ingestion, receipts, trust, E3, E5, E7
- **Prevents:** עדכון מחיר "במקום" ואובדן היסטוריה. שני מסלולים שכותבים מחיר.
- **Rule:**
  - כל מחיר נכתב כשורה חדשה ב-`price_observations`, עם `source` (official_file או receipt), `price_type` (regular, promo או club) ו-`status` (valid, conflicting, pending_branch או rejected).
  - אין UPDATE למחיר. רק `status` משתנה, ורק דרך `pricing.service` → `trust`.
  - "המחיר הנוכחי" הוא שאילתה או materialized view, ולא עמודה.

### AD-4: כללי העדיפות והאמינות נמצאים במקום אחד
- **Binds:** FR-42..FR-45, pricing, trust
- **Prevents:** חישובי אמינות או עדיפות שונים בהשוואה, בפירוט ובסריקה.
- **Rule:**
  - הפונקציות `trust.domain.resolve_effective_observation()` ו-`trust.domain.reliability_level()` הן המקור היחיד לכללי העדיפות ולרמות האמינות.
  - כל הספים נמצאים ב-`trust.config`.
  - אף מודול אחר לא מחשב צבע אמינות.

### AD-5: חישוב הסל רץ רק בשרת
- **Binds:** FR-18..FR-25, FR-47..FR-49, pricing, quota
- **Prevents:** חישוב באפליקציה שעוקף את המכסה, או חושף את המאגר לגירוד.
- **Rule:**
  - `POST /v1/comparisons` הוא המקום היחיד שמחשב את הסל.
  - ניכוי המכסה וחישוב הסל מתבצעים באותה טרנזקציה לוגית, בדרך הזאת:
    1. שמירה (reservation) של השוואה מהמכסה.
    2. חישוב הסל.
    3. אם החישוב הצליח, אישור הניכוי (commit).
    4. אם החישוב נכשל או שאין מספיק נתונים, החזרת ההשוואה למכסה (release).
  - האפליקציה רק מציגה את התוצאה.

### AD-6: מחיר אפקטיבי הוא פונקציה טהורה
- **Binds:** FR-19, pricing.domain
- **Prevents:** חישובי מבצעים שונים בין ההשוואה לפירוט החנות.
- **Rule:**
  - הפונקציה `pricing.domain.effective_price(item, observations, promotions, user_clubs, qty) -> PriceQuote` היא היחידה שמחשבת מחיר.
  - גם `/comparisons` וגם `/comparisons/:id/stores/:store_id` משתמשים בתוצאה השמורה שלה, ולא מחשבים מחדש.

### AD-7: תמונת חשבונית לא נשמרת אף פעם
- **Binds:** FR-26..FR-30, NFR-11, receipts
- **Prevents:** כתיבה של תמונה לדיסק, לבסיס נתונים, ל-bucket, ללוג או ל-Files API.
- **Rule:**
  - התמונה קיימת רק בזיכרון של בקשת `POST /v1/receipts`.
  - היא נשלחת לספק ה-LLM inline (base64), ולעולם לא דרך Files API.
  - אסור ל-logger לתעד את גוף הבקשה בנתיב הזה.
  - בכל כשל, הבקשה מסתיימת, והתמונה משתחררת מהזיכרון.

### AD-8: טשטוש בשני שלבים, לפני כל ספק חיצוני
- **Binds:** FR-27, FR-28, receipts, mobile
- **Prevents:** מידע מזהה שמגיע לספק ה-LLM או למאגר.
- **Rule:**
  - **במכשיר:** זיהוי של תבניות ספרות (כרטיס, טלפון, מועדון, אישור) וטשטוש של כל השורה. אישור של המשתמש לפני שליחה.
  - **בשרת:** שלב Tesseract בתוך התהליך, שמטשטש שוב לפני קריאת ה-LLM.
  - **אחרי החילוץ:** `receipts.domain.scrub_pii()` על כל טקסט, לפני שמירה.

### AD-9: התאמת מוצרים רק דרך מודול matching
- **Binds:** FR-17, FR-37..FR-41, ingestion, receipts
- **Prevents:** קליטת קבצים וסריקת חשבוניות שיוצרות מוצרים כפולים בדרכים שונות.
- **Rule:**
  - כל כינוי, מקובץ או מחשבונית, עובר דרך `matching.service.match(alias, chain_id, context) -> MatchResult`. התוצאה היא certain, uncertain או new_product_proposal, עם ציון ביטחון.
  - רק matching יוצר שורות ב-`product_aliases`.
  - רק catalog יוצר מוצרים, ורק לבקשת matching או לבקשת מפעיל.

### AD-10: זמני נסיעה רק דרך geo port, עם מטמון
- **Binds:** FR-18, NFR-26, geo
- **Prevents:** קריאות ישירות ל-Routes API מכמה מקומות, ועלויות שלא נשלטות.
- **Rule:**
  - `geo.service.travel_times(origin, store_ids, mode, depart_at)` היא הנקודה היחידה שקוראת ל-Google Routes.
  - לפני הקריאה: סינון לפי מרחק אווירי, וחיפוש במטמון, לפי geohash של נקודת המוצא (דיוק 7), חנות, אמצעי תחבורה וחלון זמן.
  - מיקום המשתמש לא נשמר, רק ה-geohash במטמון (NFR-12).

### AD-11: מכסה כספר תנועות
- **Binds:** FR-47..FR-49, quota
- **Prevents:** מונה מכסה שמשתבש בעדכונים מקבילים, או אובדן של יתרת סריקות.
- **Rule:**
  - `quota_ledger` הוא append-only: grant_monthly, grant_scan, reserve, commit או release.
  - היתרה היא סכום של שורות הספר.
  - המפתח הוא subject_id, כלומר user_id, או device_id אצל משתמש אורח.
  - בהרשמה, השורות של המכשיר עוברות ל-user_id.

### AD-12: זהות ואורחים
- **Binds:** FR-1, FR-2, identity, all endpoints
- **Prevents:** endpoints שמזהים משתמש בדרכים שונות.
- **Rule:**
  - כל בקשה מגיעה עם Firebase ID token (משתמש רשום) או עם device token (אורח), יחד עם אימות App Check (App Attest או Play Integrity).
  - `shared.auth.Subject` הוא המקור היחיד לזהות בצד השרת.
  - נשמרים רק `firebase_uid` ו-email. בלי שם.

### AD-13: ממשק API ופורמט שגיאות
- **Binds:** all endpoints, mobile
- **Prevents:** תגובות, תאריכים או כסף בפורמטים שונים.
- **Rule:**
  - REST/JSON תחת `/v1`.
  - כסף נשמר כמספר שלם באגורות (`amount_agorot`).
  - זמנים בפורמט ISO-8601 UTC.
  - מזהים הם UUIDv7.
  - שגיאה בפורמט `{"error": {"code", "message_he", "details"}}`.
  - OpenAPI מיוצר מ-FastAPI, ולקוח TypeScript נוצר ממנו. אין טיפוסים שנכתבים ידנית באפליקציה.

### AD-14: שלבי הצינורות הם idempotent
- **Binds:** ingestion, receipts, workers
- **Prevents:** תצפיות כפולות כשריצה חוזרת על עצמה.
- **Rule:**
  - **קובץ רשמי:** מזוהה לפי `(chain_id, file_name, file_hash)`. קובץ שכבר נקלט מדולג.
  - **חשבונית:** מזוהה לפי fingerprint, כלומר `sha256(store|datetime|total|receipt_no)` (FR-34).

## Consistency Conventions

| נושא | כלל |
|---|---|
| שמות | טבלאות ועמודות ב-snake_case ובאנגלית. מודולים בלשון יחיד. endpoints ברבים. מונחי המילון ב-PRD §3 ממופים לשמות קבועים: תצפית מחיר = `price_observation`, סניף = `store`, רשת = `chain`, כינוי = `alias`. |
| טקסט בעברית | נשמר ב-Unicode NFC. לחיפוש יש עמודה `name_norm`, שעוברת דרך `catalog.domain.normalize_he()` (הסרת ניקוד, איחוד כתיב). |
| מיקום | `geography(Point, 4326)`. |
| זמן | `timestamptz` ב-UTC. התצוגה באזור הזמן Asia/Jerusalem נעשית רק באפליקציה. |
| לוגים | JSON מובנה עם `request_id` ו-`subject_hash`. בלי גוף בקשה, בלי תמונה, בלי מיקום. |
| קונפיגורציה | ספים מספריים (FR-20, FR-39, FR-43, FR-44, FR-47) ב-`config/thresholds.yaml`, ונטענים במודול הבעלים. |
| UI באפליקציה | הטוקנים מ-DESIGN.md נמצאים ב-`mobile/src/theme/tokens.ts`. RTL מאולץ (`I18nManager.forceRTL`). מחרוזות ב-`he.json`. |

## Deferred

אלה החלטות שלא נקבעות כאן, וייסגרו בשלבים מאוחרים יותר:
- **מנוע embeddings להתאמה:** pgvector עם מודל embeddings. ייבחר לפי ניסוי על מדגם (S4.2).
- **ספק embeddings, וגרסת המודל לחשבוניות:** ייבחרו בניסוי על מדגם חשבוניות (S3.1 והמשך).
- **CDN ו-caching של API:** לא נדרשים בהיקף של ה-MVP.
- **Infrastructure-as-code:** Terraform לעומת gcloud scripts. תלוי בהחלטת הצוות.
- **כלי הניהול (FR-41, FR-46):** UI של אתר פנימי. ב-MVP, endpoints מוגנים ו-UI מינימלי.
