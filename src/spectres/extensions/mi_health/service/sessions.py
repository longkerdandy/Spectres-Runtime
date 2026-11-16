"""Bounded Mi Health renewal and Profile-verification orchestration."""

from datetime import UTC, datetime

from spectres.extensions.mi_health.models import MiHealthBinding
from spectres.extensions.mi_health.service.bindings import BindingStatus, MiHealthBindingService, NotBoundError
from spectres.extensions.mi_health.xiaomi import AuthenticationRequiredError, HealthUnauthorizedError, OwnerActionRequiredError, XiaomiClient


class MiHealthSessionService:
    """Verify and rotate the current owner's health session."""

    def __init__(self, *, bindings: MiHealthBindingService, xiaomi: XiaomiClient) -> None:
        """Inject shared binding persistence and Xiaomi transport."""
        self._bindings = bindings
        self._xiaomi = xiaomi

    async def renew(self, user_id: str) -> BindingStatus:
        """Rotate credentials only if the bound session has not changed concurrently."""
        with self._bindings.session_factory() as session:
            binding = session.get(MiHealthBinding, user_id)
            if binding is None:
                raise NotBoundError("Mi Health is not bound")
            expected_revision = binding.revision
            current = self._bindings.health_session(binding)
        try:
            result = await self._xiaomi.renew(current)
            rotated = await self._xiaomi.exchange_sts(result, device_id=current.device_id)
        except (AuthenticationRequiredError, OwnerActionRequiredError):
            with self._bindings.session_factory() as session, session.begin():
                binding = session.get(MiHealthBinding, user_id, with_for_update=True)
                if binding is not None and binding.revision == expected_revision:
                    binding.status = "reauth_required"
                    binding.updated_at = datetime.now(UTC)
            raise
        with self._bindings.session_factory() as session, session.begin():
            binding = session.get(MiHealthBinding, user_id, with_for_update=True)
            if binding is None:
                raise NotBoundError("Mi Health is not bound")
            if binding.revision != expected_revision:
                return self._status(binding)
            binding.xiaomi_user_id = rotated.user_id
            binding.c_user_id = rotated.c_user_id
            binding.pass_token = self._bindings.cipher.encrypt(user_id=user_id, purpose="pass_token", value=rotated.pass_token)
            binding.service_token = self._bindings.cipher.encrypt(user_id=user_id, purpose="service_token", value=rotated.service_token)
            binding.ssecurity = self._bindings.cipher.encrypt(user_id=user_id, purpose="ssecurity", value=rotated.ssecurity)
            binding.status = "authenticated"
            binding.revision += 1
            binding.last_renewed_at = datetime.now(UTC)
            binding.updated_at = datetime.now(UTC)
            session.flush()
            return self._status(binding)

    async def verify(self, user_id: str) -> BindingStatus:
        """Verify Profile, renewing and retrying at most once after HTTP 401."""
        with self._bindings.session_factory() as session:
            binding = session.get(MiHealthBinding, user_id)
            if binding is None:
                raise NotBoundError("Mi Health is not bound")
            current = self._bindings.health_session(binding)
        try:
            await self._xiaomi.verify_profile(current)
        except HealthUnauthorizedError:
            try:
                await self.renew(user_id)
            except (AuthenticationRequiredError, OwnerActionRequiredError):
                raise
            with self._bindings.session_factory() as session:
                binding = session.get(MiHealthBinding, user_id)
                if binding is None:
                    raise NotBoundError("Mi Health is not bound") from None
                current = self._bindings.health_session(binding)
            try:
                await self._xiaomi.verify_profile(current)
            except HealthUnauthorizedError:
                self.mark_reauth_required(user_id)
                raise AuthenticationRequiredError("Xiaomi rejected the health request after one renewal") from None
        now = datetime.now(UTC)
        with self._bindings.session_factory() as session, session.begin():
            binding = session.get(MiHealthBinding, user_id, with_for_update=True)
            if binding is None:
                raise NotBoundError("Mi Health is not bound")
            binding.status = "authenticated"
            binding.last_verified_at = now
            binding.updated_at = now
            session.flush()
            return self._status(binding)

    def mark_reauth_required(self, user_id: str) -> None:
        """Mark an existing binding as needing owner QR approval."""
        with self._bindings.session_factory() as session, session.begin():
            binding = session.get(MiHealthBinding, user_id, with_for_update=True)
            if binding is not None:
                binding.status = "reauth_required"
                binding.updated_at = datetime.now(UTC)

    def mark_authenticated(self, user_id: str) -> None:
        """Record a successful signed provider read for the current owner."""
        now = datetime.now(UTC)
        with self._bindings.session_factory() as session, session.begin():
            binding = session.get(MiHealthBinding, user_id, with_for_update=True)
            if binding is None:
                raise NotBoundError("Mi Health is not bound")
            binding.status = "authenticated"
            binding.last_verified_at = now
            binding.updated_at = now

    @staticmethod
    def _status(binding: MiHealthBinding) -> BindingStatus:
        return BindingStatus(
            status=binding.status,
            region=binding.region,
            bound_at=binding.bound_at,
            last_verified_at=binding.last_verified_at,
            last_renewed_at=binding.last_renewed_at,
        )
