---
title: 'Story 0.1: שלד השרת'
type: 'chore'
created: '2026-10-28'
status: 'done'
baseline_revision: 'cc067644fb604bec3a00501b9df348be411b39d1'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/docs/implementation-artifacts/epic-0-context.md'
  - '{project-root}/docs/planning-artifacts/architecture/architecture-CartWise-2026-10-26/ARCHITECTURE-SPINE.md'
warnings: ['oversized']
deferred:
  - summary: >-
      ייתכן שאין image של postgis/postgis:16-3.4 ל-ARM64 (שרת prod של Oracle).
    evidence: |-
      maybe-false. כדי להכריע: לבדוק את ה-manifest של ה-image (docker manifest inspect) לפני הפריסה, ואם צריך לבחור image מרובה ארכיטקטורות.
    location: >-
      deploy/docker-compose.yml
    severity: medium (unverified)
---

<intent-contract>

## Intent

**Problem:** אין עדיין קוד בריפו. כל ה-Stories הבאות צריכות backend אחד, עם מבנה מודולים, `core` ובסיס נתונים אחידים, כדי שלא יבחרו כל אחת מבנה משלה.

**Approach:** פרויקט Python בתיקייה `backend/` (מנוהל ב-uv), עם FastAPI, SQLAlchemy 2 ו-Alembic. Postgres 16 עם PostGIS, שרץ ב-Docker Compose מתוך `deploy/`. `core` משותף, 11 מודולים ריקים במבנה layered, endpoint בריאות אחד, ובדיקות unit ו-integration.

## Boundaries & Constraints

**Always:**
- מבנה הקוד לפי AD-2: `backend/app/modules/<module>/{models,schemas,repository,service,routes}.py`. כיוון התלות הוא routes ← service ← repository ← models.
- פורמט שגיאה לפי AD-13, בכל תגובת שגיאה, כולל 404, 422 ו-500: `{"error": {"code": str, "message_he": str, "details": object}}`.
- זמנים ב-UTC. כסף כמספר שלם באגורות. מזהים UUIDv7.
- לוגים ב-JSON מובנה, עם `request_id`. בלי גוף בקשה ובלי כותרות Authorization.
- כל הגדרה מגיעה ממשתני סביבה (pydantic-settings). ערכי ברירת המחדל מתאימים לסביבת dev בלבד.

**Never:**
- בלי קובץ `.env` ובלי סודות בריפו. פרטי ההתחברות של Postgres ב-dev (`cartwise`/`cartwise`) מוגדרים ישירות ב-compose, כערכי dev לא סודיים.
- בלי טבלאות תחום, בלי auth אמיתי, בלי worker ובלי CI. כל אלה שייכים ל-Stories אחרות.
- בלי שירותים נוספים ב-compose, מעבר ל-`db` ו-`api`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| בריאות תקינה | `GET /v1/health`, ו-DB זמין | 200, `{"status":"ok","db":"ok"}` | — |
| DB לא זמין | `GET /v1/health`, ו-DB למטה | 503, `{"error":{"code":"db_unavailable","message_he":"בסיס הנתונים לא זמין","details":{}}}` | חריגה נתפסת. אין stack trace בתגובה |
| נתיב לא קיים | `GET /v1/nope` | 404 בפורמט AD-13, עם `code:"not_found"` | handler ל-HTTPException |
| ולידציה | בקשה עם פרמטר לא תקין (בבדיקה, דרך router בדיקה) | 422 בפורמט AD-13, עם `code:"validation_error"` ופירוט ב-`details` | handler ל-RequestValidationError |
| חריגה לא צפויה | חריגה ב-handler | 500 בפורמט AD-13, עם `code:"internal_error"`. הלוג כולל `request_id` | handler כללי |
| request id | עם כותרת `X-Request-ID` או בלעדיה | התגובה מחזירה `X-Request-ID`: הערך שנשלח, או ערך חדש | — |

</intent-contract>

## Code Map

- `backend/` -- לא קיים. פרויקט חדש. הריפו מכיל כרגע רק `docs/` ו-`_bmad/`.
- `docs/implementation-artifacts/epic-0-context.md` -- מקור המוסכמות לסטאק, למבנה ול-API.
- `docs/planning-artifacts/architecture/architecture-CartWise-2026-10-26/ARCHITECTURE-SPINE.md` -- AD-1, AD-2, AD-13 וטבלת הבעלות (11 המודולים, ועוד `core` לטבלת jobs העתידית).
- `deploy/` -- לא קיים. compose ל-dev.

## Tasks & Acceptance

**Execution:**
- `backend/pyproject.toml` -- פרויקט uv, `requires-python >=3.13`. תלויות: fastapi, uvicorn[standard], pydantic-settings, sqlalchemy>=2, psycopg[binary]>=3, alembic. dev: pytest, httpx, testcontainers[postgres], ruff, mypy. הגדרות ruff ו-mypy (strict על `app/`) -- בסיס אחיד לכל ה-Stories.
- `backend/app/core/config.py` -- `Settings` (pydantic-settings): `DATABASE_URL`, `ENV`, `LOG_LEVEL`. ברירת מחדל ל-dev: `postgresql+psycopg://cartwise:cartwise@localhost:5432/cartwise`.
- `backend/app/core/db.py` -- engine, `SessionLocal`, dependency `get_session`, ו-`Base` (DeclarativeBase) עם naming convention ל-constraints.
- `backend/app/core/errors.py` -- `AppError(code, message_he, status, details)`, ו-handlers ל-AppError, ל-HTTPException, ל-RequestValidationError ולחריגה כללית, כולם בפורמט AD-13.
- `backend/app/core/ids.py` -- `new_id() -> uuid.UUID`, לפי UUIDv7 (RFC 9562). אם `uuid.uuid7` קיים, משתמשים בו. אחרת, מימוש מקומי.
- `backend/app/core/money.py` -- `Agorot = int`, `from_shekels(Decimal|str) -> int` (עיגול חצי למעלה), `to_shekels_str(int) -> "12.90"`.
- `backend/app/core/auth.py` -- `Subject` (dataclass: `kind: Literal["user","device","anonymous"]`, `id: str | None`), ו-dependency `get_subject` שמחזיר anonymous. stub, ומחליפים אותו ב-Epic 1.
- `backend/app/core/logging.py` -- logger בפורמט JSON, ו-middleware ל-`X-Request-ID`. הלוג כולל method, path, status ו-duration, בלי body.
- `backend/app/modules/{identity,lists,catalog,pricing,ingestion,receipts,matching,trust,quota,spending,geo}/` -- לכל מודול `__init__.py` ו-5 קבצים. `routes.py` מגדיר `router = APIRouter(prefix="/<module>", tags=["<module>"])` ריק. השאר מכילים docstring קצר בלבד.
- `backend/app/modules/registry.py` -- רשימת ה-routers, ש-`main` רושם תחת `/v1`.
- `backend/app/main.py` -- `create_app()`: handlers, middleware, routers, ו-`GET /v1/health` (`SELECT 1`). מחזיר 200 או 503 לפי המטריצה. `app = create_app()`.
- `backend/alembic.ini`, `backend/migrations/env.py` -- ה-URL נטען מ-`Settings`, ו-`target_metadata = Base.metadata`.
- `backend/migrations/versions/0001_extensions.py` -- `CREATE EXTENSION IF NOT EXISTS` ל-postgis, pg_trgm ו-unaccent. ה-downgrade מוחק אותן.
- `backend/Dockerfile` -- `python:3.13-slim` ו-uv. מריץ `alembic upgrade head`, ואז uvicorn על `0.0.0.0:8000`.
- `deploy/docker-compose.yml` -- `db`: `postgis/postgis:16-3.4`, עם healthcheck ו-volume. `api`: build מ-`../backend`, תלוי ב-db healthy, פורט 8000, ו-`DATABASE_URL` שמצביע על `db`.
- `backend/tests/unit/test_core.py` -- money (עיגול, פורמט), ids (גרסה 7, מונוטוניות במזהים עוקבים), ופורמט שגיאה ל-404, 422 ו-500 (עם TestClient ו-router בדיקה).
- `backend/tests/integration/test_db.py` -- testcontainers `postgis/postgis:16-3.4`: `alembic upgrade head`, ובדיקה ב-`pg_extension` שהותקנו שלוש ההרחבות. `/v1/health` מחזיר 200 מול ה-DB, ו-503 כש-URL לא תקין.
- `backend/.gitignore` -- `.venv/`, `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`.
- `backend/README.md` -- הפקודות להרצה ולבדיקות, בקצרה.

**Acceptance Criteria:**
- Given מחשב עם Docker, when מריצים `docker compose up -d --build` ב-`deploy/`, then `curl http://localhost:8000/v1/health` מחזיר 200 עם `{"status":"ok","db":"ok"}`.
- Given ה-DB רץ, when בודקים `pg_extension`, then postgis, pg_trgm ו-unaccent קיימות.
- Given תיקיית `backend/`, when מריצים את פקודות האימות, then כולן עוברות.
- Given `backend/app/modules/`, then יש בדיוק 11 מודולים, ובכל אחד 5 הקבצים.

## Spec Change Log

## Review Triage Log

## Design Notes

- **Compose:** `deploy/docker-compose.yml` משמש בשלב הזה ל-dev. קובץ prod (עם caddy ו-worker, ARM64) יתווסף בפריסה. image ה-PostGIS ל-ARM64 ייבדק אז, ונרשם כ-deferred.
- **`uuid.uuid7`:** קיים ב-Python 3.14 בלבד. ב-3.13 נדרש מימוש מקומי של כ-15 שורות: 48 ביט של זמן במילישניות, הגרסה, ו-random.

## Verification

**Commands:**
- `cd backend && uv sync` -- expected: מסתיים בלי שגיאה
- `cd backend && uv run ruff check . && uv run ruff format --check .` -- expected: 0 בעיות
- `cd backend && uv run mypy app` -- expected: Success
- `cd backend && uv run pytest -q` -- expected: כל הבדיקות עוברות (integration דורש Docker)
- `cd deploy && docker compose up -d --build && curl -s http://localhost:8000/v1/health` -- expected: `{"status":"ok","db":"ok"}`. ואחר כך `docker compose down`

### 2026-10-28 — Review pass
- verdicts: 46 findings — high 0, medium 6, low 21, false 15, maybe-false 4
- findings:
  - Blind Hunter:
    - `false` `reject` uv.lock חסר ב-diff — הקובץ קיים בדיסק, הוצא מה-diff במכוון בגלל הגודל, וייכנס ל-commit.
    - `low` `patch` README: `cd backend` מתוך deploy/ נכשל — תוקן ל-`cd ../backend`.
    - `low` `patch` unhandled_error_handler לא נגיש או רושם פעמיים — הרישום ל-Exception הוסר. RequestIdMiddleware הוא הנתיב היחיד ל-500.
    - `low` `patch` access log רושם סטטוס שגוי אחרי שהתגובה התחילה — `status = 500` ב-except.
    - `low` `patch` 5xx/422 ב-HTTPException מקבלים קוד או הודעה לא עקביים — מיפוי חדש: 500→internal_error, 5xx→הודעת שרת, 422→validation_error.
    - `medium` `patch` env.py לא מייבא models, ו-autogenerate יציע למחוק אובייקטים של PostGIS — import של 11 המודולים, ומסנני include_name/include_object.
    - `low` `reject` migrations רצות בהפעלת כל container (race בין replicas) — בפיילוט יש מופע API יחיד (AD-1), והתיקון הוא שירות migrate נפרד, לא תיקון ישיר.
    - `maybe-false` `defer` אין image של postgis/postgis ל-ARM64 — רלוונטי לפריסת prod. ייבדק אז.
    - `medium` `patch` integration מדלג בשקט — `CARTWISE_REQUIRE_DOCKER=1` מכשיל במקום לדלג, `-rs`, ועצירת container שהתחיל חלקית.
    - `low` `patch` test_health_db_unavailable ב-integration — הועבר ל-unit.
    - `medium` `patch` בדיקות חסרות: sanitization, לוג, 405, fallback, ענפי uuid, mount — נוספו בדיקות.
    - `medium` `patch` ברירות מחדל של dev מגיעות ל-prod, ו-LOG_LEVEL לא תקין קורס — Literal ל-ENV ול-LOG_LEVEL, ו-validator שחוסם את ה-URL של dev ב-prod.
    - `low` `reject` side effects ב-import (create_app ו-engine גלובלי) — עדיין אין routes שמשתמשים ב-get_session. התיקון הוא refactor, לא תיקון ישיר.
    - `low` `patch` לוג ה-503 בלי סיבה — נוסף `error` עם שם המחלקה.
    - `low` `reject` אין healthcheck ל-api ב-compose — ב-dev לא נדרש. הוספה ולא תיקון.
    - `medium` `patch` `.env` לא מוחרג בריפו ציבורי — נוסף ל-.gitignore ול-.dockerignore.
    - `false` `reject` ה-spec לא ב-diff — במכוון. ה-spec הוא ה-claims_file הנפרד.
  - Verification Gap:
    - `medium` `patch` access log לא נבדק — נוספה בדיקה (קבוצת הבדיקות החסרות).
    - `medium` `patch` sanitization של X-Request-ID לא נבדק — נוספה בדיקה (אותה קבוצה).
    - `medium` `patch` ענפי overflow ונסיגת שעון ב-UUIDv7 — בדיקה עם שעון קבוע (אותה קבוצה).
    - `medium` `patch` skip שקט ב-integration — קבוצת CARTWISE_REQUIRE_DOCKER.
    - `low` `patch` fallback של env.py ל-Settings לא נבדק — נוספה בדיקת integration על DB חדש.
    - `low` `patch` 405 וכותרת Allow לא נבדקו — נוספה בדיקה.
    - `low` `patch` (other) handler ל-Exception לא נגיש — קבוצת הסרת ה-handler.
    - `low` `patch` (other) ENV לא בשימוש — קבוצת ה-validator.
  - Edge Case Hunter:
    - `low` `reject` HTTPException 204/304 עם גוף JSON — אף נתיב לא מעלה 204/304 כחריגה. guard לא נדרש.
    - `low` `patch` קוד 500 לא עקבי — קבוצת המיפוי.
    - `low` `reject` AppError עם סטטוס לא תקין — שימוש פנימי בלבד. guard מוסיף מורכבות.
    - `low` `patch` רישום כפול כשהתגובה כבר התחילה — קבוצת הסרת ה-handler.
    - `low` `patch` access log 200 על כשל — קבוצת `status = 500`.
    - `low` `patch` extra דורס שדות ליבה בלוג — המפתחות כבר לא נדרסים, ונוספה בדיקה.
    - `low` `patch` LOG_LEVEL לא תקין — קבוצת ה-Literal.
    - `low` `patch` money("abc") מעלה InvalidOperation — עכשיו ValueError, ונוספה בדיקה.
    - `low` `reject` סכומים עם יותר מ-26 ספרות — לא מציאותי במחירי מכולת.
    - `low` `reject` health נתקע על שאילתה — ב-dev, ו-connect_timeout קיים. statement_timeout הוא guard נוסף.
    - `low` `reject` race של migrations בין replicas — כמו בממצא של Blind Hunter.
    - `low` `reject` אין הרשאת CREATE EXTENSION — Postgres בהתקנה עצמית, כ-superuser (AD-1).
    - `low` `patch` catch-all ב-fixture, ו-container שנשאר פתוח — קבוצת CARTWISE_REQUIRE_DOCKER.
  - Intent Alignment:
    - `false` `reject` מסלול ה-compose לא נבדק — הורץ ידנית באימות של step-03: health החזיר 200.
    - `false` `reject` uv.lock מחוץ ל-diff — כמו בממצא של Blind Hunter.
    - `false` `reject` "db: ok" רק ברמת החיבור — תואם למטריצה ב-spec (SELECT 1).
    - `medium` `patch` integration שאפשר לדלג עליו — קבוצת CARTWISE_REQUIRE_DOCKER.
    - `false` `reject` mypy רק על app/ — ה-spec קובע במפורש `uv run mypy app`.
    - `low` `patch` mount של ה-routers לא נבדק — נוספה בדיקה (קבוצת הבדיקות החסרות).
    - `false` `reject` money ו-ids כ-helpers של Python — זה מה שה-spec מגדיר.
    - `false` `reject` עבודה שלא התבקשה (לוגים, request-id, CA, README) — לוגים ו-request-id נדרשים ב-Always/Tasks, ו-README ב-Tasks.
    - `false` `reject` (פירוט) הכפילויות בממצאים של Intent תועדו בשורות למעלה.

## Auto Run Result

Status: done

**סיכום:** נבנה שלד backend: FastAPI ו-SQLAlchemy 2 ו-Alembic, מנוהלים ב-uv. Postgres 16 עם PostGIS, pg_trgm ו-unaccent, רץ ב-Docker Compose מתוך `deploy/`. ב-`core` יש: config, db, errors (AD-13), ids (UUIDv7), money (אגורות), auth (Subject stub), ולוג JSON עם X-Request-ID. נבנו 11 מודולים במבנה layered, ו-`GET /v1/health`.

**קבצים:**
- `backend/pyproject.toml`, `backend/uv.lock` -- פרויקט uv, ruff, mypy strict ו-pytest.
- `backend/app/core/*` -- config, db, errors, ids, money, auth, logging.
- `backend/app/modules/<11>/*`, `backend/app/modules/registry.py` -- מודולים ריקים ו-routers תחת `/v1`.
- `backend/app/main.py` -- `create_app` ו-health.
- `backend/migrations/*`, `backend/alembic.ini` -- Alembic, ומיגרציה 0001 שמפעילה את ההרחבות. כולל import של models, ומסנן לאובייקטים של PostGIS.
- `backend/Dockerfile`, `backend/.dockerignore` -- image של ה-API. כולל CA אופציונלי בזמן build, דרך build secret.
- `deploy/docker-compose.yml`, `deploy/README.md`, `deploy/.gitignore`, `deploy/no-extra-ca.crt` -- compose ל-dev. `deploy/.env`, שמכיל את `CARTWISE_EXTRA_CA` של המחשב המקומי, מוחרג מ-git.
- `backend/tests/unit/*`, `backend/tests/integration/*` -- 45 בדיקות.
- `backend/.gitignore`, `backend/README.md`.

**ממצאי הסקירה:** 46 ממצאים. 14 קבוצות patch הוחלו (6 medium, 8 low). פריט אחד נדחה ל-deferred: image של PostGIS ל-ARM64, maybe-false, ייבדק בפריסה. השאר נדחו או נמצאו false, והנימוק של כל אחד רשום ב-Review Triage Log.

**המלצה לסקירת המשך:** `true`. נוספו patches בדרגת medium: נתיב ה-500 עבר ל-middleware בלבד, ונוספו מסנני autogenerate ב-env.py, validator ל-Settings וה-fixture של integration. ה-patches האלה נבדקו בבדיקות, אבל לא עברו סקירה עצמאית נוספת.

**אימות:**
- `uv run ruff check .`, `ruff format --check .` ו-`uv run mypy app` עברו.
- `CARTWISE_REQUIRE_DOCKER=1 uv run pytest -q`: 45 עברו, ואף בדיקה לא דולגה.
- `docker compose up -d --build`, עם `CARTWISE_EXTRA_CA` מ-`deploy/.env` שמצביע על תעודת NetFree המקומית:
  - `/v1/health` החזיר `{"status":"ok","db":"ok"}`, ו-`/v1/nope` החזיר 404 בפורמט AD-13.
  - שלוש ההרחבות נמצאו ב-`pg_extension`.
  - בתוך ה-image אין secret ואין `SSL_CERT_FILE`.

**סיכונים שנשארו:**
- ה-image של postgis ל-ARM64 עדיין לא נבדק.
- downgrade של 0001 על image ה-postgis (שמתקין postgis_topology ו-tiger) נכשל בלי CASCADE. לא נדרש כרגע.
- התאמת `deploy/.env` נדרשת בכל מחשב עם NetFree.
