"""Firebase ID-token verification against a local RSA key and a fake JWKS (no network)."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.core.config import DEFAULT_FIREBASE_JWKS_URL, Settings, get_settings
from app.core.errors import AppError
from app.core.firebase import (
    FORCED_REFRESH_INTERVAL_SECONDS,
    JwksFirebaseVerifier,
    get_firebase_verifier,
)
from app.core.tokens import issue_device_token
from app.main import create_app

PROJECT = "cartwise-test"
KID = "test-kid"


def _private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


KEY = _private_key()
OTHER_KEY = _private_key()


def _jwks(key: rsa.RSAPrivateKey = KEY, kid: str = KID) -> dict[str, Any]:
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return {"keys": [jwk]}


class FakeJwksClient(jwt.PyJWKClient):
    """The real PyJWKClient, with fetch_data served from memory."""

    def __init__(self, jwks: dict[str, Any]) -> None:
        super().__init__("https://jwks.invalid/keys")
        self.jwks = jwks
        self.fetches = 0

    def fetch_data(self) -> Any:
        self.fetches += 1
        return self.jwks


class DownJwksClient:
    def get_signing_keys(self, refresh: bool = False) -> list[jwt.PyJWK]:
        raise jwt.PyJWKClientConnectionError("unreachable")


class HtmlJwksClient(FakeJwksClient):
    """The endpoint answers with a non-JSON page (e.g. a filtering proxy's block page)."""

    def fetch_data(self) -> Any:
        self.fetches += 1
        return json.loads("<html>blocked</html>")


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _claims(**overrides: object) -> dict[str, object]:
    now = int(datetime.now(UTC).timestamp())
    claims: dict[str, object] = {
        "iss": f"https://securetoken.google.com/{PROJECT}",
        "aud": PROJECT,
        "sub": "firebase-uid-1",
        "iat": now,
        "exp": now + 3600,
        "auth_time": now,
        "name": "Dana Cohen",
        "email": "dana@example.com",
    }
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


def _token(
    claims: dict[str, object] | None = None,
    key: rsa.RSAPrivateKey = KEY,
    kid: str | None = KID,
    alg: str = "RS256",
) -> str:
    headers = {"kid": kid} if kid is not None else {}
    return jwt.encode(claims or _claims(), key, algorithm=alg, headers=headers)


def _verifier(project: str = PROJECT) -> JwksFirebaseVerifier:
    return JwksFirebaseVerifier(project, "https://jwks.invalid/keys", FakeJwksClient(_jwks()))


def _assert_status(token: str, status: int, code: str, verifier: Any = None) -> None:
    with pytest.raises(AppError) as info:
        (verifier or _verifier()).verify(token)
    assert (info.value.status, info.value.code) == (status, code)


def test_valid_token_returns_uid_only() -> None:
    assert _verifier().verify(_token()) == "firebase-uid-1"


def test_jwks_is_cached() -> None:
    client = FakeJwksClient(_jwks())
    verifier = JwksFirebaseVerifier(PROJECT, "https://jwks.invalid/keys", client)
    verifier.verify(_token())
    verifier.verify(_token())
    assert client.fetches == 1


def test_wrong_signature() -> None:
    _assert_status(_token(key=OTHER_KEY), 401, "invalid_token")


def test_unknown_kid() -> None:
    _assert_status(_token(kid="other-kid"), 401, "invalid_token")


def test_unknown_kid_forces_at_most_one_refresh_per_window() -> None:
    client = FakeJwksClient(_jwks())
    clock = Clock()
    verifier = JwksFirebaseVerifier(PROJECT, "https://jwks.invalid/keys", client, clock)
    _assert_status(_token(kid="random-1"), 401, "invalid_token", verifier)
    assert client.fetches == 2  # initial fetch + one forced refresh
    clock.now += FORCED_REFRESH_INTERVAL_SECONDS - 1
    _assert_status(_token(kid="random-2"), 401, "invalid_token", verifier)
    assert client.fetches == 2  # no refetch inside the window
    assert verifier.verify(_token()) == "firebase-uid-1"  # known kids still work
    clock.now += 2
    _assert_status(_token(kid="random-3"), 401, "invalid_token", verifier)
    assert client.fetches == 3


def test_rotated_key_is_picked_up_by_the_forced_refresh() -> None:
    client = FakeJwksClient(_jwks())
    verifier = JwksFirebaseVerifier(PROJECT, "https://jwks.invalid/keys", client, Clock())
    verifier.verify(_token())
    client.jwks = _jwks(OTHER_KEY, kid="rotated")
    assert verifier.verify(_token(key=OTHER_KEY, kid="rotated")) == "firebase-uid-1"


def test_non_json_jwks_is_503() -> None:
    verifier = JwksFirebaseVerifier(PROJECT, "https://jwks.invalid/keys", HtmlJwksClient({}))
    _assert_status(_token(), 503, "auth_unavailable", verifier)


def test_missing_kid() -> None:
    _assert_status(_token(kid=None), 401, "invalid_token")


def test_wrong_audience() -> None:
    _assert_status(_token(_claims(aud="another-project")), 401, "invalid_token")


def test_wrong_issuer() -> None:
    _assert_status(
        _token(_claims(iss="https://securetoken.google.com/another-project")),
        401,
        "invalid_token",
    )


def test_expired() -> None:
    past = int((datetime.now(UTC) - timedelta(hours=2)).timestamp())
    _assert_status(_token(_claims(iat=past, exp=past + 600)), 401, "invalid_token")


def test_issued_in_the_future() -> None:
    future = int((datetime.now(UTC) + timedelta(hours=1)).timestamp())
    _assert_status(_token(_claims(iat=future, exp=future + 3600)), 401, "invalid_token")


def test_auth_time_in_the_future() -> None:
    future = int((datetime.now(UTC) + timedelta(hours=1)).timestamp())
    _assert_status(_token(_claims(auth_time=future)), 401, "invalid_token")


def test_auth_time_within_leeway_is_accepted() -> None:
    soon = int(datetime.now(UTC).timestamp()) + 5
    assert _verifier().verify(_token(_claims(auth_time=soon))) == "firebase-uid-1"


@pytest.mark.parametrize("auth_time", ["yesterday", True])
def test_auth_time_not_a_number(auth_time: object) -> None:
    _assert_status(_token(_claims(auth_time=auth_time)), 401, "invalid_token")


@pytest.mark.parametrize("missing", ["exp", "iat", "sub", "aud", "iss", "auth_time"])
def test_missing_claim(missing: str) -> None:
    claims = _claims()
    del claims[missing]
    _assert_status(_token(claims), 401, "invalid_token")


@pytest.mark.parametrize("sub", ["", "   ", "x" * 129])
def test_bad_sub(sub: str) -> None:
    _assert_status(_token(_claims(sub=sub)), 401, "invalid_token")


def test_hs256_rejected() -> None:
    token = jwt.encode(_claims(), "s" * 40, algorithm="HS256", headers={"kid": KID})
    _assert_status(token, 401, "invalid_token")


@pytest.mark.parametrize("garbage", ["", "abc", "a.b.c"])
def test_garbage(garbage: str) -> None:
    _assert_status(garbage, 401, "invalid_token")


@pytest.mark.parametrize("project", ["", "   "])
def test_unconfigured_project(project: str) -> None:
    verifier = _verifier(project)
    assert not verifier.configured
    _assert_status(_token(), 503, "auth_unavailable", verifier)


def test_jwks_unreachable_is_503() -> None:
    verifier = JwksFirebaseVerifier(PROJECT, "https://jwks.invalid/keys", DownJwksClient())
    _assert_status(_token(), 503, "auth_unavailable", verifier)


def test_settings_defaults() -> None:
    s = Settings()
    assert s.FIREBASE_JWKS_URL == DEFAULT_FIREBASE_JWKS_URL
    assert "securetoken@system.gserviceaccount.com" in DEFAULT_FIREBASE_JWKS_URL


def test_prod_allows_empty_firebase_project() -> None:
    s = Settings(
        ENV="prod",
        DATABASE_URL="postgresql+psycopg://app@db:5432/cartwise",
        DEVICE_TOKEN_SECRET="a" * 32,
    )
    assert s.FIREBASE_PROJECT_ID == ""


# --- HTTP, without a database -----------------------------------------------


@pytest.fixture
def unconfigured_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.delenv("FIREBASE_PROJECT_ID", raising=False)
    get_settings.cache_clear()
    yield TestClient(create_app())
    get_settings.cache_clear()


def test_default_dependency_is_unconfigured(unconfigured_client: TestClient) -> None:
    assert not get_firebase_verifier(get_settings()).configured


def test_link_unconfigured_is_503(unconfigured_client: TestClient) -> None:
    resp = unconfigured_client.post(
        "/v1/auth/link", headers={"Authorization": f"Bearer {_token()}"}, json={}
    )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "auth_unavailable"


def test_link_unconfigured_device_token_is_503(unconfigured_client: TestClient) -> None:
    from app.core.ids import new_id

    device_token, _ = issue_device_token(new_id())
    resp = unconfigured_client.post(
        "/v1/auth/link", headers={"Authorization": f"Bearer {device_token}"}, json={}
    )
    assert resp.status_code == 503


def test_firebase_token_unconfigured_is_503(
    unconfigured_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    token = _token()
    with caplog.at_level("DEBUG"):
        resp = unconfigured_client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "auth_unavailable"
    assert token not in caplog.text


def test_link_without_token_is_401(unconfigured_client: TestClient) -> None:
    resp = unconfigured_client.post("/v1/auth/link", json={})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "auth_required"


def test_me_with_jwks_unreachable_is_503(caplog: pytest.LogCaptureFixture) -> None:
    app = create_app()
    down = JwksFirebaseVerifier(PROJECT, "https://jwks.invalid/keys", DownJwksClient())
    app.dependency_overrides[get_firebase_verifier] = lambda: down
    token = _token()
    with caplog.at_level("DEBUG"):
        resp = TestClient(app).get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "auth_unavailable"
    assert token not in resp.text
    assert token not in caplog.text
