"""The SMTP mailer passes login and encryption settings through to the mail library."""

import aiosmtplib
import pytest
from mindnest_api.mailer import SmtpMailer
from mindnest_core.settings import Settings


async def _send(monkeypatch: pytest.MonkeyPatch, **settings: object) -> dict[str, object]:
    seen: dict[str, object] = {}

    async def fake_send(message: object, **kwargs: object) -> None:
        seen.update(kwargs)

    monkeypatch.setattr(aiosmtplib, "send", fake_send)
    await SmtpMailer(Settings(**settings)).send("a@example.com", "Hi", "Body")  # type: ignore[arg-type]
    return seen


async def test_development_default_is_plain_and_anonymous(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = await _send(monkeypatch)
    assert seen["start_tls"] is False and seen["use_tls"] is False
    assert seen["username"] is None and seen["password"] is None


async def test_starttls_with_login(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = await _send(
        monkeypatch, smtp_security="starttls", smtp_user="apikey", smtp_password="s3cret", smtp_port=587
    )
    assert seen["start_tls"] is True and seen["use_tls"] is False
    assert seen["username"] == "apikey" and seen["password"] == "s3cret"
    assert seen["port"] == 587


async def test_implicit_tls(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = await _send(monkeypatch, smtp_security="tls", smtp_port=465)
    assert seen["use_tls"] is True and seen["start_tls"] is False


async def test_a_mail_failure_is_logged_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(message: object, **kwargs: object) -> None:
        raise OSError("unreachable")

    monkeypatch.setattr(aiosmtplib, "send", boom)
    await SmtpMailer(Settings()).send("a@example.com", "Hi", "Body")
