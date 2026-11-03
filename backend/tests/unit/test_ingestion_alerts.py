"""Operator alert sinks (Story 3.5): the log, and e-mail over STARTTLS. No real SMTP: every test
injects a fake smtp_factory."""

import logging
import ssl
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any, ClassVar

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.modules.ingestion.alerts import (
    SMTP_TIMEOUT_SECONDS,
    AlertMessage,
    EmailAlertSink,
    LogAlertSink,
    build_alert_sinks,
    email_body,
    email_subject,
)

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
# Made up: example.test is reserved, and no real password is ever written here.
SMTP: dict[str, Any] = {
    "ALERT_SMTP_HOST": "smtp.example.test",
    "ALERT_SMTP_USER": "alerts@example.test",
    "ALERT_SMTP_PASSWORD": SecretStr("not-a-real-password"),
    "ALERT_EMAIL_FROM": "alerts@example.test",
    "ALERT_EMAIL_TO": "operator@example.test, second@example.test",
}

DROP = AlertMessage(
    chain="רשת בדויה",
    kind="record_drop",
    details={"prev": 1000, "cur": 600, "pct": 40.0, "series": 1, "threshold": 30},
    opened_at=NOW,
    at=NOW,
)


class FakeSMTP:
    instances: ClassVar[list["FakeSMTP"]] = []

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self.calls: list[str] = []
        self.context: ssl.SSLContext | None = None
        self.login_args: tuple[str, str] | None = None
        self.sent: list[EmailMessage] = []
        FakeSMTP.instances.append(self)

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *exc: object) -> None:
        self.calls.append("quit")

    def starttls(self, *, context: ssl.SSLContext) -> None:
        self.calls.append("starttls")
        self.context = context

    def login(self, user: str, password: str) -> None:
        self.calls.append("login")
        self.login_args = (user, password)

    def send_message(self, msg: EmailMessage) -> None:
        self.calls.append("send")
        self.sent.append(msg)


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeSMTP.instances = []


def _settings(**overrides: Any) -> Settings:
    return Settings(**{**SMTP, **overrides})


def test_the_log_sink(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR, logger="app.ingestion.alerts"):
        LogAlertSink().send(DROP)
    [record] = caplog.records
    assert record.getMessage() == "ingestion_alert"
    assert record.levelno == logging.ERROR
    assert record.chain == "רשת בדויה"  # type: ignore[attr-defined]
    assert record.kind == "record_drop"  # type: ignore[attr-defined]
    assert record.details == {  # type: ignore[attr-defined]
        "prev": 1000,
        "cur": 600,
        "pct": 40.0,
        "series": 1,
        "threshold": 30,
    }


def test_no_email_with_the_defaults() -> None:
    sinks = build_alert_sinks(Settings())
    assert [type(sink) for sink in sinks] == [LogAlertSink]


@pytest.mark.parametrize(
    "missing",
    [
        "ALERT_SMTP_HOST",
        "ALERT_SMTP_USER",
        "ALERT_SMTP_PASSWORD",
        "ALERT_EMAIL_FROM",
        "ALERT_EMAIL_TO",
    ],
)
def test_any_missing_smtp_setting_leaves_only_the_log(missing: str) -> None:
    empty: Any = SecretStr("") if missing == "ALERT_SMTP_PASSWORD" else "  "
    sinks = build_alert_sinks(_settings(**{missing: empty}))
    assert [type(sink) for sink in sinks] == [LogAlertSink]


def test_every_smtp_setting_adds_email() -> None:
    sinks = build_alert_sinks(_settings(), smtp_factory=FakeSMTP)  # type: ignore[arg-type]
    assert [type(sink) for sink in sinks] == [LogAlertSink, EmailAlertSink]
    email = sinks[1]
    assert isinstance(email, EmailAlertSink)
    assert (email.host, email.port) == ("smtp.example.test", 587)
    assert email.recipients == ["operator@example.test", "second@example.test"]
    assert "not-a-real-password" not in repr(email)


def test_the_port_default_and_override() -> None:
    assert Settings().ALERT_SMTP_PORT == 587
    sinks = build_alert_sinks(_settings(ALERT_SMTP_PORT=2525))
    email = sinks[1]
    assert isinstance(email, EmailAlertSink)
    assert email.port == 2525


def test_email_is_sent_over_starttls_with_certificate_checks() -> None:
    [_, email] = build_alert_sinks(_settings(), smtp_factory=FakeSMTP)  # type: ignore[arg-type]
    email.send(DROP)

    [smtp] = FakeSMTP.instances
    assert (smtp.host, smtp.port, smtp.timeout) == ("smtp.example.test", 587, SMTP_TIMEOUT_SECONDS)
    assert SMTP_TIMEOUT_SECONDS == 30
    assert smtp.calls == ["starttls", "login", "send", "quit"]
    assert smtp.context is not None
    assert smtp.context.verify_mode == ssl.CERT_REQUIRED
    assert smtp.context.check_hostname is True
    assert smtp.login_args == ("alerts@example.test", "not-a-real-password")

    [msg] = smtp.sent
    assert msg["From"] == "alerts@example.test"
    assert msg["To"] == "operator@example.test, second@example.test"
    assert msg["Subject"] == "CartWise: התראת קליטה, רשת בדויה: ירידה במספר הרשומות"
    body = msg.get_content()
    assert "רשת: רשת בדויה" in body
    assert "ירד ב-40.0%" in body
    assert "1000" in body
    assert "600" in body
    assert "2026-11-03 12:00 UTC" in body


def test_a_failing_smtp_raises_to_the_caller() -> None:
    def broken(host: str, port: int, timeout: float) -> Any:
        raise OSError("connection refused")

    [_, email] = build_alert_sinks(_settings(), smtp_factory=broken)
    with pytest.raises(OSError):
        email.send(DROP)


@pytest.mark.parametrize(
    ("alert", "expected"),
    [
        (
            AlertMessage(
                "רשת בדויה",
                "stale",
                {"hours": 25.0, "threshold": 24, "last_success_at": "2026-11-02T11:00:00+00:00"},
                NOW,
                NOW,
            ),
            ["אין קליטה", "25.0 שעות", "האחרונה: 2026-11-02 11:00 UTC."],
        ),
        (
            AlertMessage(
                "רשת בדויה",
                "file_errors",
                {"failed": 2, "attempted": 20, "pct": 10.0, "threshold": 5},
                NOW,
                NOW,
            ),
            ["שגיאות בקבצים", "2 מתוך 20 קבצים נכשלו (10.0%"],
        ),
        (
            AlertMessage(
                "רשת בדויה",
                "file_errors",
                {"failed": 0, "attempted": 0, "pct": 100.0, "threshold": 5, "error": "no files"},
                NOW,
                NOW,
            ),
            ["שגיאת הריצה: no files"],
        ),
    ],
)
def test_the_email_text_of_each_kind(alert: AlertMessage, expected: list[str]) -> None:
    text = email_subject(alert) + "\n" + email_body(alert)
    for part in expected:
        assert part in text


class FakeSMTPSSL(FakeSMTP):
    def __init__(self, host: str, port: int, timeout: float, context: ssl.SSLContext) -> None:
        super().__init__(host, port, timeout)
        self.context = context


def test_port_465_uses_implicit_tls_with_certificate_checks() -> None:
    [_, email] = build_alert_sinks(
        _settings(ALERT_SMTP_PORT=465),
        smtp_factory=FakeSMTP,  # type: ignore[arg-type]
        smtp_ssl_factory=FakeSMTPSSL,  # type: ignore[arg-type]
    )
    email.send(DROP)
    [smtp] = FakeSMTP.instances
    assert isinstance(smtp, FakeSMTPSSL)
    assert (smtp.port, smtp.timeout) == (465, SMTP_TIMEOUT_SECONDS)
    assert smtp.calls == ["login", "send", "quit"]
    assert smtp.context is not None
    assert smtp.context.verify_mode == ssl.CERT_REQUIRED
    assert smtp.context.check_hostname is True


@pytest.mark.parametrize("stale", [1, 6])
def test_stale_hours_must_exceed_the_ingest_interval(stale: int) -> None:
    with pytest.raises(ValueError, match="INGEST_STALE_HOURS"):
        Settings(INGEST_STALE_HOURS=stale, INGEST_INTERVAL_HOURS=6)


def test_stale_hours_above_the_interval_are_accepted() -> None:
    assert Settings(INGEST_STALE_HOURS=7, INGEST_INTERVAL_HOURS=6).INGEST_STALE_HOURS == 7


def test_an_empty_variable_means_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    # compose passes ${VAR:-}: an unset threshold arrives as an empty string.
    monkeypatch.setenv("INGEST_STALE_HOURS", "")
    monkeypatch.setenv("ALERT_SMTP_PORT", "")
    settings = Settings()
    assert (settings.INGEST_STALE_HOURS, settings.ALERT_SMTP_PORT) == (24, 587)
