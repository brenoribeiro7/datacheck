import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from argon2 import PasswordHasher, Type
from sqlalchemy import delete, func, select

from datacheck.identity.models import User, UserSession
from datacheck.identity.passwords import PasswordService
from datacheck.identity.service import (
    ABSOLUTE_TIMEOUT,
    DuplicateIdentity,
    IdentityService,
    LogoutResult,
)
from datacheck.identity.tokens import (
    decode_token,
    encode_token,
    generate_token_bytes,
    hash_session_token,
)
from datacheck.infrastructure.database import DatabaseResources

pytestmark = pytest.mark.integration
_NOW = datetime(2026, 3, 2, 12, tzinfo=UTC)
_PASSWORD = "valid-password-1"


def _password_service() -> PasswordService:
    return PasswordService(
        PasswordHasher(
            time_cost=1,
            memory_cost=8_192,
            parallelism=1,
            hash_len=16,
            salt_len=8,
            encoding="utf-8",
            type=Type.ID,
        )
    )


def _service(resources: DatabaseResources, now: datetime) -> IdentityService:
    return IdentityService(
        session_factory=resources.session_factory,
        password_service=_password_service(),
        clock=lambda: now,
    )


@pytest.fixture(autouse=True)
def clean_identity_rows(identity_database: DatabaseResources) -> None:
    with identity_database.engine.begin() as connection:
        connection.execute(delete(UserSession))
        connection.execute(delete(User))


def test_concurrent_duplicate_registration_has_one_winner_and_no_orphan(
    identity_database: DatabaseResources,
) -> None:
    first_service = _service(identity_database, _NOW)
    second_service = _service(identity_database, _NOW)
    barrier = Barrier(2)

    def register(service: IdentityService) -> str:
        barrier.wait()
        try:
            service.register(email="race@example.test", password=_PASSWORD)
        except DuplicateIdentity:
            return "duplicate"
        return "created"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(register, (first_service, second_service)))

    assert sorted(results) == ["created", "duplicate"]
    with identity_database.session_factory() as database_session:
        assert database_session.scalar(select(func.count()).select_from(User)) == 1
        assert database_session.scalar(select(func.count()).select_from(UserSession)) == 1


def test_concurrent_authentication_touch_never_regresses_last_seen(
    identity_database: DatabaseResources,
) -> None:
    raw_bearer = generate_token_bytes()
    bearer = encode_token(raw_bearer)
    session_id = uuid.uuid4()
    with identity_database.session_factory() as database_session, database_session.begin():
        user = User(
            id=uuid.uuid4(),
            email="touch@example.test",
            email_normalized="touch@example.test",
            password_hash="$argon2id$synthetic-fixture",
            created_at=_NOW - timedelta(days=1),
            updated_at=_NOW - timedelta(days=1),
        )
        database_session.add(user)
        database_session.add(
            UserSession(
                id=session_id,
                user_id=user.id,
                token_hash=hash_session_token(raw_bearer),
                csrf_token=generate_token_bytes(),
                created_at=_NOW - timedelta(hours=1),
                last_seen_at=_NOW - timedelta(minutes=30),
                absolute_expires_at=_NOW + timedelta(hours=11),
                revoked_at=None,
            )
        )

    earlier = _service(identity_database, _NOW)
    later_now = _NOW + timedelta(minutes=10)
    later = _service(identity_database, later_now)
    barrier = Barrier(2)

    def authenticate(service: IdentityService) -> uuid.UUID:
        barrier.wait()
        return service.authenticate(bearer).session_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        session_ids = list(executor.map(authenticate, (earlier, later)))

    assert session_ids == [session_id, session_id]
    with identity_database.session_factory() as database_session:
        stored = database_session.get(UserSession, session_id)
        assert stored is not None
        assert stored.last_seen_at == later_now


def test_concurrent_valid_logout_is_safely_idempotent(
    identity_database: DatabaseResources,
) -> None:
    service = _service(identity_database, _NOW)
    issuance = service.register(email="logout-race@example.test", password=_PASSWORD)
    csrf = decode_token(issuance.csrf_token)
    first = _service(identity_database, _NOW + timedelta(minutes=1))
    second = _service(identity_database, _NOW + timedelta(minutes=1))
    barrier = Barrier(2)

    def logout(actor: IdentityService) -> LogoutResult:
        barrier.wait()
        return actor.logout(encoded_bearer=issuance.bearer_token, supplied_csrf_token=csrf)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(logout, (first, second)))

    assert set(results) == {LogoutResult.REVOKED, LogoutResult.ALREADY_INACTIVE}
    with identity_database.session_factory() as database_session:
        stored = database_session.get(UserSession, issuance.session_id)
        assert stored is not None
        assert stored.revoked_at == _NOW + timedelta(minutes=1)


def test_cleanup_skips_row_locked_by_another_transaction(
    identity_database: DatabaseResources,
) -> None:
    created_at = _NOW - timedelta(hours=13)
    with identity_database.session_factory() as database_session, database_session.begin():
        user = User(
            id=uuid.uuid4(),
            email="locked-cleanup@example.test",
            email_normalized="locked-cleanup@example.test",
            password_hash="$argon2id$synthetic-fixture",
            created_at=_NOW - timedelta(days=1),
            updated_at=_NOW - timedelta(days=1),
        )
        database_session.add(user)
        locked_id = uuid.uuid4()
        unlocked_id = uuid.uuid4()
        for index, session_id in enumerate((locked_id, unlocked_id), start=1):
            database_session.add(
                UserSession(
                    id=session_id,
                    user_id=user.id,
                    token_hash=index.to_bytes(32),
                    csrf_token=(index + 10).to_bytes(32),
                    created_at=created_at,
                    last_seen_at=created_at,
                    absolute_expires_at=created_at + ABSOLUTE_TIMEOUT,
                    revoked_at=None,
                )
            )

    locking_session = identity_database.session_factory()
    locking_transaction = locking_session.begin()
    try:
        locked = locking_session.scalar(
            select(UserSession).where(UserSession.id == locked_id).with_for_update()
        )
        assert locked is not None

        with ThreadPoolExecutor(max_workers=1) as executor:
            deleted = executor.submit(
                _service(identity_database, _NOW).cleanup_inactive_sessions
            ).result(timeout=10)

        assert deleted == 1
        with identity_database.session_factory() as observer:
            assert observer.get(UserSession, locked_id) is not None
            assert observer.get(UserSession, unlocked_id) is None
    finally:
        locking_transaction.rollback()
        locking_session.close()
