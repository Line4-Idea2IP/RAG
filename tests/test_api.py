import base64

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from idea2ip.engine import Engine
from idea2ip.main import create_app
from idea2ip.models import TargetField

ROOT = "/v1/projects/project-moon-garden"


@pytest.mark.parametrize("path", ["answers/analyze", "contributions", "brief"])
def test_mock_flow(client, payload, path):
    response = client.post(ROOT + "/" + path, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["mode"] == "mock"


def test_exactly_five_brief_sections_and_references(client, payload):
    body = client.post(ROOT + "/brief", json=payload).json()
    assert set(body["sections"]) == {
        "work_overview",
        "ai_usage",
        "human_contribution",
        "evidence_summary",
        "gaps_and_guidance",
    }
    allowed = {s["source_id"] for s in body["sources"]}
    assert all(set(s["source_ids"]) <= allowed for s in body["sections"].values())
    assert body["legal_editions"] == []
    assert body["status"] == "DRAFT"


def test_question_is_neutral(client, payload):
    response = client.post(
        ROOT + "/questions", json={"context": payload, "target_field": "human_edit"}
    )
    assert response.status_code == 200
    assert "없다면" in response.json()["question"]


@pytest.mark.parametrize("mode,has_sources", [("mock", True), ("mock", False), ("live", False)])
@pytest.mark.parametrize(
    "target,expected",
    [
        ("work_overview", "작품의 종류와 표현하려는 내용을 설명해 주시겠어요?"),
        (
            "ai_usage",
            "AI 도구를 사용한 작업이 있나요? 있다면 도구 이름과 활용 단계를, "
            "없다면 없다고 알려주세요.",
        ),
        (
            "human_edit",
            "작품에서 직접 수정하거나 추가한 부분이 있나요? "
            "있다면 구체적인 요소와 작업 방법을, 없다면 없다고 알려주세요.",
        ),
        (
            "selection_arrangement",
            "여러 시안이나 요소 중 직접 선택하거나 배치한 작업이 있나요? "
            "있다면 그 과정과 기준을, 없다면 없다고 알려주세요.",
        ),
        (
            "creative_intent",
            "표현하려던 의도가 있나요? 있다면 그 의도와 이를 반영한 결정이나 과정을, "
            "없다면 없다고 알려주세요.",
        ),
    ],
)
def test_fallback_questions(settings, payload, mode, has_sources, target, expected):
    class NoCall:
        def generate(self, *args, **kwargs):
            pytest.fail("fallback must not call model")

    settings = settings.model_copy(update={"mode": mode})
    client = TestClient(create_app(settings, Engine(settings, NoCall())))
    if not has_sources:
        payload["sources"] = []
    response = client.post(ROOT + "/questions", json={"context": payload, "target_field": target})
    assert response.status_code == 200
    body = response.json()
    # Reviewed fixed wording; this does not assess arbitrary model responses.
    assert body["question"] == expected
    assert body["source_ids"] == []
    assert body["target_field"] == target
    assert body["mode"] == mode


def test_unknown_question_target_rejected(client, payload):
    response = client.post(
        ROOT + "/questions", json={"context": payload, "target_field": "unknown"}
    )
    assert response.status_code == 422


def test_empty_brief_uses_all_default_questions(client, payload):
    from idea2ip.engine import QUESTIONS

    payload["sources"] = []
    body = client.post(ROOT + "/brief", json=payload).json()
    assert body["sections"]["gaps_and_guidance"]["statements"][:5] == [
        QUESTIONS[target] for target in TargetField
    ]


@pytest.mark.parametrize("mutation", ["cross_project", "duplicate", "official", "orphan"])
def test_bad_sources_rejected(client, payload, mutation):
    source = payload["sources"][0]
    if mutation == "cross_project":
        source["project_id"] = "another-project"
    elif mutation == "duplicate":
        payload["sources"].append(source.copy())
    elif mutation == "official":
        source["kind"] = "OFFICIAL_GUIDE"
    else:
        source["kind"] = "IMAGE_OBSERVATION"
        source["parent_source_ids"] = ["unknown"]
    response = client.post(ROOT + "/brief", json=payload)
    assert response.status_code == 422
    assert "달빛" not in response.text  # Validation errors must not echo private inputs.


def test_path_scope(client, payload):
    assert client.post("/v1/projects/another/brief", json=payload).status_code == 422


def test_auth_required_when_configured(settings, payload):
    app = create_app(settings.model_copy(update={"service_token": SecretStr("local-test")}))
    client = TestClient(app)
    assert client.post(ROOT + "/brief", json=payload).status_code == 401
    assert (
        client.post(
            ROOT + "/brief", json=payload, headers={"X-Service-Token": "local-test"}
        ).status_code
        == 200
    )


def test_empty_context_never_calls_model(settings):
    class NoCall:
        def generate(self, *args, **kwargs):
            pytest.fail("model called with no evidence")

    settings = settings.model_copy(update={"mode": "live"})
    client = TestClient(create_app(settings, Engine(settings, NoCall())))
    context = {"project_id": "empty", "title": "비어 있음", "sources": []}
    response = client.post("/v1/projects/empty/brief", json=context)
    assert response.status_code == 200
    assert response.json()["sections"]["work_overview"]["status"] == "INCOMPLETE"


def test_images_do_not_claim_visual_analysis_in_mock(client, payload):
    # Valid 1x1 PNG fixture. No remote fetch or model dependency.
    image = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0l"
        "EQVR4nGP4DwQACfsD/fteaysAAAAASUVORK5CYII="
    )
    response = client.post(
        ROOT + "/images/observe",
        json={
            "context": payload,
            "attachment_source_id": "attachment-sketch",
            "image_data_uri": "data:image/png;base64," + image,
        },
    )
    assert response.status_code == 200
    assert response.json()["observations"] == []
    assert response.json()["authorship_verified"] is False
    assert base64.b64decode(image).startswith(b"\x89PNG")


@pytest.mark.parametrize("uri", ["http://127.0.0.1/private", "data:image/png;base64,YWJj", "bad"])
def test_unsafe_or_invalid_images(client, payload, uri):
    response = client.post(
        ROOT + "/images/observe",
        json={
            "context": payload,
            "attachment_source_id": "attachment-sketch",
            "image_data_uri": uri,
        },
    )
    assert response.status_code == 422


def test_health_is_liveness_only(client):
    assert client.get("/health/live").json()["dependencies_checked"] is False
