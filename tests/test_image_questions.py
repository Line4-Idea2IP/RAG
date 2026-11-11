"""Canned responses verify HTTP payloads and guards, not model semantic quality."""

import base64
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from idea2ip.engine import QUESTION_GUIDANCE, QUESTIONS, Engine
from idea2ip.llm import LlamaClient
from idea2ip.main import create_app
from idea2ip.models import EvidenceType, ImageRequest, QuestionRequest, Source, TargetField

IMAGE = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\nfixture").decode()


def completion(result):
    return httpx.Response(
        200,
        json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}]},
    )


@pytest.fixture
def image_context(context):
    context = context.model_copy(deep=True)
    context.sources = [s for s in context.sources if s.source_id == "attachment-sketch"]
    context.sources.append(
        Source(
            source_id="observation-1",
            project_id=context.project_id,
            kind=EvidenceType.IMAGE_OBSERVATION,
            title="이미지 모델 관찰",
            content=json.dumps(
                {
                    "observations": ["왼쪽의 붉은 원형과 아래쪽의 은색 원통이 보인다."],
                    "limitations": ["아래쪽 원통은 일부만 보여 전체 형태는 확인하기 어렵다."],
                    "authorship_verified": False,
                },
                ensure_ascii=False,
            ),
            parent_source_ids=["attachment-sketch"],
        )
    )
    return context


@pytest.mark.parametrize("target", list(TargetField))
@pytest.mark.parametrize("forged", [False, True])
def test_image_question_actual_chat_and_source_validation(settings, image_context, target, forged):
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        task, raw = payload["messages"][1]["content"][0]["text"].split("\nDATA_JSON:\n")
        data = json.loads(raw)
        calls.append(data)
        assert data["context"] == image_context.model_dump(mode="json")
        attachment, observation = data["context"]["sources"]
        assert attachment["kind"] == "ATTACHED_FILE"
        assert observation["kind"] == "IMAGE_OBSERVATION"
        assert observation["source_id"] == "observation-1"
        assert observation["parent_source_ids"] == [attachment["source_id"]]
        assert json.loads(observation["content"])["authorship_verified"] is False
        assert data["default_question"] == QUESTIONS[target]
        assert data["question_guidance"] == QUESTION_GUIDANCE[target]
        for instruction in (
            "USER_STATEMENT만 사용자 진술로 취급",
            "오류가 있을 수 있는 모델 해석",
            "사용자 진술이나 확인된 창작 사실이 아니다",
            "구체적인 요소를 질문의 계기로",
            "직접 수정·추가한 부분의 유무",
            "사용자가 배치했다고 전제하지 않는다",
            "특정 의도를 추정하거나 제시하지 않는다",
            "limitations와 불확실성",
            "관련성이 낮거나 불확실한 관찰",
            "실제로 활용한 질문의 source_ids",
            "IMAGE_OBSERVATION의 source_id를 반환",
            "부모 첨부와의 연결",
            "일반 질문에는 출처를 강제로 붙이지 않는다",
            "이미 답한 작업 유무를 다시 묻지 말고",
        ):
            assert instruction in task
        return completion(
            {
                "target_field": target.value,
                "question": "붉은 원형과 관련해 알려주실 내용이 있나요?",
                "source_ids": ["invented" if forged else "observation-1"],
            }
        )

    settings = settings.model_copy(update={"mode": "live"})
    client = TestClient(
        create_app(settings, Engine(settings, LlamaClient(settings, httpx.MockTransport(handler))))
    )
    response = client.post(
        f"/v1/projects/{image_context.project_id}/questions",
        json={"context": image_context.model_dump(mode="json"), "target_field": target.value},
    )
    assert len(calls) == 1
    if forged:
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "INVALID_SOURCE_REFERENCE"
    else:
        assert response.status_code == 200
        assert response.json()["source_ids"] == ["observation-1"]


@pytest.mark.parametrize("empty_observation", [False, True])
@pytest.mark.parametrize("mode", ["mock", "live"])
def test_unusable_or_missing_observation_allows_general_question(
    settings, image_context, empty_observation, mode
):
    if empty_observation:
        # Source.content must be nonempty; an empty observation list is valid content.
        image_context.sources[1].content = '{"observations": [], "limitations": []}'
    else:
        image_context.sources.pop()
    calls = []

    def handler(request):
        calls.append(request)
        return completion(
            {
                "target_field": "human_edit",
                "question": QUESTIONS[TargetField.HUMAN_EDIT],
                "source_ids": [],
            }
        )

    settings = settings.model_copy(update={"mode": mode})
    engine = Engine(settings, LlamaClient(settings, httpx.MockTransport(handler)))
    result = engine.question(QuestionRequest(context=image_context, target_field="human_edit"))
    assert result.question == QUESTIONS[TargetField.HUMAN_EDIT]
    assert result.source_ids == []
    assert len(calls) == (1 if mode == "live" else 0)


@pytest.mark.parametrize("limitations", [[], ["작은 글자는 판독하기 어렵다."] * 2])
def test_observe_prompt_deduplicates_only_observation_output(settings, context, limitations):
    # Repeated sentences in a user statement must survive question and analysis paths.
    statement = next(s for s in context.sources if s.source_id == "statement-edit")
    statement.content = "제가 선을 추가했습니다. 제가 선을 추가했습니다."
    original = context.model_dump(mode="json")
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        task, raw = payload["messages"][1]["content"][0]["text"].split("\nDATA_JSON:\n")
        schema = payload["response_format"]["json_schema"]["name"]
        if schema == "ObservationDraft":
            assert json.loads(raw) == {"attachment_source_id": "attachment-sketch"}
            assert payload["messages"][1]["content"][1]["image_url"]["url"] == IMAGE
            for instruction in (
                "주요 시각 요소와 색·형태·상대적 위치",
                "한 요소의 특징을 다른 요소에도 적용하지 않는다",
                "비슷한 관찰을 반복하지 않으며",
                "최대 개수는 상한",
                "재질, 물체의 개폐 상태, 가려진 구조를 확정하지 않는다",
                "불확실성을 표현",
                "흐림·가림·부분 노출·판독 불가",
                "정책 문구로 채우지 말고",
                "빈 목록",
                "저자, 제작 도구, AI 사용 여부, 제작 순서",
                "사용자의 직접 수정이나 창작 의도",
            ):
                assert instruction in task
            return completion(
                {"observations": ["붉은 원형이 보인다."] * 2, "limitations": limitations}
            )
        if schema == "QuestionDraft":
            assert json.loads(raw)["context"] == original
            return completion(
                {
                    "target_field": "human_edit",
                    "question": "어떤 선을 추가했나요?",
                    "source_ids": [],
                }
            )
        sources = json.loads(raw)["sources"]
        assert next(s for s in sources if s["source_id"] == statement.source_id)["content"] == (
            statement.content
        )
        return completion(
            {
                target.value: {
                    "disposition": "provided" if matches else "not_provided",
                    "source_ids": [s["source_id"] for s in matches],
                }
                for target in TargetField
                for matches in [[s for s in sources if s["target_field"] == target.value]]
            }
        )

    settings = settings.model_copy(update={"mode": "live"})
    engine = Engine(settings, LlamaClient(settings, httpx.MockTransport(handler)))
    result = engine.observe(
        ImageRequest(
            context=context, attachment_source_id="attachment-sketch", image_data_uri=IMAGE
        )
    )
    assert result.observations == ["붉은 원형이 보인다."]
    assert result.limitations == list(dict.fromkeys(limitations))
    assert result.parent_source_ids == ["attachment-sketch"]
    assert result.evidence_type == EvidenceType.IMAGE_OBSERVATION
    assert result.authorship_verified is False
    engine.question(QuestionRequest(context=context, target_field="human_edit"))
    analysis = engine.analyze(context)
    assert analysis.fields[2].quotes == [statement.content]
    assert context.model_dump(mode="json") == original
    assert len(calls) == 3


@pytest.mark.parametrize("mode", ["mock", "live"])
def test_image_only_analysis_and_brief_never_recognize_contribution(settings, image_context, mode):
    def handler(request):
        pytest.fail("image-only analysis must not call a model")

    settings = settings.model_copy(update={"mode": mode})
    engine = Engine(settings, LlamaClient(settings, httpx.MockTransport(handler)))
    analysis = engine.analyze(image_context)
    assert all(field.status == "MISSING" and field.source_ids == [] for field in analysis.fields)
    assert engine.contributions_from(analysis).contributions == []
    brief = engine.brief(image_context)
    assert len(brief.sections.model_dump()) == 5
    assert brief.sections.human_contribution.status == "INCOMPLETE"
    assert brief.sections.human_contribution.source_ids == []
    assert brief.sources[1].kind == EvidenceType.IMAGE_OBSERVATION


def test_model_cannot_cite_observation_as_user_contribution(settings, image_context, context):
    statement = next(s for s in context.sources if s.source_id == "statement-edit")
    image_context.sources.append(statement)

    def handler(request):
        payload = json.loads(request.content)
        data = json.loads(payload["messages"][1]["content"][0]["text"].split("\nDATA_JSON:\n")[1])
        assert data["sources"] == [statement.model_dump(mode="json")]
        result = {
            target.value: {"disposition": "not_provided", "source_ids": []}
            for target in TargetField
        }
        result["human_edit"] = {
            "disposition": "provided",
            "source_ids": ["observation-1"],
        }
        return completion(result)

    settings = settings.model_copy(update={"mode": "live"})
    client = TestClient(
        create_app(settings, Engine(settings, LlamaClient(settings, httpx.MockTransport(handler))))
    )
    response = client.post(
        f"/v1/projects/{image_context.project_id}/contributions",
        json=image_context.model_dump(mode="json"),
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "INVALID_QUOTE"
