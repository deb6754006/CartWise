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

## Checks

```sh
cd backend
uv run ruff check . && uv run ruff format --check .
uv run mypy app
uv run pytest -q          # integration tests need Docker (testcontainers)
uv run pytest -q tests/unit
```
