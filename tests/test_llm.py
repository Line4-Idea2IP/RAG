import json

import httpx
import pytest
from fastapi.testclient import TestClient

from idea2ip.engine import Engine
from idea2ip.errors import ServiceError
from idea2ip.llm import LlamaClient
from idea2ip.main import create_app
from idea2ip.models import QuestionDraft


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
