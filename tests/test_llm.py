import json

import httpx
import pytest
from fastapi.testclient import TestClient

from idea2ip.engine import QUESTIONS, Engine
from idea2ip.errors import ServiceError
from idea2ip.llm import LlamaClient
from idea2ip.main import create_app
from idea2ip.models import QuestionDraft, QuestionRequest, TargetField


@pytest.mark.parametrize(
    "target,required_guidance",
    [
        (TargetField.WORK_OVERVIEW, ["작품 종류", "표현 내용"]),
        (TargetField.AI_USAGE, ["AI 도구", "활용 단계", "사용을 전제하지 않는다"]),
        (TargetField.HUMAN_EDIT, ["직접 수정", "추가", "구체적인 요소와 방법"]),
        (
            TargetField.SELECTION_ARRANGEMENT,
            [
                "후보·요소 선택",
                "위치·크기·순서",
                "기준",
                "직접 다시 그렸다는 진술만으로 선택·배치도 했다고 전제하지 않는다",
                "별개의 선택·구성 작업 유무를 묻는다",
                "직접 수정 작업이나 도구 설정을 반복해서 묻지 않는다",
                "특정 편집 프로그램 사용을 가정하지 않으며 AI 도구 안에서 후보를",
            ],
        ),
        (TargetField.CREATIVE_INTENT, ["표현하려던 의도", "반영한 결정·과정"]),
    ],
)
def test_question_chat_receives_target_guidance(settings, context, target, required_guidance):
    # Deliberately provide only a human_edit statement for every target. In particular,
    # selection_arrangement must retain its own scope despite the redrawing context.
    context.sources = [s for s in context.sources if s.source_id == "statement-edit"]
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        task, raw_data = payload["messages"][1]["content"][0]["text"].split("\nDATA_JSON:\n")
        data = json.loads(raw_data)
        calls.append(data)
        assert data["target_field"] == target.value
        assert data["default_question"] == QUESTIONS[target]
        for instruction in required_guidance:
            assert instruction in data["question_guidance"]
        assert data["context"] == context.model_dump(mode="json")
        for instruction in (
            "question_guidance에 따라 default_question을 참고",
            "한국어 질문 하나",
            "길이 제한",
            "불필요한 하위 질문",
            "해당 작업이 없는 경우도 허용",
            "'없다'고 답할 수 있음을 질문에 명시",
            "이미 있으면 사용자 진술로 취급",
            "이미 답한 작업 유무를 다시 묻지 말고",
            "작업 주체 확인만 반복하지 않는다",
            "불명확하거나 상충하는 진술은 확인",
            "첨부·이미지 관찰은 확인 질문의 계기로만",
            "직접 창작을 입증하는 근거로 바꾸지 않는다",
        ):
            assert instruction in task
        schema = payload["response_format"]["json_schema"]["schema"]
        assert schema["properties"]["question"]["maxLength"] == 500
        # This canned response tests request construction, not generated semantic quality.
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "target_field": target.value,
                                    "question": QUESTIONS[target],
                                    "source_ids": [],
                                }
                            )
                        },
                    }
                ]
            },
        )

    settings = settings.model_copy(update={"mode": "live"})
    engine = Engine(settings, LlamaClient(settings, httpx.MockTransport(handler)))
    result = engine.question(QuestionRequest(context=context, target_field=target))
    assert result.target_field == target
    assert len(calls) == 1


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
        data = json.loads(payload["messages"][1]["content"][0]["text"].split("\nDATA_JSON:\n")[1])
        assert data["field_questions"] == {target.value: text for target, text in QUESTIONS.items()}
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
