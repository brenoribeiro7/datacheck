import importlib
import sys
from typing import cast

import pytest
from celery import Celery


def test_celery_app_uses_worker_settings_without_project_tasks(
    monkeypatch: pytest.MonkeyPatch,
    clear_datacheck_environment: None,
) -> None:
    monkeypatch.setenv("DATACHECK_ENVIRONMENT", "test")
    monkeypatch.setenv("DATACHECK_CELERY_BROKER_URL", "redis://127.0.0.1:6399/0")
    sys.modules.pop("datacheck.infrastructure.celery", None)

    module = importlib.import_module("datacheck.infrastructure.celery")
    celery_app = cast(Celery, module.celery_app)

    assert celery_app.conf.broker_url == "redis://127.0.0.1:6399/0"
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.result_serializer == "json"
    assert celery_app.conf.accept_content == ["json"]
    assert celery_app.conf.broker_connection_retry_on_startup is True
    assert not any(name.startswith("datacheck.") for name in celery_app.tasks)
