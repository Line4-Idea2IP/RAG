import json

import httpx
import pytest
from fastapi.testclient import TestClient

from idea2ip.engine import Engine
from idea2ip.errors import ServiceError
from idea2ip.llm import LlamaClient
from idea2ip.main import create_app
from idea2ip.models import QuestionDraft


@pytest.mark.parametrize("variant", ["missing", "extra", "old_duplicate_array"])
def test_invalid_analysis_shape_fails_closed(settings, context, variant):
    from idea2ip.models import TargetField

    empty = {"disposition": "not_provided", "source_ids": [], "quotes": []}
    result = {target.value: empty.copy() for target in TargetField}
    if variant == "missing":
        del result["creative_intent"]
    elif variant == "extra":
        result["unknown_field"] = empty.copy()
    else:
        result = {"fields": [{"target_field": "human_edit", **empty} for _ in range(5)]}

    def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}]
            },
        )

    settings = settings.model_copy(update={"mode": "live"})
    engine = Engine(settings, LlamaClient(settings, httpx.MockTransport(handler)))
    client = TestClient(create_app(settings, engine))
    response = client.post(
        f"/v1/projects/{context.project_id}/answers/analyze", json=context.model_dump(mode="json")
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "MODEL_INVALID_OUTPUT"


@pytest.mark.parametrize("endpoint", ["answers/analyze", "brief", "contributions"])
def test_analysis_uses_required_named_fields(settings, context, endpoint):
    from idea2ip.models import EvidenceType, TargetField

    def handler(request):
        payload = json.loads(request.content)
        schema = payload["response_format"]["json_schema"]["schema"]
        names = {target.value for target in TargetField}
        assert set(schema["properties"]) == names
        assert set(schema["required"]) == names
        assert schema["additionalProperties"] is False
        result = {}
        for target in TargetField:
            sources = [
                s
                for s in context.sources
                if s.kind == EvidenceType.USER_STATEMENT and s.target_field == target
            ]
            result[target.value] = {
                "disposition": "provided" if sources else "not_provided",
                "source_ids": [s.source_id for s in sources],
                "quotes": [s.content for s in sources],
            }
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}]
            },
        )

    settings = settings.model_copy(update={"mode": "live"})
    engine = Engine(settings, LlamaClient(settings, httpx.MockTransport(handler)))
    client = TestClient(create_app(settings, engine))
    response = client.post(
        f"/v1/projects/{context.project_id}/{endpoint}", json=context.model_dump(mode="json")
    )
    assert response.status_code == 200, response.text
    result = response.json()
    if endpoint == "answers/analyze":
        assert [field["target_field"] for field in result["fields"]] == [
            t.value for t in TargetField
        ]
        assert result["fields"][3]["status"] == "MISSING"
        assert result["fields"][4]["status"] == "MISSING"
    elif endpoint == "brief":
        assert len(result["sections"]) == 5
        assert result["sections"]["human_contribution"]["source_ids"] == ["statement-edit"]
    else:
        assert result["contributions"][0]["source_ids"] == ["statement-edit"]


def test_llama_chat_contract(settings):
    def handler(request):
        assert str(request.url) == "http://localhost:8081/v1/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == "idea2ip-vl"
        assert body["response_format"]["json_schema"]["schema"]["required"]
        assert body["messages"][1]["content"][1]["type"] == "image_url"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "target_field": "human_edit",
                                    "question": "직접 수정한 부분이 있나요?",
                                    "source_ids": [],
                                }
                            )
                        },
                    }
                ]
            },
        )

    client = LlamaClient(settings, httpx.MockTransport(handler))
    assert (
        client.generate(QuestionDraft, "task", {}, "data:image/png;base64,fixture").source_ids == []
    )


@pytest.mark.parametrize(
    "variant,code",
    [
        ("connection", "MODEL_UNAVAILABLE"),
        ("timeout", "MODEL_TIMEOUT"),
        ("http", "MODEL_HTTP_ERROR"),
        ("bad_json", "MODEL_INVALID_OUTPUT"),
        ("missing_field", "MODEL_INVALID_OUTPUT"),
        ("truncated", "MODEL_INVALID_OUTPUT"),
    ],
)
def test_model_failures(settings, variant, code):
    def handler(request):
        if variant == "connection":
            raise httpx.ConnectError("connection refused", request=request)
        if variant == "timeout":
            raise httpx.ReadTimeout("timeout", request=request)
        if variant == "http":
            return httpx.Response(500, text="private upstream error")
        content = "garbage" if variant == "bad_json" else '{"question":"누락"}'
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length" if variant == "truncated" else "stop",
                        "message": {"content": content},
                    }
                ]
            },
        )

    with pytest.raises(ServiceError) as error:
        LlamaClient(settings, httpx.MockTransport(handler)).generate(QuestionDraft, "task", {})
    assert error.value.code == code


def test_live_outage_is_503_not_mock(settings, context):
    def handler(request):
        raise httpx.ConnectError("offline", request=request)

    settings = settings.model_copy(update={"mode": "live"})
    engine = Engine(settings, LlamaClient(settings, httpx.MockTransport(handler)))
    client = TestClient(create_app(settings, engine))
    response = client.post(
        f"/v1/projects/{context.project_id}/questions",
        json={
            "context": context.model_dump(mode="json"),
            "target_field": "human_edit",
        },
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MODEL_UNAVAILABLE"
