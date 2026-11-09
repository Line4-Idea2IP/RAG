import pytest

from idea2ip.config import Settings
from idea2ip.engine import Engine
from idea2ip.errors import ServiceError
from idea2ip.models import (
    AnalysisDraft,
    EvidenceType,
    ProjectContext,
    QuestionDraft,
    QuestionRequest,
)


class Stub:
    def __init__(self, result):
        self.result = result

    def generate(self, *args, **kwargs):
        return self.result


def candidate_draft(context):
    fields = Engine(Settings(_env_file=None)).analyze(context).fields
    return AnalysisDraft(
        fields=[
            {
                **{k: v for k, v in f.model_dump().items() if k not in ("status", "evidence_type")},
                "disposition": "provided" if f.source_ids else "not_provided",
            }
            for f in fields
        ]
    )


def test_valid_user_reported_contributions(settings, context):
    draft = candidate_draft(context)
    engine = Engine(settings.model_copy(update={"mode": "live"}), Stub(draft))
    analysis = engine.analyze(context)
    result = engine.contributions_from(analysis)
    assert len(result.contributions) == 1
    assert result.contributions[0].source_ids == ["statement-edit"]
    assert result.contributions[0].evidence_type == EvidenceType.USER_STATEMENT


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("unknown", "INVALID_SOURCE_REFERENCE"),
        ("quote", "INVALID_QUOTE"),
        ("attachment", "INVALID_QUOTE"),
        ("snippet", "INVALID_QUOTE"),
        ("omit", "MODEL_EVIDENCE_OMITTED"),
        ("duplicate_field", "MODEL_FIELD_MISMATCH"),
    ],
)
def test_reject_ungrounded_model_analysis(settings, context, mutation, code):
    draft = candidate_draft(context)
    field = draft.fields[2]
    if mutation == "unknown":
        field.source_ids = ["nonexistent"]
    elif mutation == "quote":
        field.quotes = ["사용자가 전체를 직접 그렸습니다."]
    elif mutation == "attachment":
        field.source_ids = ["attachment-notes"]
        field.quotes = [context.sources[3].content]
    elif mutation == "snippet":
        field.quotes = ["직접 다시 그렸습니다."]
    elif mutation == "omit":
        field.disposition, field.source_ids, field.quotes = "not_provided", [], []
    else:
        draft.fields[0].target_field = draft.fields[1].target_field
    engine = Engine(settings.model_copy(update={"mode": "live"}), Stub(draft))
    with pytest.raises(ServiceError) as error:
        engine.analyze(context)
    assert error.value.code == code


def test_question_rejects_forged_source(settings, context):
    engine = Engine(
        settings.model_copy(update={"mode": "live"}),
        Stub(
            QuestionDraft(
                target_field="human_edit", question="어떻게 만드셨나요?", source_ids=["invented"]
            )
        ),
    )
    with pytest.raises(ServiceError, match="출처"):
        engine.question(QuestionRequest(context=context, target_field="human_edit"))


def test_image_and_guide_cannot_become_human_contribution(settings, context):
    reduced = ProjectContext(
        project_id=context.project_id,
        title=context.title,
        sources=[s for s in context.sources if s.kind != EvidenceType.USER_STATEMENT],
    )
    assert (
        Engine(settings).contributions_from(Engine(settings).analyze(reduced)).contributions == []
    )


def test_mock_is_conservative_about_negation(settings, context):
    context.sources[2].content = "직접 수정한 부분은 없습니다."
    result = Engine(settings).analyze(context)
    assert result.fields[2].status == "UNCLEAR"
    assert Engine(settings).contributions_from(result).contributions == []
