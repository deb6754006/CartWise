import itertools
import logging
import uuid
from decimal import Decimal

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.core import ids
from app.core.errors import AppError
from app.core.ids import new_id
from app.core.money import from_shekels, to_shekels_str
from app.main import create_app

# --- money -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("12.90", 1290),
        ("12.9", 1290),
        ("0.005", 1),
        ("0.004", 0),
        ("1.235", 124),
        ("1.245", 125),
        ("-1.235", -124),
        (Decimal("7"), 700),
        ("0", 0),
    ],
)
def test_from_shekels_rounds_half_up(value: str | Decimal, expected: int) -> None:
    assert from_shekels(value) == expected


@pytest.mark.parametrize("value", ["NaN", "Infinity"])
def test_from_shekels_rejects_non_finite(value: str) -> None:
    with pytest.raises(ValueError):
        from_shekels(value)


@pytest.mark.parametrize(
    ("agorot", "expected"),
    [(1290, "12.90"), (5, "0.05"), (0, "0.00"), (100, "1.00"), (-1290, "-12.90"), (-5, "-0.05")],
)
def test_to_shekels_str(agorot: int, expected: str) -> None:
    assert to_shekels_str(agorot) == expected


# --- ids ---------------------------------------------------------------------


@pytest.mark.parametrize("factory", [new_id, ids._uuid7_local])
def test_ids_are_uuid7(factory: object) -> None:
    assert callable(factory)
    value = factory()
    assert isinstance(value, uuid.UUID)
    assert value.version == 7
    assert value.variant == uuid.RFC_4122


@pytest.mark.parametrize("factory", [new_id, ids._uuid7_local])
def test_ids_are_monotonic(factory: object) -> None:
    assert callable(factory)
    values = [factory() for _ in range(10_000)]
    assert values == sorted(values)
    assert len(set(values)) == len(values)


# --- error format (AD-13) ----------------------------------------------------


def _assert_error_shape(body: dict[str, object], code: str) -> None:
    assert set(body) == {"error"}
    err = body["error"]
    assert isinstance(err, dict)
    assert set(err) == {"code", "message_he", "details"}
    assert err["code"] == code
    assert isinstance(err["message_he"], str)
    assert err["message_he"]


@pytest.fixture
def client() -> TestClient:
    app: FastAPI = create_app()
    test_router = APIRouter(prefix="/_test")

    @test_router.get("/items")
    def items(n: int) -> dict[str, int]:
        return {"n": n}

    @test_router.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret internal detail")

    @test_router.get("/app-error")
    def app_error() -> None:
        raise AppError("quota_exhausted", "המכסה נגמרה", status=409, details={"left": 0})

    app.include_router(test_router)
    return TestClient(app, raise_server_exceptions=False)


def test_404_format(client: TestClient) -> None:
    resp = client.get("/v1/nope")
    assert resp.status_code == 404
    _assert_error_shape(resp.json(), "not_found")


def test_422_format(client: TestClient) -> None:
    resp = client.get("/_test/items", params={"n": "not-a-number"})
    assert resp.status_code == 422
    body = resp.json()
    _assert_error_shape(body, "validation_error")
    errors = body["error"]["details"]["errors"]
    assert errors
    assert errors[0]["loc"] == ["query", "n"]


def test_500_format_and_log_has_request_id(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.ERROR, logger="app.errors")
    resp = client.get("/_test/boom", headers={"X-Request-ID": "req-500"})
    assert resp.status_code == 500
    body = resp.json()
    _assert_error_shape(body, "internal_error")
    assert "secret internal detail" not in resp.text
    assert resp.headers["X-Request-ID"] == "req-500"

    from app.core.logging import JsonFormatter

    records = [r for r in caplog.records if r.getMessage() == "unhandled_exception"]
    assert records
    assert '"request_id": "req-500"' in JsonFormatter().format(records[0])


def test_app_error_format(client: TestClient) -> None:
    resp = client.get("/_test/app-error")
    assert resp.status_code == 409
    body = resp.json()
    _assert_error_shape(body, "quota_exhausted")
    assert body["error"]["details"] == {"left": 0}


def test_request_id_echoed(client: TestClient) -> None:
    resp = client.get("/v1/nope", headers={"X-Request-ID": "abc-123"})
    assert resp.headers["X-Request-ID"] == "abc-123"


def test_request_id_generated(client: TestClient) -> None:
    resp = client.get("/v1/nope")
    assert len(resp.headers["X-Request-ID"]) == 32


def test_modules_layout() -> None:
    from pathlib import Path

    modules_dir = Path(__file__).resolve().parents[2] / "app" / "modules"
    modules = sorted(p.name for p in modules_dir.iterdir() if (p / "__init__.py").exists())
    assert modules == sorted(
        [
            "identity",
            "lists",
            "catalog",
            "pricing",
            "ingestion",
            "receipts",
            "matching",
            "trust",
            "quota",
            "spending",
            "geo",
        ]
    )
    for name in modules:
        for f in ("models.py", "schemas.py", "repository.py", "service.py", "routes.py"):
            assert (modules_dir / name / f).is_file(), f"{name}/{f}"


# --- review follow-ups -------------------------------------------------------


def test_from_shekels_rejects_malformed() -> None:
    with pytest.raises(ValueError):
        from_shekels("abc")


def test_uuid7_local_monotonic_with_fixed_and_backwards_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_ns = 1_800_000_000_000 * 1_000_000
    monkeypatch.setattr(ids.time, "time_ns", lambda: fixed_ns)
    monkeypatch.setattr(ids, "_last_ms", 0)
    monkeypatch.setattr(ids, "_last_seq", 0)
    values = [ids._uuid7_local() for _ in range(5000)]  # > 4096: forces seq overflow
    monkeypatch.setattr(ids.time, "time_ns", lambda: fixed_ns - 10_000 * 1_000_000)
    values += [ids._uuid7_local() for _ in range(100)]
    assert all(a < b for a, b in itertools.pairwise(values))
    assert all(v.version == 7 for v in values)


def test_access_log_record(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="app.access")
    client.get("/v1/nope")
    records = [r for r in caplog.records if r.name == "app.access" and r.getMessage() == "request"]
    assert records
    rec = records[-1]
    assert rec.__dict__["method"] == "GET"
    assert rec.__dict__["path"] == "/v1/nope"
    assert rec.__dict__["status"] == 404
    assert isinstance(rec.__dict__["duration_ms"], int | float)


@pytest.mark.parametrize(
    "sent",
    [b"x" * 129, "בקשה".encode(), b"abc\tdef"],
    ids=["too-long", "non-ascii", "tab"],
)
def test_request_id_sanitized(client: TestClient, sent: bytes) -> None:
    resp = client.get("/v1/nope", headers={"X-Request-ID": sent})
    rid = resp.headers["X-Request-ID"]
    assert len(rid) == 32
    assert rid.encode("latin-1") != sent


def test_405_format(client: TestClient) -> None:
    resp = client.post("/v1/health")
    assert resp.status_code == 405
    _assert_error_shape(resp.json(), "method_not_allowed")
    assert "GET" in resp.headers["Allow"]


@pytest.mark.parametrize(
    ("status", "code"), [(500, "internal_error"), (503, "service_unavailable")]
)
def test_explicit_http_exception_5xx(status: int, code: str) -> None:
    from fastapi import HTTPException

    from app.core.errors import INTERNAL_ERROR_HE

    app = create_app()

    @app.get("/_test/http/{s}")
    def raise_http(s: int) -> None:
        raise HTTPException(status_code=s)

    resp = TestClient(app).get(f"/_test/http/{status}")
    assert resp.status_code == status
    _assert_error_shape(resp.json(), code)
    assert resp.json()["error"]["message_he"] == INTERNAL_ERROR_HE


def test_explicit_http_exception_422() -> None:
    from fastapi import HTTPException

    app = create_app()

    @app.get("/_test/http422")
    def raise_422() -> None:
        raise HTTPException(status_code=422)

    resp = TestClient(app).get("/_test/http422")
    _assert_error_shape(resp.json(), "validation_error")


def test_all_module_routers_mounted_under_v1() -> None:
    from app.modules.registry import ROUTERS

    assert len(ROUTERS) == 11
    saved = [list(r.routes) for r in ROUTERS]
    try:
        for r in ROUTERS:
            r.add_api_route("/_probe", lambda: None)
        paths = set(create_app().openapi()["paths"])
    finally:
        for r, routes in zip(ROUTERS, saved, strict=True):
            r.routes[:] = routes
    for r in ROUTERS:
        assert f"/v1{r.prefix}/_probe" in paths


def test_health_db_unavailable() -> None:
    from app.core.db import make_engine

    bad = make_engine("postgresql+psycopg://nobody:wrong@127.0.0.1:1/none")
    resp = TestClient(create_app(engine=bad)).get("/v1/health")
    assert resp.status_code == 503
    assert resp.json() == {
        "error": {"code": "db_unavailable", "message_he": "בסיס הנתונים לא זמין", "details": {}}
    }


def test_settings_validation() -> None:
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(LOG_LEVEL="LOUD")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Settings(ENV="staging")  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(ENV="prod")
    ok = Settings(ENV="prod", DATABASE_URL="postgresql+psycopg://app@db:5432/cartwise")
    assert ok.ENV == "prod"


def test_json_formatter_core_fields_not_overwritten() -> None:
    import json

    from app.core.logging import JsonFormatter

    record = logging.makeLogRecord(
        {
            "name": "real",
            "msg": "hello",
            "levelname": "INFO",
            "ts": "spoof",
            "level": "spoof",
            "logger": "spoof",
            "request_id": "spoof",
            "custom": 1,
        }
    )
    out = json.loads(JsonFormatter().format(record))
    assert out["level"] == "INFO"
    assert out["logger"] == "real"
    assert out["msg"] == "hello"
    assert out["ts"] != "spoof"
    assert out["custom"] == 1
