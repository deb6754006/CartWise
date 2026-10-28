import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import sessionmaker

from app.core.config import DEV_DEVICE_TOKEN_SECRET, Settings, get_settings
from app.core.db import get_session_factory, make_engine
from app.core.errors import AppError
from app.core.ids import new_id
from app.core.tokens import decode_device_token, issue_device_token
from app.main import create_app
from app.modules.identity.schemas import DeviceRegisterIn

PROD_DB = "postgresql+psycopg://app@db:5432/cartwise"


@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # Settings read the process env; keep CI/shell values out of these tests.
    for name in ("ENV", "DATABASE_URL", "DEVICE_TOKEN_SECRET", "DEVICE_TOKEN_TTL_DAYS"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _claims(**overrides: object) -> dict[str, object]:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "sub": str(new_id()),
        "typ": "device",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=1)).timestamp()),
    }
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


def _sign(
    claims: dict[str, object], secret: str = DEV_DEVICE_TOKEN_SECRET, alg: str = "HS256"
) -> str:
    return jwt.encode(claims, secret, algorithm=alg)


def _assert_invalid(token: str) -> None:
    with pytest.raises(AppError) as info:
        decode_device_token(token)
    assert info.value.status == 401
    assert info.value.code == "invalid_token"


def test_issue_and_decode_roundtrip() -> None:
    device_id = new_id()
    token, expires_at = issue_device_token(device_id)
    assert decode_device_token(token) == device_id

    claims = jwt.decode(token, options={"verify_signature": False})
    assert set(claims) == {"sub", "typ", "iat", "exp"}
    assert claims["sub"] == str(device_id)
    assert claims["typ"] == "device"
    assert jwt.get_unverified_header(token)["alg"] == "HS256"
    assert expires_at.tzinfo is not None
    assert claims["exp"] == int(expires_at.timestamp())
    assert claims["exp"] - claims["iat"] == 30 * 24 * 3600


def test_ttl_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEVICE_TOKEN_TTL_DAYS", "7")
    token, _ = issue_device_token(new_id())
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["exp"] - claims["iat"] == 7 * 24 * 3600


def test_secret_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEVICE_TOKEN_SECRET", "o" * 40)
    token, _ = issue_device_token(new_id())
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token, DEV_DEVICE_TOKEN_SECRET, algorithms=["HS256"])


def test_wrong_signature() -> None:
    _assert_invalid(_sign(_claims(), secret="w" * 40))


def test_expired() -> None:
    past = datetime.now(UTC) - timedelta(days=1)
    _assert_invalid(_sign(_claims(iat=int(past.timestamp()) - 60, exp=int(past.timestamp()))))


def test_wrong_typ() -> None:
    _assert_invalid(_sign(_claims(typ="user")))


@pytest.mark.parametrize("missing", ["sub", "typ", "iat", "exp"])
def test_missing_claim(missing: str) -> None:
    claims = _claims()
    del claims[missing]
    _assert_invalid(_sign(claims))


def test_sub_not_uuid() -> None:
    _assert_invalid(_sign(_claims(sub="not-a-uuid")))


def test_other_algorithm_rejected() -> None:
    _assert_invalid(_sign(_claims(), alg="HS512"))
    _assert_invalid(jwt.encode(_claims(), key=None, algorithm="none"))  # type: ignore[arg-type]


@pytest.mark.parametrize("garbage", ["", "abc", "a.b.c"])
def test_garbage(garbage: str) -> None:
    _assert_invalid(garbage)


@pytest.mark.parametrize(
    "secret", [None, "", "   ", "a", "a" * 31, " " + "a" * 31 + " ", DEV_DEVICE_TOKEN_SECRET]
)
def test_prod_requires_device_token_secret(secret: str | None) -> None:
    kwargs: dict[str, str] = {"ENV": "prod", "DATABASE_URL": PROD_DB}
    if secret is not None:
        kwargs["DEVICE_TOKEN_SECRET"] = secret
    with pytest.raises(ValidationError, match="DEVICE_TOKEN_SECRET"):
        Settings(**kwargs)  # type: ignore[arg-type]


def test_prod_accepts_32_char_secret() -> None:
    s = Settings(ENV="prod", DATABASE_URL=PROD_DB, DEVICE_TOKEN_SECRET="a" * 32)
    assert s.DEVICE_TOKEN_SECRET == "a" * 32


def test_prod_secret_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("DATABASE_URL", PROD_DB)
    with pytest.raises(ValidationError, match="DEVICE_TOKEN_SECRET"):
        Settings()
    monkeypatch.setenv("DEVICE_TOKEN_SECRET", "p" * 40)
    assert Settings().DEVICE_TOKEN_SECRET == "p" * 40


@pytest.mark.parametrize("env", ["dev", "test"])
def test_dev_secret_allowed_outside_prod(env: str) -> None:
    s = Settings(ENV=env)  # type: ignore[arg-type]
    assert s.DEVICE_TOKEN_SECRET == DEV_DEVICE_TOKEN_SECRET
    assert s.DEVICE_TOKEN_TTL_DAYS == 30


@pytest.mark.parametrize("ttl", [0, -1, 366, 10**9])
def test_ttl_bounds_rejected(ttl: int) -> None:
    with pytest.raises(ValidationError):
        Settings(DEVICE_TOKEN_TTL_DAYS=ttl)


@pytest.mark.parametrize("ttl", [1, 365])
def test_ttl_bounds_accepted(ttl: int) -> None:
    assert ttl == Settings(DEVICE_TOKEN_TTL_DAYS=ttl).DEVICE_TOKEN_TTL_DAYS


def test_install_id_lone_surrogate_rejected() -> None:
    with pytest.raises(ValidationError, match="string_unicode"):
        DeviceRegisterIn(install_id="\ud800" + "a" * 20)


# --- HTTP, without a database -----------------------------------------------


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_me_without_token(client: TestClient) -> None:
    resp = client.get("/v1/me")
    assert resp.status_code == 401
    assert resp.json() == {
        "error": {"code": "auth_required", "message_he": "נדרשת התחברות", "details": {}}
    }


@pytest.mark.parametrize(
    "header",
    ["Bearer", "Bearer ", "Basic abc", "Token abc", "Bearer not-a-jwt"],
)
def test_me_malformed_authorization(client: TestClient, header: str) -> None:
    resp = client.get("/v1/me", headers={"Authorization": header})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_token"


def test_forged_token_not_logged(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    token = _sign(_claims(sub=str(uuid.uuid4())), secret="f" * 40)
    with caplog.at_level("DEBUG"):
        resp = client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_token"
    assert token not in resp.text
    assert token not in caplog.text
    for record in caplog.records:
        assert token not in str(vars(record))


def test_anonymous_request_does_not_open_a_session() -> None:
    app = create_app()
    opened: list[bool] = []

    def factory() -> object:
        opened.append(True)
        raise AssertionError("session opened")

    app.dependency_overrides[get_session_factory] = lambda: factory
    resp = TestClient(app).get("/v1/me")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "auth_required"
    assert opened == []


def test_db_error_during_device_lookup_is_503() -> None:
    bad = make_engine("postgresql+psycopg://127.0.0.1:1/none")
    app = create_app(engine=bad)
    app.dependency_overrides[get_session_factory] = lambda: sessionmaker(bind=bad)
    token, _ = issue_device_token(new_id())
    resp = TestClient(app).get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 503
    assert resp.json() == {
        "error": {"code": "db_unavailable", "message_he": "בסיס הנתונים לא זמין", "details": {}}
    }
    assert token not in resp.text
