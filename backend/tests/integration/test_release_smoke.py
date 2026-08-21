import hashlib
from functools import partial
from pathlib import Path

import pytest
from argon2 import PasswordHasher, Type
from fastapi.testclient import TestClient
from pydantic import SecretStr

from datacheck.core.settings import ApiSettings
from datacheck.identity.passwords import PasswordService
from datacheck.identity.service import IdentityService
from datacheck.infrastructure.database import DatabaseResources, probe_database
from datacheck.main import create_app

pytestmark = pytest.mark.integration
_ORIGIN = "http://localhost:3000"
_PASSWORD = "valid-password-1"
_COOKIE_NAME = "datacheck_session"


def _client(resources: DatabaseResources, storage_root: Path) -> TestClient:
    settings = ApiSettings(
        environment="test",
        database_url=SecretStr("postgresql+psycopg://redacted.invalid/datacheck_test"),
        trusted_origins=(_ORIGIN,),
        dataset_storage_root=storage_root,
    )
    identity_service = IdentityService(
        session_factory=resources.session_factory,
        password_service=PasswordService(
            PasswordHasher(
                time_cost=1,
                memory_cost=8_192,
                parallelism=1,
                hash_len=16,
                salt_len=8,
                encoding="utf-8",
                type=Type.ID,
            )
        ),
    )
    return TestClient(
        create_app(
            settings=settings,
            database_probe=partial(probe_database, resources.engine),
            database_resources=resources,
            identity_service=identity_service,
        )
    )


def _mutation_headers(csrf_token: str) -> dict[str, str]:
    return {"Origin": _ORIGIN, "X-CSRF-Token": csrf_token}


def test_v1_release_flow_is_complete_and_exposes_only_public_snapshots(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    client = _client(identity_database, tmp_path / "release-storage")
    csv_content = b"id,email,age\n1,alice@example.test,20\n2,invalid,200\n2,,30\n"
    rule_payloads = [
        {"type": "required", "target_column": "email", "configuration": {}},
        {"type": "unique", "target_column": "id", "configuration": {}},
        {
            "type": "type",
            "target_column": "age",
            "configuration": {"expected_type": "integer"},
        },
        {
            "type": "range",
            "target_column": "age",
            "configuration": {"minimum": 0, "maximum": 120},
        },
        {
            "type": "regex",
            "target_column": "email",
            "configuration": {"pattern": "^[^@]+@[^@]+$"},
        },
    ]

    with client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/ready").json() == {"status": "ready"}

        openapi_response = client.get("/openapi.json")
        assert openapi_response.status_code == 200
        openapi = openapi_response.json()
        assert openapi["info"] == {"title": "DataCheck API", "version": "1.0.0"}
        http_methods = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
        assert (
            sum(
                method in http_methods
                for path_item in openapi["paths"].values()
                for method in path_item
            )
            == 14
        )

        registration = client.post(
            "/api/v1/auth/register",
            headers={"Origin": _ORIGIN, "Content-Type": "application/json"},
            json={"email": "release@example.test", "password": _PASSWORD},
        )
        assert registration.status_code == 201
        registration_csrf = registration.json()["csrf_token"]
        assert registration.cookies.get(_COOKIE_NAME) is not None
        assert registration_csrf

        first_logout = client.post(
            "/api/v1/auth/logout",
            headers=_mutation_headers(registration_csrf),
        )
        assert first_logout.status_code == 204
        assert client.get("/api/v1/auth/me").status_code == 401

        login = client.post(
            "/api/v1/auth/login",
            headers={"Origin": _ORIGIN, "Content-Type": "application/json"},
            json={"email": "release@example.test", "password": _PASSWORD},
        )
        assert login.status_code == 200
        csrf_token = login.json()["csrf_token"]
        assert client.cookies.get(_COOKIE_NAME) is not None
        current_user = client.get("/api/v1/auth/me")
        assert current_user.status_code == 200
        assert current_user.json()["user"]["email"] == "release@example.test"
        assert current_user.json()["csrf_token"] == csrf_token

        dataset_response = client.post(
            "/api/v1/datasets",
            headers={**_mutation_headers(csrf_token), "Content-Type": "application/json"},
            json={"name": "Release qualification"},
        )
        assert dataset_response.status_code == 201
        dataset_id = dataset_response.json()["id"]

        upload_response = client.post(
            f"/api/v1/datasets/{dataset_id}/upload",
            headers=_mutation_headers(csrf_token),
            files={"file": ("release-smoke.csv", csv_content, "text/csv")},
        )
        assert upload_response.status_code == 200
        assert upload_response.json()["upload"] == {
            "original_filename": "release-smoke.csv",
            "size_bytes": len(csv_content),
            "row_count": 3,
            "columns": ["id", "email", "age"],
            "sha256": hashlib.sha256(csv_content).hexdigest(),
            "uploaded_at": upload_response.json()["upload"]["uploaded_at"],
        }

        created_rules = []
        for payload in rule_payloads:
            response = client.post(
                f"/api/v1/datasets/{dataset_id}/rules",
                headers={**_mutation_headers(csrf_token), "Content-Type": "application/json"},
                json=payload,
            )
            assert response.status_code == 201
            created_rules.append(response.json())

        rules_response = client.get(f"/api/v1/datasets/{dataset_id}/rules")
        assert rules_response.status_code == 200
        assert rules_response.json() == created_rules

        analysis_response = client.post(
            f"/api/v1/datasets/{dataset_id}/analyses",
            headers=_mutation_headers(csrf_token),
        )
        assert analysis_response.status_code == 201
        analysis = analysis_response.json()
        assert analysis["quality_score"] == 71.43
        assert analysis["source_row_count"] == 3
        assert analysis["total_violation_count"] == 4
        assert analysis["source"] == {
            "original_filename": "release-smoke.csv",
            "content_sha256": hashlib.sha256(csv_content).hexdigest(),
            "size_bytes": len(csv_content),
            "row_count": 3,
            "column_names": ["id", "email", "age"],
            "uploaded_at": upload_response.json()["upload"]["uploaded_at"],
        }
        assert [result["source_rule_id"] for result in analysis["rule_results"]] == [
            rule["id"] for rule in created_rules
        ]
        assert [
            (
                result["rule_type"],
                result["evaluated_count"],
                result["passed_count"],
                result["violation_count"],
                result["skipped_count"],
            )
            for result in analysis["rule_results"]
        ] == [
            ("required", 3, 2, 1, 0),
            ("unique", 3, 2, 1, 0),
            ("type", 3, 3, 0, 0),
            ("range", 3, 2, 1, 0),
            ("regex", 2, 1, 1, 1),
        ]
        assert [result["violation_samples"] for result in analysis["rule_results"]] == [
            [{"row_number": 3, "value_preview": "", "truncated": False}],
            [{"row_number": 3, "value_preview": "2", "truncated": False}],
            [],
            [{"row_number": 2, "value_preview": "200", "truncated": False}],
            [{"row_number": 2, "value_preview": "invalid", "truncated": False}],
        ]

        assert set(analysis) == {
            "id",
            "dataset_id",
            "quality_score",
            "source_row_count",
            "total_violation_count",
            "created_at",
            "source",
            "rule_results",
        }
        assert set(analysis["source"]) == {
            "original_filename",
            "content_sha256",
            "size_bytes",
            "row_count",
            "column_names",
            "uploaded_at",
        }
        for result in analysis["rule_results"]:
            assert set(result) == {
                "rule_position",
                "source_rule_id",
                "rule_type",
                "target_column",
                "configuration",
                "evaluated_count",
                "passed_count",
                "violation_count",
                "skipped_count",
                "violation_samples",
            }
            for sample in result["violation_samples"]:
                assert set(sample) == {"row_number", "value_preview", "truncated"}

        history_response = client.get(f"/api/v1/datasets/{dataset_id}/analyses")
        detail_response = client.get(f"/api/v1/datasets/{dataset_id}/analyses/{analysis['id']}")
        assert history_response.status_code == 200
        assert history_response.json() == [
            {
                "id": analysis["id"],
                "dataset_id": dataset_id,
                "quality_score": 71.43,
                "source_row_count": 3,
                "total_violation_count": 4,
                "created_at": analysis["created_at"],
            }
        ]
        assert detail_response.status_code == 200
        assert detail_response.json() == analysis

        final_logout = client.post(
            "/api/v1/auth/logout",
            headers=_mutation_headers(csrf_token),
        )
        assert final_logout.status_code == 204
        assert client.get("/api/v1/auth/me").status_code == 401
