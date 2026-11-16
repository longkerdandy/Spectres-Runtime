"""Owner-scoped Mi Health binding and QR-attempt persistence."""

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from spectres.extensions.mi_health.config import MiHealthConfig
from spectres.extensions.mi_health.credentials import CredentialCipher
from spectres.extensions.mi_health.models import MiHealthBinding, MiHealthQrAttempt
from spectres.extensions.mi_health.xiaomi import (
    AuthenticationRequiredError,
    ChallengeExpiredError,
    HealthSession,
    OwnerActionRequiredError,
    QrChallenge,
    XiaomiClient,
)
from spectres.health.ingestion import HealthIngestionService


class BindingError(Exception):
    """Base class for safe binding-state failures."""


class NotBoundError(BindingError):
    """The current owner has no Mi Health binding."""


class BindingExistsError(BindingError):
    """The current owner already has an authenticated binding."""


class ChallengeNotFoundError(BindingError):
    """The QR challenge is unknown, terminal, or owned by another user."""


@dataclass(frozen=True)
class BindingStatus:
    """Non-sensitive public binding state."""

    status: str
    region: str
    bound_at: datetime | None
    last_verified_at: datetime | None
    last_renewed_at: datetime | None


@dataclass(frozen=True)
class QrAttemptChallenge:
    """Public QR challenge data returned to its owner."""

    challenge_id: str
    qr_payload: str
    created_at: datetime
    server_timeout_seconds: int | None


class MiHealthBindingService:
    """Manage only the verified owner's Mi Health authentication state."""

    def __init__(
        self,
        *,
        config: MiHealthConfig,
        session_factory: sessionmaker[Session],
        cipher: CredentialCipher,
        xiaomi: XiaomiClient,
        ingestion: HealthIngestionService,
    ) -> None:
        """Inject the Extension-local configuration, database, cipher, and transport."""
        self._config = config
        self._session_factory = session_factory
        self._cipher = cipher
        self._xiaomi = xiaomi
        self._ingestion = ingestion

    @property
    def session_factory(self) -> sessionmaker[Session]:
        """Return the Extension-local session factory for session orchestration."""
        return self._session_factory

    @property
    def cipher(self) -> CredentialCipher:
        """Return the shared credential cipher."""
        return self._cipher

    def status(self, user_id: str) -> BindingStatus:
        """Read local status without contacting Xiaomi."""
        with self._session_factory() as session:
            binding = session.get(MiHealthBinding, user_id)
            return self._status(binding)

    async def create_qr_challenge(self, user_id: str) -> QrAttemptChallenge:
        """Create a challenge and supersede the owner's previous active attempt."""
        with self._session_factory() as session:
            binding = session.get(MiHealthBinding, user_id)
            if binding is not None and binding.status == "authenticated":
                raise BindingExistsError("Mi Health is already bound; unbind before binding another account")
            device_id = binding.device_id if binding is not None else secrets.token_hex(8).upper()
        challenge = await self._xiaomi.create_qr_challenge(device_id=device_id)
        attempt_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        with self._session_factory() as session, session.begin():
            binding = session.get(MiHealthBinding, user_id, with_for_update=True)
            if binding is not None and binding.status == "authenticated":
                raise BindingExistsError("Mi Health is already bound; unbind before binding another account")
            session.execute(delete(MiHealthQrAttempt).where(MiHealthQrAttempt.user_id == user_id))
            session.add(
                MiHealthQrAttempt(
                    id=attempt_id,
                    user_id=user_id,
                    device_id=device_id,
                    lp_ciphertext=self._cipher.encrypt(user_id=user_id, purpose="qr_lp", value=challenge.lp_url),
                    state="waiting",
                    server_timeout_seconds=challenge.server_timeout_seconds,
                    created_at=now,
                    updated_at=now,
                )
            )
        return QrAttemptChallenge(
            challenge_id=attempt_id,
            qr_payload=challenge.qr_payload,
            created_at=now,
            server_timeout_seconds=challenge.server_timeout_seconds,
        )

    async def poll_qr_challenge(self, user_id: str, challenge_id: str) -> BindingStatus:
        """Poll one active attempt and atomically persist an approved session."""
        attempt, lp_url = self._attempt(user_id, challenge_id)
        challenge = QrChallenge(
            login_url="",
            qr_payload="",
            lp_url=lp_url,
            server_timeout_seconds=attempt.server_timeout_seconds,
        )
        try:
            result = await self._xiaomi.poll_qr(challenge=challenge, device_id=attempt.device_id)
            health_session = await self._xiaomi.exchange_sts(result, device_id=attempt.device_id)
        except (OwnerActionRequiredError, AuthenticationRequiredError, ChallengeExpiredError):
            with self._session_factory() as session, session.begin():
                owned_attempt = session.get(MiHealthQrAttempt, challenge_id, with_for_update=True)
                if owned_attempt is not None and owned_attempt.user_id == user_id:
                    session.delete(owned_attempt)
                binding = session.get(MiHealthBinding, user_id, with_for_update=True)
                if binding is not None:
                    binding.status = "reauth_required"
            raise
        with self._session_factory() as session, session.begin():
            owned_attempt = session.get(MiHealthQrAttempt, challenge_id, with_for_update=True)
            if owned_attempt is None or owned_attempt.user_id != user_id:
                raise ChallengeNotFoundError("Mi Health QR challenge was not found")
            binding = session.get(MiHealthBinding, user_id, with_for_update=True)
            self._write_session(session, binding, user_id=user_id, health_session=health_session)
            session.delete(owned_attempt)
        return self.status(user_id)

    def cancel_qr_challenge(self, user_id: str, challenge_id: str) -> None:
        """Cancel and delete one owner-matched QR attempt."""
        with self._session_factory() as session, session.begin():
            attempt = session.get(MiHealthQrAttempt, challenge_id, with_for_update=True)
            if attempt is None or attempt.user_id != user_id:
                raise ChallengeNotFoundError("Mi Health QR challenge was not found")
            session.delete(attempt)

    def unbind(self, user_id: str) -> None:
        """Atomically delete this owner's Mi Fitness data, binding, and attempts."""
        with self._session_factory() as session, session.begin():
            binding = session.get(MiHealthBinding, user_id, with_for_update=True)
            if binding is None:
                raise NotBoundError("Mi Health is not bound")
            self._ingestion.delete_provider_data(user_id, "mi_fitness", session=session)
            session.execute(delete(MiHealthQrAttempt).where(MiHealthQrAttempt.user_id == user_id))
            session.delete(binding)

    def health_session(self, binding: MiHealthBinding) -> HealthSession:
        """Decrypt a binding's health session for an in-progress owner operation."""
        return HealthSession(
            user_id=binding.xiaomi_user_id,
            c_user_id=binding.c_user_id,
            pass_token=self._cipher.decrypt(user_id=binding.user_id, purpose="pass_token", envelope=binding.pass_token),
            service_token=self._cipher.decrypt(user_id=binding.user_id, purpose="service_token", envelope=binding.service_token),
            ssecurity=self._cipher.decrypt(user_id=binding.user_id, purpose="ssecurity", envelope=binding.ssecurity),
            device_id=binding.device_id,
        )

    def _attempt(self, user_id: str, challenge_id: str) -> tuple[MiHealthQrAttempt, str]:
        with self._session_factory() as session:
            attempt = session.get(MiHealthQrAttempt, challenge_id)
            if attempt is None or attempt.user_id != user_id:
                raise ChallengeNotFoundError("Mi Health QR challenge was not found")
            lp_url = self._cipher.decrypt(user_id=user_id, purpose="qr_lp", envelope=attempt.lp_ciphertext)
            session.expunge(attempt)
            return attempt, lp_url

    def _write_session(
        self,
        session: Session,
        binding: MiHealthBinding | None,
        *,
        user_id: str,
        health_session: HealthSession,
    ) -> None:
        encrypted = {
            "pass_token": self._cipher.encrypt(user_id=user_id, purpose="pass_token", value=health_session.pass_token),
            "service_token": self._cipher.encrypt(user_id=user_id, purpose="service_token", value=health_session.service_token),
            "ssecurity": self._cipher.encrypt(user_id=user_id, purpose="ssecurity", value=health_session.ssecurity),
        }
        if binding is None:
            binding = MiHealthBinding(
                user_id=user_id,
                region=self._config.region,
                device_id=health_session.device_id,
                xiaomi_user_id=health_session.user_id,
                c_user_id=health_session.c_user_id,
                status="authenticated",
                bound_at=datetime.now(UTC),
                **encrypted,
            )
            session.add(binding)
        else:
            binding.device_id = health_session.device_id
            binding.xiaomi_user_id = health_session.user_id
            binding.c_user_id = health_session.c_user_id
            binding.status = "authenticated"
            binding.revision += 1
            binding.pass_token = encrypted["pass_token"]
            binding.service_token = encrypted["service_token"]
            binding.ssecurity = encrypted["ssecurity"]
        binding.updated_at = datetime.now(UTC)
        session.flush()

    def _status(self, binding: MiHealthBinding | None) -> BindingStatus:
        if binding is None:
            return BindingStatus(status="unbound", region=self._config.region, bound_at=None, last_verified_at=None, last_renewed_at=None)
        return BindingStatus(
            status=binding.status,
            region=binding.region,
            bound_at=binding.bound_at,
            last_verified_at=binding.last_verified_at,
            last_renewed_at=binding.last_renewed_at,
        )
