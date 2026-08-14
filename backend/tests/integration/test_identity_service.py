import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from argon2 import PasswordHasher, Type
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from datacheck.identity.models import User, UserSession
from datacheck.identity.passwords import PasswordService, PasswordVerification
from datacheck.identity.repositories import SessionRepository
from datacheck.identity.service import (
    ABSOLUTE_TIMEOUT,
    IDLE_TIMEOUT,
    AuthenticationRequired,
    DuplicateIdentity,
    IdentityService,
    InvalidCredentials,
    InvalidCsrf,
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
_NOW = datetime(2026, 3, 1, 12, tzinfo=UTC)
_PASSWORD = "valid-password-1"


@dataclass
class _Clock:
    current: datetime

    def __call__(self) -> datetime:
        return self.current


def _password_service(*, time_cost: int = 1) -> PasswordService:
    return PasswordService(
        PasswordHasher(
            time_cost=time_cost,
            memory_cost=8_192,
            parallelism=1,
            hash_len=16,
            salt_len=8,
            encoding="utf-8",
            type=Type.ID,
        )
    )


def _service(
    resources: DatabaseResources,
    clock: _Clock,
    *,
    password_service: PasswordService | None = None,
) -> IdentityService:
    return IdentityService(
        session_factory=resources.session_factory,
        password_service=password_service or _password_service(),
        clock=clock,
    )


@pytest.fixture(autouse=True)
def clean_identity_rows(identity_database: DatabaseResources) -> None:
    with identity_database.engine.begin() as connection:
        connection.execute(delete(UserSession))
        connection.execute(delete(User))


def _insert_user(database_session: Session, *, email_key: str) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{email_key}@example.test",
        email_normalized=f"{email_key.lower()}@example.test",
        password_hash="$argon2id$synthetic-fixture",
        created_at=_NOW - timedelta(days=1),
        updated_at=_NOW - timedelta(days=1),
    )
    database_session.add(user)
    return user


def _insert_session(
    resources: DatabaseResources,
    *,
    created_at: datetime,
    last_seen_at: datetime,
    revoked_at: datetime | None = None,
    email_key: str = "state",
) -> tuple[str, bytes, uuid.UUID]:
    raw_bearer = generate_token_bytes()
    raw_csrf = generate_token_bytes()
    with resources.session_factory() as database_session, database_session.begin():
        user = _insert_user(database_session, email_key=f"{email_key}-{uuid.uuid4().hex}")
        user_session = UserSession(
            id=uuid.uuid4(),
            user_id=user.id,
            token_hash=hash_session_token(raw_bearer),
            csrf_token=raw_csrf,
            created_at=created_at,
            last_seen_at=last_seen_at,
            absolute_expires_at=created_at + ABSOLUTE_TIMEOUT,
            revoked_at=revoked_at,
        )
        database_session.add(user_session)
    return encode_token(raw_bearer), raw_csrf, user_session.id


def test_registration_is_atomic_and_persists_only_token_hash(
    identity_database: DatabaseResources,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock(_NOW)
    service = _service(identity_database, clock)

    result = service.register(email=" Person@EXAMPLE.TEST ", password=_PASSWORD)

    with identity_database.session_factory() as database_session:
        user = database_session.scalar(select(User))
        user_session = database_session.scalar(select(UserSession))
        assert user is not None
        assert user_session is not None
        assert user.email == "Person@example.test"
        assert user.email_normalized == "person@example.test"
        assert user_session.user_id == user.id == result.user.user_id
        assert user_session.token_hash == hash_session_token(decode_token(result.bearer_token))
        assert user_session.csrf_token == decode_token(result.csrf_token)
        assert user_session.absolute_expires_at - user_session.created_at == ABSOLUTE_TIMEOUT
        assert result.bearer_token not in repr(user_session.__dict__)
        assert {"session_token", "raw_token", "token"}.isdisjoint(
            UserSession.__table__.columns.keys()
        )

    with pytest.raises(DuplicateIdentity):
        service.register(email="person@example.test", password=_PASSWORD)
    with identity_database.session_factory() as database_session:
        assert database_session.scalar(select(func.count()).select_from(User)) == 1
        assert database_session.scalar(select(func.count()).select_from(UserSession)) == 1

    original_add = SessionRepository.add

    def add_invalid_session(repository: SessionRepository, user_session: UserSession) -> None:
        user_session.csrf_token = b"short"
        original_add(repository, user_session)

    monkeypatch.setattr(SessionRepository, "add", add_invalid_session)
    with pytest.raises(IntegrityError):
        service.register(email="atomic@example.test", password=_PASSWORD)
    with identity_database.session_factory() as database_session:
        assert (
            database_session.scalar(
                select(func.count())
                .select_from(User)
                .where(User.email_normalized == "atomic@example.test")
            )
            == 0
        )


def test_login_issues_independent_session_and_failure_paths_create_none(
    identity_database: DatabaseResources,
) -> None:
    clock = _Clock(_NOW)
    service = _service(identity_database, clock)
    registration = service.register(email="login@example.test", password=_PASSWORD)
    clock.current = _NOW + timedelta(minutes=1)

    login = service.login(email="LOGIN@example.test", password=_PASSWORD)

    assert login.session_id != registration.session_id
    assert login.bearer_token != registration.bearer_token
    with identity_database.session_factory() as database_session:
        assert database_session.scalar(select(func.count()).select_from(UserSession)) == 2

    with pytest.raises(InvalidCredentials):
        service.login(email="login@example.test", password="wrong-password-1")
    with pytest.raises(InvalidCredentials):
        service.login(email="unknown@example.test", password=_PASSWORD)
    with identity_database.session_factory() as database_session:
        assert database_session.scalar(select(func.count()).select_from(UserSession)) == 2
        database_session.execute(
            update(User)
            .where(User.id == registration.user.user_id)
            .values(password_hash="malformed")
        )
        database_session.commit()
    with pytest.raises(InvalidCredentials):
        service.login(email="login@example.test", password=_PASSWORD)
    with identity_database.session_factory() as database_session:
        assert database_session.scalar(select(func.count()).select_from(UserSession)) == 2


def test_login_rehashes_password_with_session_in_same_write_phase(
    identity_database: DatabaseResources,
) -> None:
    clock = _Clock(_NOW)
    old_passwords = _password_service(time_cost=1)
    registration_service = _service(identity_database, clock, password_service=old_passwords)
    registration = registration_service.register(email="rehash@example.test", password=_PASSWORD)
    with identity_database.session_factory() as database_session:
        old_hash = database_session.scalar(
            select(User.password_hash).where(User.id == registration.user.user_id)
        )
    assert old_hash is not None

    clock.current = _NOW + timedelta(hours=1)
    current_passwords = _password_service(time_cost=2)
    login_service = _service(identity_database, clock, password_service=current_passwords)
    login_service.login(email="rehash@example.test", password=_PASSWORD)

    with identity_database.session_factory() as database_session:
        user = database_session.get(User, registration.user.user_id)
        assert user is not None
        assert user.password_hash != old_hash
        assert current_passwords.verify(user.password_hash, _PASSWORD) is PasswordVerification.MATCH
        assert current_passwords.check_needs_rehash(user.password_hash) is False
        assert user.updated_at == clock.current
        assert database_session.scalar(select(func.count()).select_from(UserSession)) == 2


class _MutatingPasswordService(PasswordService):
    def __init__(self, delegate: PasswordService, mutation: Callable[[], None]) -> None:
        self._delegate = delegate
        self._mutation = mutation

    def normalize_and_validate(self, password: str) -> str:
        return self._delegate.normalize_and_validate(password)

    def hash(self, password: str) -> str:
        return self._delegate.hash(password)

    def verify(self, encoded_hash: str, password: str) -> PasswordVerification:
        result = self._delegate.verify(encoded_hash, password)
        if result is PasswordVerification.MATCH:
            self._mutation()
        return result

    def check_needs_rehash(self, encoded_hash: str) -> bool:
        return self._delegate.check_needs_rehash(encoded_hash)


def test_stale_verified_password_snapshot_cannot_create_session(
    identity_database: DatabaseResources,
) -> None:
    clock = _Clock(_NOW)
    base_passwords = _password_service()
    registration_service = _service(identity_database, clock, password_service=base_passwords)
    registration = registration_service.register(email="stale@example.test", password=_PASSWORD)

    def mutate_hash() -> None:
        with identity_database.session_factory() as database_session, database_session.begin():
            user = database_session.get(User, registration.user.user_id)
            assert user is not None
            user.password_hash = base_passwords.hash("replacement-pass")
            user.updated_at = _NOW + timedelta(minutes=1)

    stale_passwords = _MutatingPasswordService(base_passwords, mutate_hash)
    login_service = _service(identity_database, clock, password_service=stale_passwords)

    with pytest.raises(InvalidCredentials):
        login_service.login(email="stale@example.test", password=_PASSWORD)
    with identity_database.session_factory() as database_session:
        assert database_session.scalar(select(func.count()).select_from(UserSession)) == 1


def test_authentication_touches_active_session_and_rejects_unknown_or_malformed(
    identity_database: DatabaseResources,
) -> None:
    clock = _Clock(_NOW)
    bearer, csrf, session_id = _insert_session(
        identity_database,
        created_at=_NOW - timedelta(hours=1),
        last_seen_at=_NOW - timedelta(minutes=30),
    )
    service = _service(identity_database, clock)

    context = service.authenticate(bearer)

    assert context.session_id == session_id
    assert context.csrf_token == csrf
    with identity_database.session_factory() as database_session:
        assert database_session.get(UserSession, session_id).last_seen_at == _NOW  # type: ignore[union-attr]
    with pytest.raises(AuthenticationRequired):
        service.authenticate(encode_token(generate_token_bytes()))
    with pytest.raises(AuthenticationRequired):
        service.authenticate("malformed")


@pytest.mark.parametrize(
    ("created_at", "last_seen_at", "revoked_at", "accepted"),
    [
        (_NOW - timedelta(hours=3), _NOW - IDLE_TIMEOUT + timedelta(microseconds=1), None, True),
        (_NOW - timedelta(hours=3), _NOW - IDLE_TIMEOUT, None, False),
        (_NOW - timedelta(hours=3), _NOW - IDLE_TIMEOUT - timedelta(microseconds=1), None, False),
        (
            _NOW - ABSOLUTE_TIMEOUT + timedelta(microseconds=1),
            _NOW - timedelta(minutes=1),
            None,
            True,
        ),
        (_NOW - ABSOLUTE_TIMEOUT, _NOW - timedelta(minutes=1), None, False),
        (
            _NOW - ABSOLUTE_TIMEOUT - timedelta(microseconds=1),
            _NOW - timedelta(minutes=1),
            None,
            False,
        ),
        (
            _NOW - timedelta(hours=1),
            _NOW - timedelta(minutes=1),
            _NOW - timedelta(seconds=1),
            False,
        ),
    ],
    ids=[
        "idle-just-before",
        "idle-exact",
        "idle-after",
        "absolute-just-before",
        "absolute-exact",
        "absolute-after",
        "revoked",
    ],
)
def test_authentication_expiration_boundaries_are_fail_closed(
    identity_database: DatabaseResources,
    created_at: datetime,
    last_seen_at: datetime,
    revoked_at: datetime | None,
    accepted: bool,
) -> None:
    bearer, _, _ = _insert_session(
        identity_database,
        created_at=created_at,
        last_seen_at=last_seen_at,
        revoked_at=revoked_at,
    )
    service = _service(identity_database, _Clock(_NOW))

    if accepted:
        assert service.authenticate(bearer).session_id is not None
    else:
        with pytest.raises(AuthenticationRequired):
            service.authenticate(bearer)


def test_logout_is_current_session_only_csrf_protected_and_idempotent(
    identity_database: DatabaseResources,
) -> None:
    clock = _Clock(_NOW)
    service = _service(identity_database, clock)
    first = service.register(email="logout@example.test", password=_PASSWORD)
    second = service.login(email="logout@example.test", password=_PASSWORD)

    with pytest.raises(InvalidCsrf):
        service.logout(
            encoded_bearer=first.bearer_token,
            supplied_csrf_token=b"x" * 32,
        )
    assert service.authenticate(first.bearer_token).session_id == first.session_id

    assert (
        service.logout(
            encoded_bearer=first.bearer_token,
            supplied_csrf_token=decode_token(first.csrf_token),
        )
        is LogoutResult.REVOKED
    )
    with pytest.raises(AuthenticationRequired):
        service.authenticate(first.bearer_token)
    assert service.authenticate(second.bearer_token).session_id == second.session_id
    assert (
        service.logout(
            encoded_bearer=first.bearer_token,
            supplied_csrf_token=None,
        )
        is LogoutResult.ALREADY_INACTIVE
    )


def test_cleanup_is_bounded_and_preserves_active_sessions(
    identity_database: DatabaseResources,
) -> None:
    with identity_database.session_factory() as database_session, database_session.begin():
        user = _insert_user(database_session, email_key="cleanup")
        active_id = uuid.uuid4()
        database_session.add(
            UserSession(
                id=active_id,
                user_id=user.id,
                token_hash=(10_000).to_bytes(32),
                csrf_token=(20_000).to_bytes(32),
                created_at=_NOW - timedelta(hours=1),
                last_seen_at=_NOW - timedelta(minutes=1),
                absolute_expires_at=_NOW + timedelta(hours=11),
                revoked_at=None,
            )
        )
        for index in range(121):
            created_at = _NOW - timedelta(hours=13)
            database_session.add(
                UserSession(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    token_hash=index.to_bytes(32),
                    csrf_token=(index + 1_000).to_bytes(32),
                    created_at=created_at,
                    last_seen_at=created_at,
                    absolute_expires_at=created_at + ABSOLUTE_TIMEOUT,
                    revoked_at=None,
                )
            )

    service = _service(identity_database, _Clock(_NOW))

    assert service.cleanup_inactive_sessions() == 100
    assert service.cleanup_inactive_sessions() == 21
    assert service.cleanup_inactive_sessions() == 0
    with identity_database.session_factory() as database_session:
        assert database_session.scalar(select(func.count()).select_from(UserSession)) == 1
        assert database_session.get(UserSession, active_id) is not None
