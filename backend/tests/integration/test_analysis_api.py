import hashlib
from collections.abc import Iterator
from functools import partial
from pathlib import Path
from typing import cast

import pytest
from argon2 import PasswordHasher, Type
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete, func, select

from datacheck.analysis.models import Analysis
from datacheck.core.settings import ApiSettings
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


@pytest.fixture(autouse=True)
def clean_analysis_api_rows(identity_database: DatabaseResources) -> Iterator[None]:
    with identity_database.engine.begin() as connection:
        connection.execute(delete(User))
    yield


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


def _client(resources: DatabaseResources, root: Path) -> TestClient:
    settings = ApiSettings(
        environment="test",
        database_url=SecretStr("postgresql+psycopg://redacted.invalid/datacheck_test"),
        trusted_origins=(_ORIGIN,),
        dataset_storage_root=root,
    )
    return TestClient(
        create_app(
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
    )


def _register(client: TestClient, email: str) -> str:
    response = client.post(
        "/api/v1/auth/register",
        headers={"Origin": _ORIGIN, "Content-Type": "application/json"},
        json={"email": email, "password": _PASSWORD},
    )
    assert response.status_code == 201
    return cast(str, response.json()["csrf_token"])


def _headers(csrf: str, *, origin: str = _ORIGIN) -> dict[str, str]:
    return {"Origin": origin, "X-CSRF-Token": csrf}


def _dataset(client: TestClient, csrf: str, name: str = "Analysis") -> str:
    response = client.post(
        "/api/v1/datasets",
        headers={**_headers(csrf), "Content-Type": "application/json"},
        json={"name": name},
    )
    assert response.status_code == 201
    return cast(str, response.json()["id"])


def _upload(client: TestClient, csrf: str, dataset_id: str, content: bytes) -> None:
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/upload",
        headers=_headers(csrf),
        files={"file": ("values.csv", content, "text/csv")},
    )
    assert response.status_code == 200


def _required_rule(client: TestClient, csrf: str, dataset_id: str) -> str:
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/rules",
        headers={**_headers(csrf), "Content-Type": "application/json"},
        json={"type": "required", "target_column": "value", "configuration": {}},
    )
    assert response.status_code == 201
    return cast(str, response.json()["id"])


def test_analysis_http_returns_numeric_score_bounded_results_and_safe_snapshot(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    client = _client(identity_database, tmp_path / "storage")
    with client:
        csrf = _register(client, "analysis-api@example.test")
        dataset_id = _dataset(client, csrf)
        content = b'value\n1\n2\n3\n4\n5\n""\n'
        _upload(client, csrf, dataset_id, content)
        rule_id = _required_rule(client, csrf, dataset_id)

        response = client.post(
            f"/api/v1/datasets/{dataset_id}/analyses",
            headers=_headers(csrf),
        )

        assert response.status_code == 201
        body = response.json()
        score = body["quality_score"]
        assert score == 83.33
        assert isinstance(score, (int, float)) and not isinstance(score, bool)
        assert body["source"]["content_sha256"] == hashlib.sha256(content).hexdigest()
        assert body["rule_results"][0]["source_rule_id"] == rule_id
        assert body["rule_results"][0]["violation_count"] == 1
        assert len(body["rule_results"][0]["violation_samples"]) == 1
        for forbidden in ("storage_key", "owner_id", str(tmp_path), "raw_csv"):
            assert forbidden not in response.text

        listing = client.get(f"/api/v1/datasets/{dataset_id}/analyses")
        detail = client.get(f"/api/v1/datasets/{dataset_id}/analyses/{body['id']}")

    assert listing.status_code == 200
    assert listing.json() == [
        {
            "id": body["id"],
            "dataset_id": dataset_id,
            "quality_score": 83.33,
            "source_row_count": 6,
            "total_violation_count": 1,
            "created_at": body["created_at"],
        }
    ]
    assert detail.status_code == 200
    assert detail.json() == body


def test_analysis_http_serializes_zero_evaluated_score_as_null(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    client = _client(identity_database, tmp_path / "storage")
    with client:
        csrf = _register(client, "analysis-null@example.test")
        dataset_id = _dataset(client, csrf)
        _upload(client, csrf, dataset_id, b"value\n")
        _required_rule(client, csrf, dataset_id)
        response = client.post(f"/api/v1/datasets/{dataset_id}/analyses", headers=_headers(csrf))

    assert response.status_code == 201
    assert response.json()["quality_score"] is None


def test_analysis_history_is_newest_first_and_paginated_without_results(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    client = _client(identity_database, tmp_path / "storage")
    with client:
        csrf = _register(client, "analysis-history-api@example.test")
        dataset_id = _dataset(client, csrf)
        _upload(client, csrf, dataset_id, b"value\n1\n")
        _required_rule(client, csrf, dataset_id)
        endpoint = f"/api/v1/datasets/{dataset_id}/analyses"
        first = client.post(endpoint, headers=_headers(csrf)).json()
        second = client.post(endpoint, headers=_headers(csrf)).json()

        first_page = client.get(endpoint, params={"limit": 1, "offset": 0})
        second_page = client.get(endpoint, params={"limit": 1, "offset": 1})

    assert first_page.status_code == 200
    assert [item["id"] for item in first_page.json()] == [second["id"]]
    assert [item["id"] for item in second_page.json()] == [first["id"]]
    assert "rule_results" not in first_page.text


def test_analysis_mutation_requires_auth_trusted_origin_and_csrf(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    client = _client(identity_database, tmp_path / "storage")
    with client:
        csrf = _register(client, "analysis-security@example.test")
        dataset_id = _dataset(client, csrf)
        _upload(client, csrf, dataset_id, b"value\n1\n")
        _required_rule(client, csrf, dataset_id)
        endpoint = f"/api/v1/datasets/{dataset_id}/analyses"

        client.cookies.clear()
        unauthenticated = client.post(endpoint, headers=_headers(csrf))
        client.cookies.set("datacheck_session", "invalid")
        invalid_session = client.post(endpoint, headers=_headers(csrf))
        client.cookies.clear()
        csrf = _register(client, "analysis-security-second@example.test")
        missing_csrf = client.post(endpoint, headers={"Origin": _ORIGIN})
        bad_csrf = client.post(endpoint, headers={"Origin": _ORIGIN, "X-CSRF-Token": "bad"})
        bad_origin = client.post(
            endpoint,
            headers=_headers(csrf, origin="https://wrong.example.test"),
        )

    assert unauthenticated.status_code == 401
    assert invalid_session.status_code == 401
    assert missing_csrf.status_code == 403
    assert bad_csrf.status_code == 403
    assert bad_origin.status_code == 403
    with identity_database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Analysis)) == 0


def test_analysis_http_guardrails_and_cross_owner_converge_safely(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    owner = _client(identity_database, tmp_path / "owner")
    outsider = _client(identity_database, tmp_path / "outsider")
    with owner, outsider:
        owner_csrf = _register(owner, "analysis-owner@example.test")
        outsider_csrf = _register(outsider, "analysis-outsider@example.test")
        empty_dataset = _dataset(owner, owner_csrf, "No upload")
        no_upload = owner.post(
            f"/api/v1/datasets/{empty_dataset}/analyses", headers=_headers(owner_csrf)
        )

        no_rules_dataset = _dataset(owner, owner_csrf, "No rules")
        _upload(owner, owner_csrf, no_rules_dataset, b"value\n1\n")
        no_rules = owner.post(
            f"/api/v1/datasets/{no_rules_dataset}/analyses",
            headers=_headers(owner_csrf),
        )

        ready_dataset = _dataset(owner, owner_csrf, "Owned")
        _upload(owner, owner_csrf, ready_dataset, b"value\n1\n")
        _required_rule(owner, owner_csrf, ready_dataset)
        created = owner.post(
            f"/api/v1/datasets/{ready_dataset}/analyses",
            headers=_headers(owner_csrf),
        ).json()

        cross_post = outsider.post(
            f"/api/v1/datasets/{ready_dataset}/analyses",
            headers=_headers(outsider_csrf),
        )
        cross_list = outsider.get(f"/api/v1/datasets/{ready_dataset}/analyses")
        cross_detail = outsider.get(f"/api/v1/datasets/{ready_dataset}/analyses/{created['id']}")
        wrong_dataset_detail = owner.get(
            f"/api/v1/datasets/{empty_dataset}/analyses/{created['id']}"
        )

    assert no_upload.status_code == 409
    assert no_upload.json()["code"] == "dataset_not_ready"
    assert no_rules.status_code == 409
    assert no_rules.json()["code"] == "analysis_requires_rules"
    assert cross_post.status_code == 404
    assert cross_list.status_code == 404
    assert cross_detail.status_code == 404
    assert wrong_dataset_detail.status_code == 404
