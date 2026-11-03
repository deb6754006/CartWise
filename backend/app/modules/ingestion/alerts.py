"""ingestion: where operator alerts go (Story 3.5, FR-16).

Always to the structured log (LogAlertSink). Also by e-mail (EmailAlertSink) when every SMTP
setting is there: STARTTLS (implicit TLS on port 465) with the system's certificate checks,
never turned off. A sink that
fails raises; the caller logs it and tries again later.
"""

import logging
import smtplib
import ssl
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any, Protocol

from app.core.config import Settings
from app.modules.ingestion.models import AlertKind

logger = logging.getLogger("app.ingestion.alerts")

SMTP_TIMEOUT_SECONDS = 30
# The SMTPS port: TLS from the first byte, no STARTTLS.
IMPLICIT_TLS_PORT = 465

KIND_TITLES_HE: Mapping[AlertKind, str] = {
    "stale": "אין קליטה",
    "record_drop": "ירידה במספר הרשומות",
    "file_errors": "שגיאות בקבצים",
}


@dataclass(frozen=True, slots=True)
class AlertMessage:
    chain: str
    kind: AlertKind
    details: Mapping[str, Any] = field(default_factory=dict)
    # When the alert was opened, and when this message is sent (both UTC).
    opened_at: datetime | None = None
    at: datetime | None = None


class AlertSink(Protocol):
    def send(self, alert: AlertMessage) -> None: ...


class LogAlertSink:
    def send(self, alert: AlertMessage) -> None:
        logger.error(
            "ingestion_alert",
            extra={"chain": alert.chain, "kind": alert.kind, "details": dict(alert.details)},
        )


def _utc(value: datetime | str | None) -> str:
    """value (a datetime or an ISO string, as stored in details) in UTC, or "-"."""
    if value is None:
        return "-"
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _detail_lines(alert: AlertMessage) -> list[str]:
    d = alert.details
    if alert.kind == "stale":
        last = d.get("last_success_at")
        return [
            f"לא הייתה קליטה מוצלחת כבר {d.get('hours')} שעות (הסף: {d.get('threshold')}).",
            f"הקליטה המוצלחת האחרונה: {_utc(last) if last else 'אין'}.",
        ]
    if alert.kind == "record_drop":
        return [
            f"מספר הרשומות ירד ב-{d.get('pct')}% (הסף: {d.get('threshold')}%).",
            f"בקבצים הקודמים: {d.get('prev')}. בריצה הזו: {d.get('cur')}.",
            f"סדרות קבצים שהושוו: {d.get('series')}.",
        ]
    return [
        f"{d.get('failed')} מתוך {d.get('attempted')} קבצים נכשלו ({d.get('pct')}%, "
        f"הסף: {d.get('threshold')}%).",
        *([f"שגיאת הריצה: {d['error']}"] if d.get("error") else []),
    ]


def email_subject(alert: AlertMessage) -> str:
    return f"CartWise: התראת קליטה, {alert.chain}: {KIND_TITLES_HE[alert.kind]}"


def email_body(alert: AlertMessage) -> str:
    lines = [
        f"רשת: {alert.chain}",
        f"סוג ההתראה: {KIND_TITLES_HE[alert.kind]} ({alert.kind})",
        *_detail_lines(alert),
        f"נפתחה: {_utc(alert.opened_at)}",
        f"נשלחה: {_utc(alert.at)}",
        "",
        "ההתראה תישלח שוב כל עוד המצב לא נפתר.",
    ]
    return "\n".join(lines) + "\n"


type SmtpFactory = Callable[..., smtplib.SMTP]
type SmtpSslFactory = Callable[..., smtplib.SMTP_SSL]


class EmailAlertSink:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
        sender: str,
        recipients: Sequence[str],
        smtp_factory: SmtpFactory = smtplib.SMTP,
        smtp_ssl_factory: SmtpSslFactory = smtplib.SMTP_SSL,
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self._password = password
        self.sender = sender
        self.recipients = list(recipients)
        self.smtp_factory = smtp_factory
        self.smtp_ssl_factory = smtp_ssl_factory

    def __repr__(self) -> str:  # never shows the password
        return f"EmailAlertSink(host={self.host!r}, port={self.port})"

    def message(self, alert: AlertMessage) -> EmailMessage:
        msg = EmailMessage()
        msg["Subject"] = email_subject(alert)
        msg["From"] = self.sender
        msg["To"] = ", ".join(self.recipients)
        msg.set_content(email_body(alert))
        return msg

    def send(self, alert: AlertMessage) -> None:
        context = ssl.create_default_context()
        smtp: smtplib.SMTP
        if self.port == IMPLICIT_TLS_PORT:
            smtp = self.smtp_ssl_factory(
                self.host, self.port, timeout=SMTP_TIMEOUT_SECONDS, context=context
            )
        else:
            smtp = self.smtp_factory(self.host, self.port, timeout=SMTP_TIMEOUT_SECONDS)
        with smtp:
            if self.port != IMPLICIT_TLS_PORT:
                smtp.starttls(context=context)
            smtp.login(self.user, self._password)
            smtp.send_message(self.message(alert))


def _recipients(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def build_alert_sinks(
    settings: Settings,
    smtp_factory: SmtpFactory = smtplib.SMTP,
    smtp_ssl_factory: SmtpSslFactory = smtplib.SMTP_SSL,
) -> list[AlertSink]:
    """The log always; e-mail too when host, user, password, from and to are all set."""
    sinks: list[AlertSink] = [LogAlertSink()]
    password = settings.ALERT_SMTP_PASSWORD.get_secret_value()
    recipients = _recipients(settings.ALERT_EMAIL_TO)
    configured = (
        settings.ALERT_SMTP_HOST.strip(),
        settings.ALERT_SMTP_USER.strip(),
        password,
        settings.ALERT_EMAIL_FROM.strip(),
    )
    if all(configured) and recipients:
        sinks.append(
            EmailAlertSink(
                host=settings.ALERT_SMTP_HOST.strip(),
                port=settings.ALERT_SMTP_PORT,
                user=settings.ALERT_SMTP_USER.strip(),
                password=password,
                sender=settings.ALERT_EMAIL_FROM.strip(),
                recipients=recipients,
                smtp_factory=smtp_factory,
                smtp_ssl_factory=smtp_ssl_factory,
            )
        )
    return sinks
