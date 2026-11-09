import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from idea2ip.config import Settings
from idea2ip.main import create_app
from idea2ip.models import ProjectContext


@pytest.fixture
def context():
    return ProjectContext.model_validate_json(
        Path("samples/project.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def settings():
    return Settings(_env_file=None, mode="mock", retrieval="none")


@pytest.fixture
def client(settings):
    return TestClient(create_app(settings))


@pytest.fixture
def payload(context):
    return json.loads(context.model_dump_json())
