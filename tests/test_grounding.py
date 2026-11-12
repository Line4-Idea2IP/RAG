import pytest

from idea2ip.config import Settings
from idea2ip.engine import Engine
from idea2ip.errors import ServiceError
from idea2ip.models import (
    AnalysisDraft,
    EvidenceType,
    NamedAnalysisDraft,
    ProjectContext,
    QuestionDraft,
    QuestionRequest,
)


class Stub:
    def __init__(self, result):
        self.result = result

    def generate(self, schema, *args, **kwargs):
        if schema is NamedAnalysisDraft and isinstance(self.result, AnalysisDraft):
            return NamedAnalysisDraft.model_validate(
                {
                    f.target_field.value: f.model_dump(exclude={"target_field", "quotes"})
                    for f in self.result.fields
                }
            )
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
    "mutation,status",
    [
        ("unknown", "UNCLEAR"),
        ("duplicate", "USER_REPORTED"),
        ("attachment", "UNCLEAR"),
        ("wrong_field", "UNCLEAR"),
        ("omit", "UNCLEAR"),
    ],
)
def test_ungrounded_model_selection_is_repaired_not_trusted(settings, context, mutation, status):
    draft = candidate_draft(context)
    field = draft.fields[2]
    if mutation == "unknown":
        field.source_ids = ["nonexistent"]
    elif mutation == "duplicate":
        field.source_ids *= 2
    elif mutation == "attachment":
        field.source_ids = ["attachment-notes"]
    elif mutation == "wrong_field":
        field.source_ids = [context.sources[0].source_id]
    elif mutation == "omit":
        field.disposition, field.source_ids, field.quotes = "not_provided", [], []
    engine = Engine(settings.model_copy(update={"mode": "live"}), Stub(draft))
    analysis = engine.analyze(context)
    repaired = analysis.fields[2]
    # Only the field's own user statement survives, quoted verbatim; nothing invented or foreign.
    assert repaired.source_ids == ["statement-edit"]
    assert repaired.quotes == [context.sources[2].content]
    assert repaired.status == status
    # A field the model mis-selected is never reported as a contribution.
    contributions = engine.contributions_from(analysis).contributions
    assert bool(contributions) == (status == "USER_REPORTED")
    # Other fields keep their own statements.
    assert analysis.fields[0].source_ids == ["statement-overview"]


def test_not_provided_without_any_statement_stays_missing(settings, context):
    draft = candidate_draft(context)
    draft.fields[3].disposition, draft.fields[3].source_ids = "provided", ["nonexistent"]
    analysis = Engine(settings.model_copy(update={"mode": "live"}), Stub(draft)).analyze(context)
    assert analysis.fields[3].status == "MISSING"
    assert analysis.fields[3].source_ids == []


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


def test_question_rejects_model_target_mismatch(settings, context):
    engine = Engine(
        settings.model_copy(update={"mode": "live"}),
        Stub(
            QuestionDraft(
                target_field="human_edit", question="수정한 부분이 있나요?", source_ids=[]
            )
        ),
    )
    with pytest.raises(ServiceError) as error:
        engine.question(QuestionRequest(context=context, target_field="selection_arrangement"))
    assert error.value.code == "MODEL_FIELD_MISMATCH"


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


def test_server_hydrates_complete_original_and_preserves_conflict(settings, context):
    # A long statement must be returned verbatim, even when a model would select one sentence.
    original = "첫 문장입니다. 줄바꿈과  두 칸을 보존합니다.\n수정하지 않았다는 상충 진술입니다."
    context.sources[2].content = original
    second = context.sources[2].model_copy(
        update={"source_id": "statement-conflict", "content": "직접 수정했습니다."}
    )
    context.sources.append(second)
    draft = candidate_draft(context)
    draft.fields[2].disposition = "conflicted"
    analysis = Engine(settings.model_copy(update={"mode": "live"}), Stub(draft)).analyze(context)
    field = analysis.fields[2]
    assert field.status == "CONFLICTED"
    assert field.source_ids == ["statement-edit", "statement-conflict"]
    assert field.quotes == [original, second.content]


def test_conflict_with_one_statement_becomes_unclear(settings, context):
    draft = candidate_draft(context)
    draft.fields[2].disposition = "conflicted"
    analysis = Engine(settings.model_copy(update={"mode": "live"}), Stub(draft)).analyze(context)
    assert analysis.fields[2].status == "UNCLEAR"
