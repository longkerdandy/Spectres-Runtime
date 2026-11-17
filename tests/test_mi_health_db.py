"""Real-PostgreSQL tests for Mi Health binding, rotation, and ownership."""

import base64
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from spectres.config import settings
from spectres.db.postgres import get_postgres_db
from spectres.extensions.base import ExtensionContext
from spectres.extensions.mi_health import extension
from spectres.extensions.mi_health.config import MiHealthConfig
from spectres.extensions.mi_health.credentials import CredentialCipher
from spectres.extensions.mi_health.models import MiHealthBase, MiHealthBinding, MiHealthQrAttempt, MiHealthSyncRun
from spectres.extensions.mi_health.service import (
    BindingExistsError,
    ChallengeNotFoundError,
    MiHealthBindingService,
    MiHealthSessionService,
    MiHealthSyncService,
    SyncInProgressError,
)
from spectres.extensions.mi_health.xiaomi import (
    AuthenticationRequiredError,
    HealthSession,
    HealthUnauthorizedError,
    LoginResult,
    ProviderUnavailableError,
    QrChallenge,
    XiaomiClient,
)
from spectres.health.contracts import ProfileSnapshot
from spectres.health.ingestion import HealthIngestionService
from spectres.health.models import HealthProfile

pytestmark = [pytest.mark.integration, pytest.mark.db]
_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")
_SSECURITY = base64.b64encode(b"synthetic-session-secret").decode("ascii")


def _config() -> MiHealthConfig:
    return MiHealthConfig(region="cn", credential_key=_KEY, http_timeout_seconds=1.0, qr_poll_timeout_seconds=1)


def _login(suffix: str = "one") -> LoginResult:
    return LoginResult(
        user_id=f"xiaomi-{suffix}",
        c_user_id=f"c-user-{suffix}",
        pass_token=f"pass-{suffix}",
        ssecurity=_SSECURITY,
        nonce="12345678901234567890",
        location="https://sts-hlth.io.mi.com/healthapp/sts?ticket=synthetic",
    )


def _health_session(user_id: str, device_id: str, suffix: str = "one") -> HealthSession:
    login = _login(suffix)
    return HealthSession(
        user_id=login.user_id,
        c_user_id=login.c_user_id,
        pass_token=login.pass_token,
        service_token=f"service-{suffix}",
        ssecurity=login.ssecurity,
        device_id=device_id,
    )


@pytest.fixture
def services() -> tuple[MiHealthBindingService, MiHealthSessionService, XiaomiClient, sessionmaker[Session]]:
    """Build real services over clean Mi Health tables with synthetic transport."""
    engine = get_postgres_db().db_engine
    MiHealthBase.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    xiaomi = MagicMock(spec=XiaomiClient)
    xiaomi.create_qr_challenge = AsyncMock(
        side_effect=lambda *, device_id: QrChallenge(
            login_url="https://account.xiaomi.com/login",
            qr_payload="https://account.xiaomi.com/qr",
            lp_url="https://c3.lp.account.xiaomi.com/poll?synthetic=1",
            server_timeout_seconds=300,
        )
    )
    xiaomi.poll_qr = AsyncMock(side_effect=lambda **kwargs: _login())
    xiaomi.exchange_sts = AsyncMock(side_effect=lambda result, *, device_id: _health_session(result.user_id, device_id))
    xiaomi.renew = AsyncMock(side_effect=lambda session: _login("two"))
    xiaomi.verify_profile = AsyncMock(return_value=None)
    ingestion = HealthIngestionService(session_factory)
    bindings = MiHealthBindingService(config=_config(), session_factory=session_factory, cipher=CredentialCipher(_KEY), xiaomi=xiaomi, ingestion=ingestion)
    sessions = MiHealthSessionService(bindings=bindings, xiaomi=xiaomi)
    return bindings, sessions, xiaomi, session_factory


async def _bind(bindings: MiHealthBindingService, user_id: str) -> str:
    challenge = await bindings.create_qr_challenge(user_id)
    await bindings.poll_qr_challenge(user_id, challenge.challenge_id)
    return challenge.challenge_id


def _binding(session_factory: sessionmaker[Session], user_id: str) -> MiHealthBinding:
    with session_factory() as session:
        binding = session.get(MiHealthBinding, user_id)
        assert binding is not None
        session.expunge(binding)
        return binding


def _add_legacy_run(session_factory: sessionmaker[Session], user_id: str, run_id: str) -> None:
    now = datetime.now(UTC)
    with session_factory() as session, session.begin():
        session.add(
            MiHealthSyncRun(
                id=run_id,
                user_id=user_id,
                trigger_type="manual",
                status="succeeded",
                streams=[],
                created_at=now,
                updated_at=now,
            )
        )


async def test_qr_binding_encrypts_credentials_and_deletes_attempt(services: tuple[Any, ...]) -> None:
    """A complete QR flow stores ciphertext and removes transient polling material."""
    bindings, _, xiaomi, session_factory = services
    assert bindings.status("alice").status == "unbound"
    challenge = await bindings.create_qr_challenge("alice")
    with session_factory() as session:
        attempt = session.get(MiHealthQrAttempt, challenge.challenge_id)
        assert attempt is not None
        assert "c3.lp.account.xiaomi.com" not in attempt.lp_ciphertext
    status = await bindings.poll_qr_challenge("alice", challenge.challenge_id)
    assert status.status == "authenticated"
    with session_factory() as session:
        assert session.get(MiHealthQrAttempt, challenge.challenge_id) is None
        binding = session.get(MiHealthBinding, "alice")
        assert binding is not None
        for value in (binding.pass_token, binding.service_token, binding.ssecurity):
            assert value.startswith('{"v":1,')
            assert "synthetic" not in value
    with pytest.raises(BindingExistsError):
        await bindings.create_qr_challenge("alice")
    xiaomi.create_qr_challenge.assert_awaited_once()


async def test_challenge_supersession_cancel_and_cross_user_404(services: tuple[Any, ...]) -> None:
    """A new challenge replaces only its owner's attempt and foreign ids return 404."""
    bindings, _, _, session_factory = services
    first = await bindings.create_qr_challenge("alice")
    second = await bindings.create_qr_challenge("alice")
    with session_factory() as session:
        rows = session.scalars(select(MiHealthQrAttempt).where(MiHealthQrAttempt.user_id == "alice")).all()
        assert [row.id for row in rows] == [second.challenge_id]
    with pytest.raises(ChallengeNotFoundError):
        await bindings.poll_qr_challenge("bob", second.challenge_id)
    with pytest.raises(ChallengeNotFoundError):
        bindings.cancel_qr_challenge("bob", second.challenge_id)
    bindings.cancel_qr_challenge("alice", second.challenge_id)
    with pytest.raises(ChallengeNotFoundError):
        bindings.cancel_qr_challenge("alice", first.challenge_id)
    with pytest.raises(ChallengeNotFoundError):
        bindings.cancel_qr_challenge("alice", second.challenge_id)


async def test_reauthentication_reuses_stable_device_id(services: tuple[Any, ...]) -> None:
    """Reauthorization retains the original device id across QR and renewal."""
    bindings, _, xiaomi, session_factory = services
    await _bind(bindings, "alice")
    original = _binding(session_factory, "alice").device_id
    with session_factory() as session, session.begin():
        binding = session.get(MiHealthBinding, "alice")
        assert binding is not None
        binding.status = "reauth_required"
    challenge = await bindings.create_qr_challenge("alice")
    await bindings.poll_qr_challenge("alice", challenge.challenge_id)
    assert _binding(session_factory, "alice").device_id == original
    assert xiaomi.create_qr_challenge.await_args_list[-1].kwargs["device_id"] == original


async def test_unbind_deletes_only_the_current_owner(services: tuple[Any, ...]) -> None:
    """Unbinding Alice leaves Bob's independent binding intact."""
    bindings, _, _, session_factory = services
    await _bind(bindings, "alice")
    await _bind(bindings, "bob")
    bindings.unbind("alice")
    assert bindings.status("alice").status == "unbound"
    assert bindings.status("bob").status == "authenticated"
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(MiHealthBinding)) == 1
        assert session.scalar(select(func.count()).select_from(MiHealthQrAttempt)) == 0


async def test_unbind_deletes_only_current_owner_mi_fitness_health_data(services: tuple[Any, ...]) -> None:
    """Provider and legacy-run cleanup preserve other providers and owners."""
    bindings, _, _, session_factory = services
    ingestion = HealthIngestionService(session_factory)
    await _bind(bindings, "alice")
    await _bind(bindings, "bob")
    for user_id, provider in (("alice", "mi_fitness"), ("alice", "other"), ("bob", "mi_fitness")):
        ingestion.upsert(user_id, provider, ProfileSnapshot(height_cm=Decimal("170")))
    _add_legacy_run(session_factory, "alice", "legacy-alice")
    _add_legacy_run(session_factory, "bob", "legacy-bob")

    bindings.unbind("alice")

    with session_factory() as session:
        assert session.get(HealthProfile, ("alice", "mi_fitness")) is None
        assert session.get(HealthProfile, ("alice", "other")) is not None
        assert session.get(HealthProfile, ("bob", "mi_fitness")) is not None
        assert session.get(MiHealthSyncRun, "legacy-alice") is None
        assert session.get(MiHealthSyncRun, "legacy-bob") is not None


async def test_unbind_rolls_back_health_and_binding_on_composite_failure(services: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch) -> None:
    """A failure after provider deletion rolls back the entire explicit unbind."""
    bindings, _, _, session_factory = services
    ingestion = HealthIngestionService(session_factory)
    await _bind(bindings, "alice")
    ingestion.upsert("alice", "mi_fitness", ProfileSnapshot(height_cm=Decimal("170")))
    original = bindings._ingestion.delete_provider_data

    def fail_after_cleanup(user_id: str, provider: str, *, session: Session) -> None:
        original(user_id, provider, session=session)
        raise RuntimeError("synthetic composite failure")

    monkeypatch.setattr(bindings._ingestion, "delete_provider_data", fail_after_cleanup)
    with pytest.raises(RuntimeError, match="synthetic composite failure"):
        bindings.unbind("alice")

    assert bindings.status("alice").status == "authenticated"
    with session_factory() as session:
        assert session.get(HealthProfile, ("alice", "mi_fitness")) is not None


async def test_renewal_rotates_atomically_and_failure_preserves_old_session(services: tuple[Any, ...]) -> None:
    """Successful renewal changes encrypted fields; provider failure changes none."""
    bindings, sessions, xiaomi, session_factory = services
    await _bind(bindings, "alice")
    before = _binding(session_factory, "alice")
    status = await sessions.renew("alice")
    after = _binding(session_factory, "alice")
    assert status.status == "authenticated"
    assert after.last_renewed_at is not None
    assert after.service_token != before.service_token
    assert after.ssecurity != before.ssecurity
    assert after.pass_token != before.pass_token
    preserved = _binding(session_factory, "alice")
    xiaomi.renew.side_effect = ProviderUnavailableError("synthetic provider failure")
    with pytest.raises(ProviderUnavailableError):
        await sessions.renew("alice")
    failed = _binding(session_factory, "alice")
    assert failed.pass_token == preserved.pass_token
    assert failed.service_token == preserved.service_token
    assert failed.ssecurity == preserved.ssecurity


async def test_renewal_refusal_marks_reauth_without_deleting_credentials(services: tuple[Any, ...]) -> None:
    """Long-term credential refusal preserves the old session for diagnostics."""
    bindings, sessions, xiaomi, session_factory = services
    await _bind(bindings, "alice")
    before = _binding(session_factory, "alice")
    xiaomi.renew.side_effect = AuthenticationRequiredError()
    with pytest.raises(AuthenticationRequiredError):
        await sessions.renew("alice")
    after = _binding(session_factory, "alice")
    assert after.status == "reauth_required"
    assert after.service_token == before.service_token
    assert after.ssecurity == before.ssecurity


async def test_verify_renews_once_and_retries_profile(services: tuple[Any, ...]) -> None:
    """One health 401 causes one renewal and one fresh Profile attempt."""
    bindings, sessions, xiaomi, _ = services
    await _bind(bindings, "alice")
    xiaomi.verify_profile.side_effect = [HealthUnauthorizedError(), None]
    status = await sessions.verify("alice")
    assert status.status == "authenticated"
    assert status.last_verified_at is not None
    assert xiaomi.verify_profile.await_count == 2
    assert xiaomi.renew.await_count == 1


async def test_second_profile_401_stops_after_one_renewal(services: tuple[Any, ...]) -> None:
    """A second 401 marks reauthorization and never enters a renewal loop."""
    bindings, sessions, xiaomi, _ = services
    await _bind(bindings, "alice")
    xiaomi.verify_profile.side_effect = [HealthUnauthorizedError(), HealthUnauthorizedError()]
    with pytest.raises(AuthenticationRequiredError):
        await sessions.verify("alice")
    assert bindings.status("alice").status == "reauth_required"
    assert xiaomi.verify_profile.await_count == 2
    assert xiaomi.renew.await_count == 1


def test_registration_is_idempotent_and_contributes_only_one_router(monkeypatch: pytest.MonkeyPatch) -> None:
    """Registration creates tables and one router without agent or schedule surfaces."""
    monkeypatch.setenv("MI_HEALTH_REGION", "cn")
    monkeypatch.setenv("MI_HEALTH_CREDENTIAL_KEY", _KEY)
    monkeypatch.setenv("MI_HEALTH_HTTP_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("MI_HEALTH_QR_POLL_TIMEOUT_SECONDS", "1")
    ctx = ExtensionContext(settings=settings, db=get_postgres_db())
    for _ in range(2):
        contribution = extension.register(ctx)
        assert len(contribution.routers) == 1
        assert contribution.toolkits == []
        assert contribution.workflows == []
        assert contribution.schedules == []


async def test_qr_timeout_deletes_attempt_and_clears_lp(services: tuple[Any, ...]) -> None:
    """A terminal QR timeout removes the attempt and its encrypted polling URL."""
    from spectres.extensions.mi_health.xiaomi import ChallengeExpiredError

    bindings, _, xiaomi, session_factory = services
    challenge = await bindings.create_qr_challenge("alice")
    xiaomi.poll_qr.side_effect = ChallengeExpiredError()
    with pytest.raises(ChallengeExpiredError):
        await bindings.poll_qr_challenge("alice", challenge.challenge_id)
    with session_factory() as session:
        assert session.get(MiHealthQrAttempt, challenge.challenge_id) is None


async def test_concurrent_renewals_are_serialized(services: tuple[Any, ...]) -> None:
    """Two same-owner renewals complete sequentially without stale credential writes."""
    import asyncio

    bindings, sessions, xiaomi, session_factory = services
    await _bind(bindings, "alice")
    calls = 0

    async def renew(session: HealthSession) -> LoginResult:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return _login(f"rotation-{calls}")

    xiaomi.renew.side_effect = renew
    results = await asyncio.gather(sessions.renew("alice"), sessions.renew("alice"))
    assert [result.status for result in results] == ["authenticated", "authenticated"]
    assert xiaomi.renew.await_count == 2
    assert _binding(session_factory, "alice").status == "authenticated"


async def test_active_sync_blocks_unbind_and_inactive_unbind_clears_volatile_state(
    services: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unbind shares the execution lock and clears snapshots only after deletion."""
    bindings, sessions, xiaomi, session_factory = services
    await _bind(bindings, "alice")
    sync = MiHealthSyncService(
        bindings=bindings,
        sessions=sessions,
        xiaomi=xiaomi,
        ingestion=HealthIngestionService(session_factory),
    )
    run = await sync.start("alice")

    with pytest.raises(SyncInProgressError):
        await sync.unbind("alice")
    assert bindings.status("alice").status == "authenticated"
    assert sync.status("alice").active_run is not None

    monkeypatch.setattr(sync, "sync", AsyncMock(return_value=[]))
    await sync.execute("alice", run.id)
    assert sync.status("alice").last_run is not None
    _add_legacy_run(session_factory, "alice", "legacy-active-unbind")
    await sync.unbind("alice")

    final = sync.status("alice")
    assert final.active_run is None and final.last_run is None
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(MiHealthSyncRun)) == 0
        assert session.get(MiHealthBinding, "alice") is None


async def test_manual_run_executes_sync_and_restores_current_process_status(
    services: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real run traverses provider adapters and checkpoints without run-table writes."""
    import spectres.extensions.mi_health.service.sync as sync_module

    bindings, sessions, xiaomi, session_factory = services
    await _bind(bindings, "alice")
    xiaomi.read_profile = AsyncMock(return_value={})
    xiaomi.read_daily = AsyncMock(return_value={"data_list": [], "has_more": False, "next_key": None})
    xiaomi.read_raw = AsyncMock(return_value={"data_list": [], "has_more": False, "next_key": None})
    xiaomi.read_workouts = AsyncMock(return_value={"sport_records": [], "has_more": False, "next_key": None})
    monkeypatch.setattr(sync_module, "_BACKFILL_SECONDS", 40)
    monkeypatch.setattr(sync_module, "_WINDOW_SECONDS", 40)
    ingestion = HealthIngestionService(session_factory)
    sync = MiHealthSyncService(
        bindings=bindings,
        sessions=sessions,
        xiaomi=xiaomi,
        ingestion=ingestion,
        clock=lambda: 200,
    )

    run = await sync.start("alice")
    initial = sync.status("alice")
    assert initial.active_run is not None and initial.active_run.id == run.id
    assert initial.last_run is None
    assert len(initial.streams) == 8
    assert all(item.status == "never_synced" for item in initial.streams)

    await sync.execute("alice", run.id)

    final = sync.status("alice")
    assert final.active_run is None
    assert final.last_run is not None and final.last_run.status == "succeeded"
    assert len(final.last_run.streams) == 8
    assert all(item.status == "succeeded" for item in final.last_run.streams)
    assert all(item.status == "succeeded" for item in final.streams)
    assert all(item.backfill_completed for item in final.streams)
    assert "service-one" not in repr(final)
    restarted = MiHealthSyncService(bindings=bindings, sessions=sessions, xiaomi=xiaomi, ingestion=ingestion)
    restarted_status = restarted.status("alice")
    assert restarted_status.active_run is None and restarted_status.last_run is None
    assert all(item.status == "succeeded" for item in restarted_status.streams)
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(MiHealthSyncRun)) == 0


async def test_http_background_run_stores_safe_terminal_failure_in_memory(
    services: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real FastAPI background path returns 202 and exposes safe terminal state."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from spectres.extensions.mi_health.api import create_router

    bindings, sessions, xiaomi, session_factory = services
    await _bind(bindings, "alice")
    ingestion = HealthIngestionService(session_factory)
    sync = MiHealthSyncService(bindings=bindings, sessions=sessions, xiaomi=xiaomi, ingestion=ingestion)
    monkeypatch.setattr(sync, "sync", AsyncMock(side_effect=ProviderUnavailableError("private-http-sentinel")))
    app = FastAPI()

    @app.middleware("http")
    async def identity(request: Any, call_next: Any) -> Any:
        request.state.user_id = "alice"
        request.state.is_internal_service = False
        return await call_next(request)

    app.include_router(create_router(bindings=bindings, sessions=sessions, sync=sync))
    client = TestClient(app)
    response = client.post("/api/v1/extensions/mi-health/sync")
    assert response.status_code == 202
    assert response.json()["status"] == "queued"

    status = client.get("/api/v1/extensions/mi-health/sync/status")
    assert status.status_code == 200
    body = status.json()
    assert body["active_run"] is None
    assert body["last_run"]["status"] == "failed"
    assert body["last_run"]["error_code"] == "provider_unavailable"
    assert all(item["status"] == "skipped" for item in body["last_run"]["streams"])
    assert "private-http-sentinel" not in response.text + status.text
