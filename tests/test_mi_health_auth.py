"""Unit tests for Mi Health credential protection and Xiaomi protocol transport."""

import base64
import json
from typing import Any

import httpx
import pytest

from spectres.extensions.mi_health.config import MiHealthConfig
from spectres.extensions.mi_health.core.health import _Rc4, signed_nonce
from spectres.extensions.mi_health.credentials import CredentialCipher, CredentialProtectionError
from spectres.extensions.mi_health.xiaomi import (
    AuthenticationRequiredError,
    HealthSession,
    HealthUnauthorizedError,
    OwnerActionRequiredError,
    ProviderUnavailableError,
    XiaomiClient,
)

pytestmark = pytest.mark.unit
_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")
_SSECURITY = base64.b64encode(b"synthetic-session-secret").decode("ascii")


def _config(**overrides: Any) -> MiHealthConfig:
    values: dict[str, Any] = {
        "region": "cn",
        "credential_key": _KEY,
        "http_timeout_seconds": 1.0,
        "qr_poll_timeout_seconds": 1,
    }
    values.update(overrides)
    return MiHealthConfig(**values)


def _client(handler: Any) -> XiaomiClient:
    return XiaomiClient(_config(), transport=httpx.MockTransport(handler))


def _login_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "code": 0,
        "securityStatus": 0,
        "userId": "synthetic-user",
        "cUserId": "synthetic-c-user",
        "passToken": "synthetic-pass-token",
        "ssecurity": _SSECURITY,
        "nonce": "900719925474099312345",
        "location": "https://sts-hlth.io.mi.com/healthapp/sts?ticket=synthetic",
    }
    payload.update(overrides)
    return payload


def test_credential_cipher_round_trip_and_owner_binding() -> None:
    """Encrypted values round-trip only for the same owner and purpose."""
    cipher = CredentialCipher(_KEY)
    envelope = cipher.encrypt(user_id="alice", purpose="pass_token", value="synthetic-secret")
    assert "synthetic-secret" not in envelope
    assert cipher.decrypt(user_id="alice", purpose="pass_token", envelope=envelope) == "synthetic-secret"
    with pytest.raises(CredentialProtectionError):
        cipher.decrypt(user_id="bob", purpose="pass_token", envelope=envelope)
    with pytest.raises(CredentialProtectionError):
        cipher.decrypt(user_id="alice", purpose="service_token", envelope=envelope)


@pytest.mark.parametrize(
    "key",
    [None, "", "not base64!", base64.urlsafe_b64encode(bytes(16)).decode("ascii")],
    ids=["missing", "empty", "not-base64", "wrong-length"],
)
def test_credential_cipher_fails_closed_on_missing_or_invalid_key(key: str | None) -> None:
    """Missing or malformed keys produce a safe error without a plaintext echo."""
    with pytest.raises(CredentialProtectionError) as exc_info:
        CredentialCipher(key).encrypt(user_id="alice", purpose="pass_token", value="do-not-leak")
    assert "do-not-leak" not in str(exc_info.value)


def _tampered_ciphertext(envelope: str) -> str:
    """Flip one ciphertext byte while keeping the envelope well-formed."""
    payload = json.loads(envelope)
    raw = bytearray(base64.urlsafe_b64decode(payload["ciphertext"]))
    raw[0] ^= 1
    payload["ciphertext"] = base64.urlsafe_b64encode(bytes(raw)).decode("ascii")
    return json.dumps(payload)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda envelope: "not json",
        lambda envelope: "[]",
        lambda envelope: json.dumps(json.loads(envelope) | {"v": 2}),
        lambda envelope: json.dumps({"v": 1}),
        lambda envelope: json.dumps(json.loads(envelope) | {"nonce": 12}),
        _tampered_ciphertext,
    ],
    ids=["not-json", "not-object", "unknown-version", "missing-fields", "non-string-nonce", "tampered-ciphertext"],
)
def test_credential_cipher_rejects_malformed_envelopes(mutate: Any) -> None:
    """Corrupt, foreign-version, or tampered envelopes all fail with one safe error."""
    cipher = CredentialCipher(_KEY)
    envelope = cipher.encrypt(user_id="alice", purpose="pass_token", value="synthetic-secret")
    with pytest.raises(CredentialProtectionError, match="cannot be decrypted"):
        cipher.decrypt(user_id="alice", purpose="pass_token", envelope=mutate(envelope))


async def test_qr_challenge_and_poll_validate_hosts_and_preserve_nonce() -> None:
    """QR creation and approval use deviceId and retain exact decimal nonce text."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/longPolling/loginUrl":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "loginUrl": "https://account.xiaomi.com/login",
                    "qr": "https://c3.account.xiaomi.com/qr",
                    "lp": "https://c3.lp.account.xiaomi.com/poll",
                    "timeout": 300,
                },
            )
        return httpx.Response(200, content=f"&&&START&&&{json.dumps(_login_payload())}")

    client = _client(handler)
    challenge = await client.create_qr_challenge(device_id="0123456789ABCDEF")
    result = await client.poll_qr(challenge=challenge, device_id="0123456789ABCDEF")
    assert challenge.qr_payload == challenge.login_url == "https://account.xiaomi.com/login"
    assert challenge.qr_payload != "https://c3.account.xiaomi.com/qr"
    assert challenge.server_timeout_seconds == 300
    assert result.nonce == "900719925474099312345"
    assert [request.headers.get("cookie") for request in seen] == ["deviceId=0123456789ABCDEF", "deviceId=0123456789ABCDEF"]


async def test_sts_exchange_uses_no_account_cookies() -> None:
    """STS receives a signature but no account Cookie header."""
    seen: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen
        seen = request
        return httpx.Response(
            200,
            headers={"set-cookie": ("serviceToken=synthetic-service-token; Path=/; Domain=sts-hlth.io.mi.com, userId=sts-user; Path=/, cUserId=sts-c-user; Path=/")},
        )

    from spectres.extensions.mi_health.xiaomi import LoginResult

    login = LoginResult(
        user_id="synthetic-user",
        c_user_id="synthetic-c-user",
        pass_token="synthetic-pass-token",
        ssecurity=_SSECURITY,
        nonce="12345678901234567890",
        location="https://sts-hlth.io.mi.com/healthapp/sts?ticket=synthetic",
    )
    session = await _client(handler).exchange_sts(login, device_id="0123456789ABCDEF")
    assert session.service_token == "synthetic-service-token"
    assert seen is not None
    assert "cookie" not in seen.headers
    assert seen.url.params["ticket"] == "synthetic"
    assert seen.url.params["_userIdNeedEncrypt"] == "true"
    assert seen.url.params["clientSign"]


async def test_renewal_can_retain_known_identity_fields() -> None:
    """Renewal uses the existing account fields when the response omits them."""
    session = HealthSession(
        user_id="synthetic-user",
        c_user_id="synthetic-c-user",
        pass_token="synthetic-pass-token",
        service_token="old-service-token",
        ssecurity=_SSECURITY,
        device_id="0123456789ABCDEF",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert "passToken=synthetic-pass-token" in request.headers["cookie"]
        return httpx.Response(200, json={"code": 0, "securityStatus": 0, "ssecurity": _SSECURITY, "nonce": 123, "location": session.device_id})

    result = await _client(handler).renew(session)
    assert result.user_id == "synthetic-user"
    assert result.c_user_id == "synthetic-c-user"
    assert result.pass_token == "synthetic-pass-token"
    assert result.nonce == "123"


async def test_profile_success_and_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """Profile validates the decrypted business envelope and exposes 401 separately."""
    session = HealthSession("user", "c-user", "pass", "service", _SSECURITY, "device")
    monkeypatch.setattr("spectres.extensions.mi_health.xiaomi.generate_nonce", lambda: "AAECAwQFBgdick1teQ==")
    nonce = "AAECAwQFBgdick1teQ=="
    key = base64.b64decode(signed_nonce(session.ssecurity, nonce))
    body = base64.b64encode(_Rc4(key).apply(json.dumps({"code": 0, "result": {"private": "not-read"}}).encode())).decode()

    def success(request: httpx.Request) -> httpx.Response:
        assert request.headers["region_tag"] == "cn"
        assert "passToken" not in request.headers.get("cookie", "")
        assert "data" not in request.url.params
        return httpx.Response(200, text=body)

    await _client(success).verify_profile(session)

    with pytest.raises(HealthUnauthorizedError):
        await _client(lambda request: httpx.Response(401, json={"code": 0})).verify_profile(session)


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        (_login_payload(securityStatus=16), OwnerActionRequiredError),
        (_login_payload(code=70016), AuthenticationRequiredError),
        (_login_payload(nonce=1.5), ProviderUnavailableError),
    ],
)
async def test_login_failures_are_safe(payload: dict[str, Any], error: type[Exception], caplog: pytest.LogCaptureFixture) -> None:
    """Security, refusal, and malformed nonce failures do not leak session fields."""
    challenge = await _client(
        lambda request: httpx.Response(
            200,
            json={"code": 0, "loginUrl": "https://account.xiaomi.com/login", "qr": "https://account.xiaomi.com/qr", "lp": "https://account.xiaomi.com/poll"},
        )
    ).create_qr_challenge(device_id="device")
    with pytest.raises(error) as exc_info:
        await _client(lambda request: httpx.Response(200, json=payload)).poll_qr(challenge=challenge, device_id="device")
    assert "synthetic-pass-token" not in str(exc_info.value)
    assert "synthetic-pass-token" not in caplog.text


async def test_unexpected_qr_host_is_rejected() -> None:
    """A challenge cannot redirect polling material to an untrusted host."""
    with pytest.raises(ProviderUnavailableError):
        await _client(
            lambda request: httpx.Response(
                200,
                json={"code": 0, "loginUrl": "https://example.com/login", "qr": "https://account.xiaomi.com/qr", "lp": "https://account.xiaomi.com/poll"},
            )
        ).create_qr_challenge(device_id="device")


async def test_qr_poll_timeout_requires_a_fresh_challenge() -> None:
    """A bounded long-poll timeout maps to a terminal challenge result."""
    from spectres.extensions.mi_health.xiaomi import ChallengeExpiredError

    challenge = await _client(
        lambda request: httpx.Response(
            200,
            json={"code": 0, "loginUrl": "https://account.xiaomi.com/login", "qr": "https://account.xiaomi.com/qr", "lp": "https://account.xiaomi.com/poll"},
        )
    ).create_qr_challenge(device_id="device")

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    with pytest.raises(ChallengeExpiredError):
        await _client(timeout).poll_qr(challenge=challenge, device_id="device")
