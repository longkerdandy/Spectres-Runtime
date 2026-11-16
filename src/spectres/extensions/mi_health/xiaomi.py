"""Async Xiaomi account, STS, and health transport with strict host boundaries."""

import base64
import hashlib
import json
from dataclasses import dataclass
from http.cookies import CookieError, SimpleCookie
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from spectres.extensions.mi_health.config import MiHealthConfig
from spectres.extensions.mi_health.core.health import decrypt_response, encrypt_query_params, generate_nonce

_ACCOUNT_BASE = "https://account.xiaomi.com"
_HEALTH_BASE = "https://hlth.io.mi.com"
_STS_HOST = "sts-hlth.io.mi.com"
_SAFE_PREFIX = "&&&START&&&"


class XiaomiError(Exception):
    """Base class for safe Xiaomi operation failures."""


class ProviderUnavailableError(XiaomiError):
    """Xiaomi could not provide a valid expected response."""


class OwnerActionRequiredError(XiaomiError):
    """Xiaomi requires interactive security confirmation."""


class AuthenticationRequiredError(XiaomiError):
    """The current long-lived credential or health session was refused."""


class HealthUnauthorizedError(XiaomiError):
    """A signed health request received HTTP 401."""


class RequestTimeoutError(ProviderUnavailableError):
    """A Xiaomi request exceeded its configured timeout."""


class ChallengeExpiredError(XiaomiError):
    """A QR long poll expired or timed out and needs a fresh challenge."""


@dataclass(frozen=True)
class QrChallenge:
    """Sensitive QR presentation and polling material for one attempt."""

    login_url: str
    qr_payload: str
    lp_url: str
    server_timeout_seconds: int | None


@dataclass(frozen=True)
class LoginResult:
    """Validated account-login output before STS exchange."""

    user_id: str
    c_user_id: str
    pass_token: str
    ssecurity: str
    nonce: str
    location: str


@dataclass(frozen=True)
class HealthSession:
    """Complete session material persisted after a successful STS exchange."""

    user_id: str
    c_user_id: str
    pass_token: str
    service_token: str
    ssecurity: str
    device_id: str


class XiaomiClient:
    """Call only the reviewed China-region Xiaomi protocol endpoints."""

    def __init__(self, config: MiHealthConfig, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        """Initialize the protocol client with an optional test transport."""
        self._config = config
        self._transport = transport

    async def create_qr_challenge(self, *, device_id: str) -> QrChallenge:
        """Create one Mi Health QR approval challenge."""
        response = await self._get(
            f"{_ACCOUNT_BASE}/longPolling/loginUrl",
            params={"sid": "miothealth", "_json": "true"},
            cookies={"deviceId": device_id},
        )
        payload = self._account_payload(response)
        login_url = self._required_text(payload, "loginUrl")
        qr_image_url = self._required_text(payload, "qr")
        lp_url = self._required_text(payload, "lp")
        for url in (login_url, qr_image_url, lp_url):
            self._require_xiaomi_https(url)
        timeout = payload.get("timeout")
        return QrChallenge(
            login_url=login_url,
            qr_payload=login_url,
            lp_url=lp_url,
            server_timeout_seconds=timeout if isinstance(timeout, int) and not isinstance(timeout, bool) else None,
        )

    async def poll_qr(self, *, challenge: QrChallenge, device_id: str) -> LoginResult:
        """Wait once for owner approval and parse the login result."""
        self._require_xiaomi_https(challenge.lp_url)
        try:
            response = await self._get(
                challenge.lp_url,
                cookies={"deviceId": device_id},
                timeout=float(self._config.qr_poll_timeout_seconds),
            )
        except RequestTimeoutError:
            raise ChallengeExpiredError("Mi Health QR challenge timed out") from None
        return self._login_result(response)

    async def renew(self, session: HealthSession) -> LoginResult:
        """Renew the health login with the long-lived account credential."""
        response = await self._get(
            f"{_ACCOUNT_BASE}/pass/serviceLogin",
            params={"sid": "miothealth", "_json": "true"},
            cookies={"userId": session.user_id, "passToken": session.pass_token, "deviceId": session.device_id},
        )
        return self._login_result(
            response,
            known={"userId": session.user_id, "cUserId": session.c_user_id, "passToken": session.pass_token},
        )

    async def exchange_sts(self, result: LoginResult, *, device_id: str) -> HealthSession:
        """Exchange a validated login result for a health service session."""
        parsed = urlsplit(result.location)
        if parsed.scheme != "https" or parsed.hostname != _STS_HOST or parsed.path != "/healthapp/sts":
            raise ProviderUnavailableError("Xiaomi returned an unexpected STS location")
        signature = base64.b64encode(hashlib.sha1(f"nonce={result.nonce}&{result.ssecurity}".encode()).digest()).decode("ascii")
        query = parse_qsl(parsed.query, keep_blank_values=True)
        query.extend((("clientSign", signature), ("_userIdNeedEncrypt", "true")))
        sts_url = urlunsplit(parsed._replace(query=urlencode(query)))
        response = await self._get(sts_url)
        if response.status_code not in (200, 302):
            raise ProviderUnavailableError(f"Xiaomi STS returned HTTP {response.status_code}")
        cookies = self._response_cookies(response)
        service_token = cookies.get("miothealth_serviceToken") or cookies.get("serviceToken")
        if not service_token:
            raise ProviderUnavailableError("Xiaomi STS did not return a health service token")
        return HealthSession(
            user_id=cookies.get("userId", result.user_id),
            c_user_id=cookies.get("cUserId", result.c_user_id),
            pass_token=result.pass_token,
            service_token=service_token,
            ssecurity=result.ssecurity,
            device_id=device_id,
        )

    async def verify_profile(self, session: HealthSession) -> None:
        """Perform one signed Profile read without retaining personal fields."""
        await self.read_profile(session)

    async def read_profile(self, session: HealthSession) -> dict[str, Any]:
        """Read the selected Profile object for immediate canonical mapping."""
        return await self._health_get(
            session,
            path="/healthapp/user/get_miot_user_profile",
            signature_path="/user/get_miot_user_profile",
        )

    async def read_daily(
        self,
        session: HealthSession,
        *,
        key: str,
        start_time: int,
        end_time: int,
        next_key: str | None = None,
    ) -> dict[str, Any]:
        """Read one bounded daily-summary provider page."""
        data: dict[str, Any] = {"tag": "daily_report", "key": key, "start_time": start_time, "end_time": end_time, "reverse": True, "limit": 50}
        if next_key is not None:
            data["next_key"] = next_key
        return await self._health_get(
            session,
            path="/app/v1/data/get_aggregated_fitness_data_by_time",
            signature_path="/app/v1/data/get_aggregated_fitness_data_by_time",
            data=data,
        )

    async def read_raw(
        self,
        session: HealthSession,
        *,
        key: str,
        start_time: int,
        end_time: int,
        next_key: str | None = None,
    ) -> dict[str, Any]:
        """Read one bounded raw sleep or weight provider page."""
        data: dict[str, Any] = {"key": key, "start_time": start_time - 86400, "end_time": end_time, "reverse": True}
        if next_key is not None:
            data["next_key"] = next_key
        return await self._health_get(
            session,
            path="/app/v1/data/get_fitness_data_by_time",
            signature_path="/app/v1/data/get_fitness_data_by_time",
            data=data,
        )

    async def read_workouts(
        self,
        session: HealthSession,
        *,
        start_time: int,
        end_time: int,
        next_key: str | None = None,
    ) -> dict[str, Any]:
        """Read one bounded workout-summary provider page."""
        data: dict[str, Any] = {"start_time": start_time - 1, "end_time": end_time, "reverse": True, "limit": 50}
        if next_key is not None:
            data["next_key"] = next_key
        return await self._health_get(
            session,
            path="/app/v1/data/get_sport_records_by_time",
            signature_path="/app/v1/data/get_sport_records_by_time",
            data=data,
        )

    async def _health_get(
        self,
        session: HealthSession,
        *,
        path: str,
        signature_path: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        nonce = generate_nonce()
        plain = {"data": json.dumps(data, separators=(",", ":"), ensure_ascii=False)} if data is not None else None
        params = encrypt_query_params(path=path, signature_path=signature_path, nonce=nonce, ssecurity=session.ssecurity, params=plain)
        response = await self._get(
            f"{_HEALTH_BASE}{path}",
            params=params,
            cookies={"serviceToken": session.service_token, "cUserId": session.c_user_id},
            headers={"region_tag": self._config.region},
        )
        if response.status_code == 401:
            raise HealthUnauthorizedError("Xiaomi rejected the health session or request signature")
        if response.status_code != 200:
            raise ProviderUnavailableError(f"Xiaomi health read returned HTTP {response.status_code}")
        try:
            payload = decrypt_response(response.text, nonce=nonce, ssecurity=session.ssecurity)
        except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
            raise ProviderUnavailableError("Xiaomi health read returned an invalid encrypted response") from None
        if payload.get("code") != 0 or not isinstance(payload.get("result"), dict):
            raise ProviderUnavailableError("Xiaomi health read returned an unexpected business response")
        result: Any = payload["result"]
        if not isinstance(result, dict):
            raise ProviderUnavailableError("Xiaomi health read returned an invalid result")
        return result

    async def _get(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                follow_redirects=False,
                timeout=timeout or self._config.http_timeout_seconds,
                cookies=cookies,
            ) as client:
                return await client.get(url, params=params, headers=headers)
        except httpx.TimeoutException:
            raise RequestTimeoutError("Xiaomi request timed out") from None
        except httpx.HTTPError:
            raise ProviderUnavailableError("Xiaomi request failed") from None

    def _account_payload(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code != 200:
            raise ProviderUnavailableError(f"Xiaomi account service returned HTTP {response.status_code}")
        return self._json_object(response)

    def _login_result(self, response: httpx.Response, *, known: dict[str, str] | None = None) -> LoginResult:
        payload = self._account_payload(response)
        if payload.get("code") != 0:
            raise AuthenticationRequiredError("Xiaomi refused the account credential")
        security_status = payload.get("securityStatus")
        if isinstance(security_status, int) and security_status != 0:
            raise OwnerActionRequiredError("Xiaomi requires interactive security confirmation")
        cookies = self._response_cookies(response)
        pragma = self._extension_pragma(response)
        stored = known or {}

        def value(name: str) -> str:
            return self._optional_text(payload.get(name)) or cookies.get(name) or stored.get(name) or ""

        nonce = self._optional_text(payload.get("nonce")) or self._optional_text(pragma.get("nonce"))
        result = LoginResult(
            user_id=value("userId"),
            c_user_id=value("cUserId"),
            pass_token=value("passToken"),
            ssecurity=self._optional_text(payload.get("ssecurity")) or self._optional_text(pragma.get("ssecurity")),
            nonce=nonce,
            location=self._optional_text(payload.get("location")),
        )
        if not all((result.user_id, result.c_user_id, result.pass_token, result.ssecurity, result.nonce, result.location)):
            raise ProviderUnavailableError("Xiaomi login omitted required session fields")
        return result

    @staticmethod
    def _json_object(response: httpx.Response) -> dict[str, Any]:
        try:
            text = response.text.strip()
            if text.startswith(_SAFE_PREFIX):
                text = text[len(_SAFE_PREFIX) :]
            payload: Any = json.loads(text)
        except (ValueError, UnicodeDecodeError):
            raise ProviderUnavailableError("Xiaomi returned invalid JSON") from None
        if not isinstance(payload, dict):
            raise ProviderUnavailableError("Xiaomi returned a non-object JSON response")
        return payload

    @staticmethod
    def _response_cookies(response: httpx.Response) -> dict[str, str]:
        values: dict[str, str] = {}
        for raw in response.headers.get_list("set-cookie"):
            parsed: SimpleCookie = SimpleCookie()
            try:
                parsed.load(raw)
            except CookieError:
                continue
            for name, morsel in parsed.items():
                values[name] = morsel.value
        return values

    @staticmethod
    def _extension_pragma(response: httpx.Response) -> dict[str, Any]:
        try:
            payload: Any = json.loads(response.headers.get("Extension-Pragma", "{}"))
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _optional_text(value: Any) -> str:
        if isinstance(value, (bool, float)) or value is None:
            return ""
        if isinstance(value, (str, int)):
            return str(value).strip()
        return ""

    @classmethod
    def _required_text(cls, payload: dict[str, Any], name: str) -> str:
        value = cls._optional_text(payload.get(name))
        if not value:
            raise ProviderUnavailableError(f"Xiaomi QR challenge omitted {name}")
        return value

    @staticmethod
    def _require_xiaomi_https(url: str) -> None:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        if parsed.scheme != "https" or not (host == "xiaomi.com" or host.endswith(".xiaomi.com")):
            raise ProviderUnavailableError("Xiaomi returned an unexpected account URL")
