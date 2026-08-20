import hashlib
from collections.abc import Iterator
from functools import partial
from pathlib import Path
from typing import cast

import pytest
from argon2 import PasswordHasher, Type
from fastapi.testclient import TestClient
from httpx import Response
from pydantic import SecretStr
from sqlalchemy import delete, func, select

from datacheck.core.settings import ApiSettings
from datacheck.datasets.csv import MAX_CSV_BYTES
from datacheck.datasets.models import Dataset, ValidationRule
from datacheck.datasets.service import DatasetService
from datacheck.datasets.storage import LocalDatasetStorage
from datacheck.identity.models import User
from datacheck.identity.passwords import PasswordService
from datacheck.identity.service import IdentityService
from datacheck.infrastructure.database import DatabaseResources, probe_database
from datacheck.main import create_app

pytestmark = pytest.mark.integration
_ORIGIN = "http://localhost:3000"
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


def _test_client(resources: DatabaseResources, root: Path) -> TestClient:
    settings = ApiSettings(
        environment="test",
        database_url=SecretStr("postgresql+psycopg://redacted.invalid/datacheck_test"),
        trusted_origins=(_ORIGIN,),
        dataset_storage_root=root,
    )
    application = create_app(
        settings=settings,
        database_probe=partial(probe_database, resources.engine),
        database_resources=resources,
        identity_service=IdentityService(
            session_factory=resources.session_factory,
            password_service=_password_service(),
        ),
        dataset_service=DatasetService(
            session_factory=resources.session_factory,
            storage=LocalDatasetStorage(root),
        ),
    )
    return TestClient(application)


@pytest.fixture(autouse=True)
def clean_dataset_api_rows(identity_database: DatabaseResources) -> Iterator[None]:
    with identity_database.engine.begin() as connection:
        connection.execute(delete(User))
    yield


def _register(client: TestClient, email: str) -> str:
    response = client.post(
        "/api/v1/auth/register",
        headers={"Origin": _ORIGIN, "Content-Type": "application/json"},
        json={"email": email, "password": _PASSWORD},
    )
    assert response.status_code == 201
    return cast(str, response.json()["csrf_token"])


def _mutation_headers(csrf: str, *, origin: str = _ORIGIN) -> dict[str, str]:
    return {"Origin": origin, "X-CSRF-Token": csrf}


def _create_dataset(client: TestClient, csrf: str, name: str = "People") -> Response:
    return cast(
        Response,
        client.post(
            "/api/v1/datasets",
            headers={**_mutation_headers(csrf), "Content-Type": "application/json"},
            json={"name": name},
        ),
    )


def _upload(
    client: TestClient,
    csrf: str,
    dataset_id: str,
    content: bytes,
    *,
    filename: str | None = "people.csv",
) -> Response:
    return cast(
        Response,
        client.post(
            f"/api/v1/datasets/{dataset_id}/upload",
            headers=_mutation_headers(csrf),
            files={"file": (filename, content, "application/octet-stream")},
        ),
    )


def test_dataset_http_create_list_get_and_cross_user_isolation(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    owner = _test_client(identity_database, tmp_path / "owner-storage")
    outsider = _test_client(identity_database, tmp_path / "outsider-storage")
    with owner, outsider:
        owner_csrf = _register(owner, "owner-api@example.test")
        outsider_csrf = _register(outsider, "outsider-api@example.test")
        created = _create_dataset(owner, owner_csrf, " Owner data ")
        assert created.status_code == 201
        dataset_id = created.json()["id"]
        assert created.json()["name"] == "Owner data"
        assert created.json()["has_upload"] is False
        assert created.json()["upload"] is None

        listing = owner.get("/api/v1/datasets")
        assert listing.status_code == 200
        assert [row["id"] for row in listing.json()] == [dataset_id]
        assert owner.get(f"/api/v1/datasets/{dataset_id}").status_code == 200

        assert outsider.get("/api/v1/datasets").json() == []
        assert outsider.get(f"/api/v1/datasets/{dataset_id}").status_code == 404
        assert _upload(outsider, outsider_csrf, dataset_id, b"id\n1\n").status_code == 404
        rule = outsider.post(
            f"/api/v1/datasets/{dataset_id}/rules",
            headers={**_mutation_headers(outsider_csrf), "Content-Type": "application/json"},
            json={"type": "required", "target_column": "id", "configuration": {}},
        )
        assert rule.status_code == 404


def test_csv_upload_and_all_rule_contracts(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    client = _test_client(identity_database, tmp_path / "storage")
    with client:
        csrf = _register(client, "rules-api@example.test")
        dataset_id = _create_dataset(client, csrf).json()["id"]
        content = b"id,email,age\n1,a@example.test,42\n"
        upload = _upload(client, csrf, dataset_id, content, filename="People.CSV")
        assert upload.status_code == 200
        metadata = upload.json()["upload"]
        assert metadata == {
            "original_filename": "People.CSV",
            "size_bytes": len(content),
            "row_count": 1,
            "columns": ["id", "email", "age"],
            "sha256": hashlib.sha256(content).hexdigest(),
            "uploaded_at": metadata["uploaded_at"],
        }
        assert "storage_key" not in upload.text
        assert "owner_id" not in upload.text

        payloads = [
            {"type": "required", "target_column": "id", "configuration": {}},
            {"type": "unique", "target_column": "email", "configuration": {}},
            {
                "type": "type",
                "target_column": "age",
                "configuration": {"expected_type": "integer"},
            },
            {
                "type": "range",
                "target_column": "age",
                "configuration": {"minimum": 0, "maximum": 130},
            },
            {
                "type": "regex",
                "target_column": "email",
                "configuration": {"pattern": "^[^@]+@[^@]+$"},
            },
        ]
        created_rules: list[dict[str, object]] = []
        for payload in payloads:
            response = client.post(
                f"/api/v1/datasets/{dataset_id}/rules",
                headers={**_mutation_headers(csrf), "Content-Type": "application/json"},
                json=payload,
            )
            assert response.status_code == 201
            created_rules.append(cast(dict[str, object], response.json()))

        listing = client.get(f"/api/v1/datasets/{dataset_id}/rules")
        assert listing.status_code == 200
        assert [row["id"] for row in listing.json()] == [row["id"] for row in created_rules]
        deleted = client.delete(
            f"/api/v1/datasets/{dataset_id}/rules/{created_rules[0]['id']}",
            headers=_mutation_headers(csrf),
        )
        assert deleted.status_code == 204 and deleted.content == b""


def test_mutations_require_auth_trusted_origin_csrf_and_content_type(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    client = _test_client(identity_database, tmp_path / "storage")
    with client:
        unauthenticated = client.post(
            "/api/v1/datasets",
            headers={"Origin": _ORIGIN, "Content-Type": "application/json"},
            json={"name": "Not created"},
        )
        csrf = _register(client, "security-api@example.test")
        missing_csrf = client.post(
            "/api/v1/datasets",
            headers={"Origin": _ORIGIN, "Content-Type": "application/json"},
            json={"name": "Not created"},
        )
        bad_origin = client.post(
            "/api/v1/datasets",
            headers={
                **_mutation_headers(csrf, origin="https://wrong.example.test"),
                "Content-Type": "application/json",
            },
            json={"name": "Not created"},
        )
        wrong_media = client.post(
            "/api/v1/datasets",
            headers={**_mutation_headers(csrf), "Content-Type": "text/plain"},
            content='{"name":"Not created"}',
        )

    assert unauthenticated.status_code == 401
    assert missing_csrf.status_code == 403
    assert bad_origin.status_code == 403
    assert wrong_media.status_code == 415
    with identity_database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Dataset)) == 0


def test_upload_rejects_malformed_multipart_structure_and_exact_file_excess(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    client = _test_client(identity_database, tmp_path / "storage")
    with client:
        csrf = _register(client, "multipart-api@example.test")
        dataset_id = _create_dataset(client, csrf).json()["id"]
        endpoint = f"/api/v1/datasets/{dataset_id}/upload"
        headers = _mutation_headers(csrf)

        extra_field = client.post(
            endpoint,
            headers=headers,
            data={"note": "unexpected"},
            files={"file": ("data.csv", b"id\n1\n", "text/csv")},
        )
        second_file = client.post(
            endpoint,
            headers=headers,
            files=[
                ("file", ("one.csv", b"id\n1\n", "text/csv")),
                ("file", ("two.csv", b"id\n2\n", "text/csv")),
            ],
        )
        no_filename = client.post(
            endpoint,
            headers=headers,
            files={"file": (None, b"id\n1\n", "text/csv")},
        )
        malformed = _upload(client, csrf, dataset_id, b"id,id\n1,2\n")
        too_large = _upload(client, csrf, dataset_id, b"id\n" + b"x" * (MAX_CSV_BYTES - 2))

    assert extra_field.status_code == 400
    assert second_file.status_code == 400
    assert no_filename.status_code == 400
    assert malformed.status_code == 422
    assert malformed.json()["details"][0]["code"] == "duplicate_columns"
    assert too_large.status_code == 413


def test_upload_accepts_exact_file_boundary_and_reupload_conflict_preserves_state(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    client = _test_client(identity_database, tmp_path / "storage")
    with client:
        csrf = _register(client, "boundary-api@example.test")
        dataset_id = _create_dataset(client, csrf).json()["id"]
        exact_content = b"id,keep\n" + b"1," + b"x" * (MAX_CSV_BYTES - 11) + b"\n"
        assert len(exact_content) == MAX_CSV_BYTES
        exact = _upload(client, csrf, dataset_id, exact_content)
        assert exact.status_code == 200
        assert exact.json()["upload"]["size_bytes"] == MAX_CSV_BYTES

        created = client.post(
            f"/api/v1/datasets/{dataset_id}/rules",
            headers={**_mutation_headers(csrf), "Content-Type": "application/json"},
            json={"type": "required", "target_column": "keep", "configuration": {}},
        )
        assert created.status_code == 201
        before = client.get(f"/api/v1/datasets/{dataset_id}").json()
        conflict = _upload(client, csrf, dataset_id, b"id\n2\n", filename="replacement.csv")
        after = client.get(f"/api/v1/datasets/{dataset_id}").json()

    assert conflict.status_code == 409
    assert conflict.json()["code"] == "upload_conflicts_with_rules"
    assert after == before
    with identity_database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ValidationRule)) == 1
