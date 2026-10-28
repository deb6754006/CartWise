# Epic 0 Context: תשתית

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

להקים את השלד שעליו נבנות כל ה-Epics הבאות: backend של FastAPI עם Postgres שרץ מקומית ב-Docker Compose, אפליקציית Expo ל-Android עם RTL, טוקני העיצוב וסרגל הניווט, ו-CI שמריץ בדיקות וסורק סודות על כל שינוי. ה-Epic הזה לא ממש אף FR. המטרה שלו היא לקבע מבנה, מוסכמות וסטאק אחידים, כדי שכל Story שאחריו תתחבר אליהם בלי לבחור מחדש, ושהריפו הציבורי יישאר נקי מסודות מהיום הראשון.

## Stories

- Story 0.1: שלד השרת
- Story 0.2: שלד האפליקציה
- Story 0.3: CI והיגיינת ריפו

## Requirements & Constraints

- **הכול חינמי, ושירותים מעטים ככל האפשר.** שירותים חיצוניים מותרים: רק Firebase Auth, openrouteservice ו-Sentry. לא מוסיפים שירות (תור, cache, DB מנוהל) בלי צורך מוכח.
- **dev מקומי:** `docker compose up` בתיקיית `deploy/` מעלה Postgres 16 (עם PostGIS, pg_trgm ו-unaccent) ואת ה-API. `GET /v1/health` מחזיר 200 עם `{"status":"ok","db":"ok"}`.
- **ריפו ציבורי:** אין בריפו סודות, מפתחות, `.env`, קבלות אמיתיות (`data/receipts-real/`) או נתוני משתמשים. סודות נשמרים רק ב-GitHub Secrets או ב-`.env` בשרת. יש `.env.example` בלי ערכים אמיתיים. gitleaks ב-CI מכשיל ריצה וחוסם merge.
- **לוגים:** JSON מובנה עם `request_id` ו-`subject_hash`. בלי גוף בקשה, בלי תמונות, בלי מיקום, בלי טוקנים ובלי מידע מזהה.
- **עברית ו-RTL:** כל הממשק בעברית ב-RTL, כולל סרגל הניווט. מצב בהיר בלבד. כל הגדלים צריכים להתאים להגדלת גופן של המערכת עד 200%.
- **איכות:** backend: `uv run pytest` (כולל integration מול Postgres ב-testcontainers), `ruff` ו-type check עוברים. mobile: `npm run lint`, `npm run typecheck` ו-`npm test` עוברים.

## Technical Decisions

- **סטאק:** Python 3.13 ומעלה, FastAPI, Pydantic v2, SQLAlchemy 2 ו-Alembic, מנוהלים עם uv. אפליקציה: React Native ו-Expo SDK 56 ב-TypeScript, Android בלבד ב-MVP (iOS בגרסה 1.1).
- **פריסה (prod, לא חלק מה-Epic אבל קובעת את המבנה):** שרת יחיד, Oracle Cloud Always Free בירושלים (ARM64), Docker Compose עם הקונטיינרים `caddy`, `api`, `worker` ו-`db`. בתיקיית `deploy/` יושבים `docker-compose.yml`, `Caddyfile` ו-`backup.sh`. אין staging נפרד.
- **Modular monolith, layered:** קוד אחד משמש גם את ה-API וגם את ה-worker (APScheduler, ותור משימות כטבלת `jobs` ב-Postgres).
  - מבנה: `backend/app/main.py`, `backend/app/core/`, `backend/app/modules/<module>/` עם `models.py`, `schemas.py`, `repository.py`, `service.py` ו-`routes.py`, `backend/app/worker/`, `backend/migrations/` ו-`backend/tests/`.
  - 11 מודולים (ריקים בשלב הזה): identity, lists, catalog, pricing, ingestion, receipts, matching, trust, quota, spending, geo.
  - כיוון התלות: `routes` ← `service` ← `repository` ← `models`. `routes` לא ניגש ל-repository. רק ה-repository של המודול הבעלים ניגש לטבלאות שלו. מודול אחר ניגש לנתונים רק דרך `service.py` של המודול הבעלים.
- **`core` כולל:** הגדרות מ-env, חיבור/session לבסיס הנתונים, `Subject` (stub, כי זה יהיה המקור היחיד לזהות: Firebase ID token או device token של אורח), פורמט שגיאה, כסף ומזהים.
- **מוסכמות API:**
  - REST/JSON תחת `/v1`. endpoints ברבים.
  - שגיאה: `{"error": {"code", "message_he", "details"}}`.
  - כסף כמספר שלם באגורות (`amount_agorot`). זמנים ב-ISO-8601 UTC. מזהים UUIDv7.
  - OpenAPI מיוצר מ-FastAPI, ולקוח TypeScript נוצר ממנו בסקריפט. אין באפליקציה טיפוסי API שנכתבים ידנית.
- **מסד נתונים:** Alembic, והמיגרציה הראשונה מפעילה את ההרחבות postgis, pg_trgm ו-unaccent. מוסכמות: טבלאות ועמודות ב-snake_case ובאנגלית, שמות מודולים ביחיד, `timestamptz` ב-UTC, מיקום כ-`geography(Point, 4326)`, טקסט עברי ב-Unicode NFC.
- **קונפיגורציה:** ספים מספריים יישבו בעתיד ב-`config/thresholds.yaml`, וכל מודול בעלים יטען את שלו.
- **אפליקציה:** RTL מאולץ (`I18nManager.forceRTL`). מחרוזות ב-`mobile/src/i18n/he.json`. טוקנים ב-`mobile/src/theme/tokens.ts`.
- **CI:** GitHub Actions על כל push ו-PR: lint, type check ובדיקות ל-backend ול-mobile, ו-gitleaks. בהמשך יתווספו בניית images ל-ARM64 ל-GHCR ופריסה ב-SSH לפי tag, אבל הם לא נדרשים ב-Epic הזה.
- **כלי בדיקות:** pytest ו-testcontainers עם image של Postgres שכולל PostGIS. בהמשך יתווספו hypothesis ו-schemathesis.

## UX & Interaction Patterns

- **טוקנים (לפי DESIGN.md):**
  - צבעים: surface-base `#FBFAF7`, surface-raised `#FFFFFF`, surface-sunken `#F3F1EC`, ink-primary `#374151`, ink-secondary `#78716C`, primary `#7C3AED`, primary-tint `#F5F3FF`, sky-ink `#0369A1`, צבעי אמינות (ירוק `#16A34A`, צהוב `#CA8A04`, אדום `#DC2626`) שמשמשים לאמינות בלבד, estimate-bg `#FEF3C7` / estimate-ink `#92400E`, error-ink `#B91C1C`. ב-DESIGN.md יש את הרשימה המלאה.
  - טיפוגרפיה: גופן אחד, Rubik. display 24/700, title 20/700, heading 16/600, body 15/400, meta 13/400, price-lg 20/800, price 15/600. ספרות טבלאיות במחירים.
  - רדיוסים: sm 8, md 12, lg 18, full. ריווח: 4, 8, 12, 16, 24, 32, ושוליים של 16 בצדי המסך.
- **סרגל ניווט תחתון, 5 טאבים מימין לשמאל:** בית, רשימות, סריקה (כפתור עגול ומוגבה במרכז, הרכיב היחיד עם צל בולט), הוצאות, פרופיל. רקע `#FFFDF9`, טאב פעיל בסגול primary, לא פעיל ב-ink-secondary. בשלב הזה כל טאב מציג placeholder.
- **סגול לטקסט** הוא תמיד `#7C3AED`. `#8B5CF6` לא עומד בניגודיות AA לטקסט קטן. בלי גרדיאנטים ובלי dark mode.
- **אזורי מגע** של 44 פיקסלים לפחות. אייקונים כיווניים מתהפכים ב-RTL, ואייקונים לא כיווניים לא.

## Cross-Story Dependencies

- Story 0.2 תלויה ב-0.1 בסקריפט יצירת הלקוח, כי הוא נוצר מה-OpenAPI של השרת.
- Story 0.3 מריצה את פקודות ה-lint, ה-type check והבדיקות שמוגדרות ב-0.1 וב-0.2.
- כל ה-Epics הבאות (סדר מומלץ: 1 ← 3 ← 4 ← 2 ← 5 ← 7 ← 6 ← 8 ← 9 ← 10) נשענות על מבנה המודולים, על `core` (Subject, שגיאות, כסף, מזהים) ועל טוקני העיצוב שנקבעים כאן.
