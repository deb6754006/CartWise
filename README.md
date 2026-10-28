# CartWise

אפליקציה למובייל, בעברית, שעונה על שאלה אחת: באיזו חנות בסביבה שלי הכי משתלם לקנות את רשימת הקניות שלי? המחירים מגיעים מקובצי המחירים שהרשתות מפרסמות לפי חוק ומקבלות שמשתמשים סורקים. הממשק בעברית וב-RTL, ל-Android. ראו את [ה-brief](docs/planning-artifacts/briefs/brief-CartWise-2026-10-26/brief.md).

## מבנה התיקיות

| תיקייה | מה יש בה |
|--------|----------|
| `backend/` | השרת: FastAPI, SQLAlchemy 2, Alembic ו-Postgres 16 עם PostGIS. מנוהל עם uv. ראו [`backend/README.md`](backend/README.md). |
| `mobile/` | האפליקציה: Expo SDK 56, React Native ו-TypeScript. ראו [`mobile/README.md`](mobile/README.md). |
| `deploy/` | Docker Compose לסביבת dev מקומית. ראו [`deploy/README.md`](deploy/README.md). |
| `docs/` | מסמכי התכנון והמימוש. |
| `.github/workflows/` | ה-CI. |

## דרישות

- [Docker](https://docs.docker.com/get-docker/) (עם Docker Compose)
- [uv](https://docs.astral.sh/uv/) (מתקין את Python 3.13 בעצמו)
- [Node.js](https://nodejs.org/) 24

## הקמה מהירה

כל בלוק פקודות כאן מתחיל מתיקיית השורש של הריפו. יש שתי דרכים להריץ את ה-backend. בוחרים אחת מהן, כי שתיהן משתמשות בפורט 8000.

**דרך A: הכול ב-Docker** (בסיס נתונים ו-API). ה-API מריץ את המיגרציות של Alembic בעצמו בעלייה.

```sh
cd deploy
docker compose up -d --build
curl http://localhost:8000/v1/health   # {"status":"ok","db":"ok"}
```

**דרך B: רק בסיס הנתונים ב-Docker, וה-API מקומית** (לפיתוח של ה-backend, עם reload):

```sh
cd deploy
docker compose up -d db                # Postgres על localhost:5432
```

```sh
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload   # http://localhost:8000
```

**mobile** (בשתי הדרכים, אחרי שה-API עלה):

```sh
cd mobile
npm install
npx expo start   # "a" לאמולטור Android שרץ, או סריקת קוד ה-QR ב-Expo Go
```

ברירת המחדל של `EXPO_PUBLIC_API_URL` היא `http://10.0.2.2:8000`, שזה המחשב המארח כפי שהוא נראה מהאמולטור של Android. במכשיר פיזי (Expo Go) צריך להגדיר אותה לכתובת ה-LAN של המחשב:

```sh
# bash / zsh
cd mobile
EXPO_PUBLIC_API_URL=http://192.168.1.10:8000 npx expo start
```

```powershell
# PowerShell
cd mobile
$env:EXPO_PUBLIC_API_URL = 'http://192.168.1.10:8000'; npx expo start
```

משתני הסביבה, ואיפה מגדירים כל אחד מהם, מתוארים ב-[`.env.example`](.env.example). לכולם יש ברירת מחדל ל-dev.

## הרצת בדיקות

```sh
# backend (בדיקות ה-integration צריכות Docker)
cd backend
uv sync
uv run ruff check . && uv run ruff format --check .
uv run mypy app
uv run pytest -q
```

```sh
# mobile
cd mobile
npm ci
npm run lint
npm run typecheck
npm test
```

אחרי שינוי ב-API של ה-backend מייצרים מחדש את הלקוח. הסקריפט מריץ את קוד ה-backend דרך uv, ולכן צריך קודם `uv sync` בתיקיית `backend/`:

```sh
cd backend && uv sync && cd ../mobile && npm run gen:api
```

ואז מכניסים ל-commit את `mobile/openapi.json` ואת `mobile/src/api/schema.ts`.

## CI

GitHub Actions ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) רץ על כל push לענפים `main` ו-`dev`, ועל כל pull request. יש בו ארבעה jobs:

- **backend**: ruff, mypy ו-pytest. בדיקות ה-integration רצות עם `CARTWISE_REQUIRE_DOCKER=1`, ולכן לא מדלגות.
- **mobile**: lint, typecheck ו-jest.
- **api-schema**: מריץ `npm run gen:api`, ונכשל אם `openapi.json` או `schema.ts` לא מעודכנים.
- **secrets**: gitleaks. ב-push וב-pull request הוא סורק את ה-commits החדשים שלהם. פעם בשבוע (וגם בהרצה ידנית, `workflow_dispatch`) הוא סורק את כל ההיסטוריה.

ההגדרות של gitleaks נמצאות ב-[`.gitleaks.toml`](.gitleaks.toml): כל חוקי ברירת המחדל, ו-allowlist מצומצם, שכל פריט בו מוגבל לקובץ אחד ולשורה או לתבנית מדויקת:

- פרטי ה-Postgres של dev (`cartwise:cartwise`) ב-`deploy/docker-compose.yml`, ב-`backend/app/core/config.py` וב-`.env.example`.
- ה-URL המזויף בבדיקת כשל החיבור ב-`backend/tests/unit/test_core.py`.
- hashes של sha256 ב-`_bmad/_config/files-manifest.csv`.

## הריפו ציבורי

אין בריפו סודות, מפתחות, תעודות, קובצי `.env`, קבלות אמיתיות (`data/receipts-real/`) או נתוני משתמשים. סודות נשמרים רק ב-GitHub Secrets או ב-`.env` בשרת. gitleaks ב-CI מכשיל כל ריצה שבה נמצא סוד.

## רשת מסוננת (NetFree)

ברשת שמיירטת TLS, שגיאת תעודה בפקודות כמו `docker build`, `npm install` או `uv sync` נגרמת מהסינון ולא מהקוד. לא עוקפים ולא מבטלים בדיקות TLS. לבניית ה-image יש מנגנון אופציונלי, `CARTWISE_EXTRA_CA`, שמתואר ב-[`deploy/README.md`](deploy/README.md). הכללים המלאים ב-[`CLAUDE.md`](CLAUDE.md).

## מסמכים

- [ארכיטקטורה](docs/planning-artifacts/architecture/architecture-CartWise-2026-10-26/ARCHITECTURE-SPINE.md)
- [PRD](docs/planning-artifacts/prds/prd-CartWise-2026-10-26/prd.md)
- [Epics ו-Stories](docs/planning-artifacts/prds/prd-CartWise-2026-10-26/epics.md)
- [עיצוב](docs/planning-artifacts/ux-designs/ux-CartWise-2026-10-26/DESIGN.md) ו-[חוויית משתמש](docs/planning-artifacts/ux-designs/ux-CartWise-2026-10-26/EXPERIENCE.md)
- [מסמכי מימוש](docs/implementation-artifacts/)
