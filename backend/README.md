# CartWise backend

FastAPI, SQLAlchemy 2, Alembic, Postgres 16 + PostGIS. Managed with [uv](https://docs.astral.sh/uv/).

## Run (Docker)

```sh
cd deploy
docker compose up -d --build
curl http://localhost:8000/v1/health   # {"status":"ok","db":"ok"}
docker compose down
```

## Run locally

```sh
cd deploy && docker compose up -d db      # Postgres on localhost:5432
cd ../backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Settings come from environment variables: `DATABASE_URL`, `ENV`, `LOG_LEVEL` (defaults are for dev).

## Dev catalog data

The migrations add no catalog data, so the clubs screen starts empty and brand search finds
nothing. To see them locally, add fictional chains ("רשת א׳", "רשת ב׳", "רשת ג׳"), each with one
club, and fictional brands ("מותג א׳", "מותג ב׳", "מותג ג׳"):

```sh
cd backend
uv run python -m scripts.seed_dev_catalog
```

It is safe to run again, and it refuses to run with `ENV=prod`. In production, real chains are
added after Story 3.1, where they are chosen and approved, and real brands come from the official
files (Epic 3). Until then the app shows its empty states.

## Checks

```sh
cd backend
uv run ruff check . && uv run ruff format --check .
uv run mypy app
uv run pytest -q          # integration tests need Docker (testcontainers)
uv run pytest -q tests/unit
```
