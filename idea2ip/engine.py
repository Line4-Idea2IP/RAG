import hashlib

from .config import Settings
from .errors import ServiceError
from .llm import LlamaClient
from .models import (
    AnalysisDraft,
    AnalysisResponse,
    BriefResponse,
    BriefSection,
    BriefSections,
    Contribution,
    ContributionResponse,
    EvidenceType,
    FieldAnalysis,
    FieldCandidate,
    ImageRequest,
    ImageResponse,
    NamedAnalysisDraft,
    ObservationDraft,
    ProjectContext,
    QuestionDraft,
    QuestionRequest,
    QuestionResponse,
    SearchRequest,
    TargetField,
)
from .retrieval import search

QUESTIONS = {
    TargetField.WORK_OVERVIEW: "작품의 종류와 표현하려는 내용을 설명해 주시겠어요?",
    TargetField.AI_USAGE: (
        "AI 도구를 사용한 작업이 있나요? 있다면 도구 이름과 활용 단계를, 없다면 없다고 알려주세요."
    ),
    TargetField.HUMAN_EDIT: (
        "작품에서 직접 수정하거나 추가한 부분이 있나요? "
        "있다면 구체적인 요소와 작업 방법을, 없다면 없다고 알려주세요."
    ),
    TargetField.SELECTION_ARRANGEMENT: (
        "여러 시안이나 요소 중 직접 선택하거나 배치한 작업이 있나요? "
        "있다면 그 과정과 기준을, 없다면 없다고 알려주세요."
    ),
    TargetField.CREATIVE_INTENT: (
        "표현하려던 의도가 있나요? 있다면 그 의도와 이를 반영한 결정이나 과정을, "
        "없다면 없다고 알려주세요."
    ),
}

QUESTION_GUIDANCE = {
    TargetField.WORK_OVERVIEW: "작품 종류와 표현 내용을 묻는다.",
    TargetField.AI_USAGE: "사용한 AI 도구와 활용 단계를 묻는다. 사용을 전제하지 않는다.",
    TargetField.HUMAN_EDIT: (
        "사용자가 직접 수정하거나 추가한 구체적인 요소와 방법을 묻는다. "
        "후보 선택·배치나 프롬프트·도구 설정을 대신 묻지 않는다."
    ),
    TargetField.SELECTION_ARRANGEMENT: (
        "후보·요소 선택, 구성, 위치·크기·순서 결정 중 관련된 작업과 그 기준을 묻는다. "
        "직접 다시 그렸다는 진술만으로 선택·배치도 했다고 전제하지 않는다. "
        "직접 수정 과정에 한정하지 말고 별개의 선택·구성 작업 유무를 묻는다. "
        "직접 수정 작업이나 도구 설정을 반복해서 묻지 않는다. "
        "특정 편집 프로그램 사용을 가정하지 않으며 AI 도구 안에서 후보를 "
        "선택·구성한 경우도 포함한다."
    ),
    TargetField.CREATIVE_INTENT: (
        "표현하려던 의도와 이를 반영한 결정·과정을 묻는다. "
        "수정 방법이나 도구 설정만 묻는 질문으로 바꾸지 않는다."
    ),
}


class Engine:
    def __init__(self, settings: Settings, llm: LlamaClient | None = None):
        self.settings = settings
        self.llm = llm or LlamaClient(settings)

    def prepare(self, context: ProjectContext, query: str) -> ProjectContext:
        hits = search(SearchRequest(context=context, query=query), self.settings).hits
        sources = {s.source_id: s for s in context.sources}
        for hit in hits:
            source = hit.source
            old = sources.get(source.source_id)
            if old is not None and old != source:
                raise ServiceError(
                    "SOURCE_CONFLICT", "요청과 색인의 동일 출처 내용이 다릅니다", 422
                )
            sources[source.source_id] = source
        try:
            return ProjectContext.model_validate(
                {**context.model_dump(), "sources": list(sources.values())}
            )
        except ValueError as exc:
            raise ServiceError(
                "VECTOR_CONTEXT_INVALID", "검색 근거 범위/부모 출처 검증 실패", 503
            ) from exc

    @staticmethod
    def check_ids(ids: list[str], context: ProjectContext) -> None:
        allowed = {s.source_id for s in context.sources}
        if len(ids) != len(set(ids)) or not set(ids) <= allowed:
            raise ServiceError("INVALID_SOURCE_REFERENCE", "없는 출처 또는 중복 출처 ID 차단")

    def question(self, request: QuestionRequest) -> QuestionResponse:
        context = self.prepare(request.context, QUESTIONS[request.target_field])
        if self.settings.mode == "mock" or not context.sources:
            draft = QuestionDraft(
                target_field=request.target_field,
                question=QUESTIONS[request.target_field],
                source_ids=[],
            )
        else:
            draft = self.llm.generate(
                QuestionDraft,
                "target_field에 대해 question_guidance에 따라 default_question을 참고하여 "
                "중립적인 한국어 질문 하나를 작성한다. 기존 스키마의 길이 제한을 지키고 "
                "불필요한 하위 질문을 나열하지 않는다. "
                "사실을 전제하지 말고 해당 작업이 없는 경우도 허용하며 "
                "'없다'고 답할 수 있음을 질문에 명시한다. "
                "관련 내용이 이미 있으면 사용자 진술로 취급하고 부족한 내용에 초점을 맞춘다. "
                "이미 답한 작업 유무를 다시 묻지 말고 구체적인 방법·기준 등 빠진 내용만 묻는다. "
                "'제가 수정했다'는 답변에 작업 주체 확인만 반복하지 않는다. "
                "불명확하거나 상충하는 진술은 확인할 수 있다. "
                "첨부·이미지 관찰은 확인 질문의 계기로만 사용하며 사용자의 작업 주체·의도·"
                "직접 창작을 입증하는 근거로 바꾸지 않는다.",
                {
                    "target_field": request.target_field.value,
                    "default_question": QUESTIONS[request.target_field],
                    "question_guidance": QUESTION_GUIDANCE[request.target_field],
                    "context": context.model_dump(mode="json"),
                },
            )
        self.check_ids(draft.source_ids, context)
        if draft.target_field != request.target_field:
            raise ServiceError("MODEL_FIELD_MISMATCH", "모델의 질문 대상 필드 불일치")
        return QuestionResponse(
            **draft.model_dump(),
            project_id=context.project_id,
            snapshot_version=context.snapshot_version,
            mode=self.settings.mode,
        )

    def analyze_prepared(self, context: ProjectContext) -> AnalysisResponse:
        statements = [s for s in context.sources if s.kind == EvidenceType.USER_STATEMENT]
        if self.settings.mode == "mock" or not statements:
            fields = []
            for target in TargetField:
                matches = [s for s in statements if s.target_field == target]
                fields.append(
                    FieldCandidate(
                        target_field=target,
                        # Mock never pretends to understand completeness, negation or conflicts.
                        disposition="unclear" if matches else "not_provided",
                        source_ids=[s.source_id for s in matches],
                        quotes=[s.content for s in matches],
                    )
                )
            draft = AnalysisDraft(fields=fields)
        else:
            named = self.llm.generate(
                NamedAnalysisDraft,
                "사용자 진술만 분석한다. 다음 5개 이름을 가진 JSON 객체를 반환한다: "
                "work_overview, ai_usage, human_edit, selection_arrangement, creative_intent. "
                "각 객체는 disposition, source_ids, quotes만 가진다. fields 배열이나 "
                "target_field 속성은 반환하지 않는다. 자료가 없는 항목도 반드시 포함하고 "
                "disposition=not_provided, source_ids=[], quotes=[]로 반환한다. "
                "provided는 해당 질문에 구체적으로 답한 경우, unclear는 모호/관련성 부족, "
                "not_provided는 근거 없음, conflicted는 양립 불가능한 진술이 있는 경우다. "
                "'직접 수정한 것이 없다'도 답변이지만 창작 기여를 했다는 뜻이 아니다. "
                "source_ids와 quotes는 같은 순서/개수로 쓴다. "
                "quote는 content 전체 원문이어야 한다. "
                "모든 사용된 진술을 인용하고 상충하는 진술을 버리지 않는다. "
                "target_field가 명시된 진술은 다른 필드로 바꾸지 않는다.",
                {
                    "field_questions": {target.value: text for target, text in QUESTIONS.items()},
                    "sources": [s.model_dump(mode="json") for s in statements],
                },
            )
            draft = named.to_draft()
        if {f.target_field for f in draft.fields} != set(TargetField):
            raise ServiceError("MODEL_FIELD_MISMATCH", "분석 필드 중복/누락")
        lookup = {s.source_id: s for s in statements}
        results = []
        for field in draft.fields:
            self.check_ids(field.source_ids, context)
            if len(field.source_ids) != len(field.quotes):
                raise ServiceError("INVALID_SOURCE_REFERENCE", "인용과 출처 개수 불일치")
            if field.disposition == "not_provided" and field.source_ids:
                raise ServiceError("MODEL_INVALID_OUTPUT", "근거 없음 상태에 인용이 있습니다")
            if field.disposition != "not_provided" and not field.source_ids:
                raise ServiceError("INVALID_SOURCE_REFERENCE", "답변 분석에 원문 인용이 필요합니다")
            for sid, quote in zip(field.source_ids, field.quotes):
                source = lookup.get(sid)
                if source is None or quote != source.content:
                    raise ServiceError("INVALID_QUOTE", "사용자 진술 원문에 없는 인용 차단")
                if source.target_field is not None and source.target_field != field.target_field:
                    raise ServiceError("MODEL_FIELD_MISMATCH", "사용자 진술의 대상 필드 변경 차단")
            if field.disposition == "conflicted" and len(field.source_ids) < 2:
                raise ServiceError(
                    "MODEL_INVALID_OUTPUT", "상충 분석에는 두 개 이상의 진술이 필요합니다"
                )
            # Explicitly mapped statements cannot disappear from their field's analysis.
            expected = {s.source_id for s in statements if s.target_field == field.target_field}
            if not expected <= set(field.source_ids):
                raise ServiceError("MODEL_EVIDENCE_OMITTED", "지정 필드의 사용자 진술 누락")
            status = {
                "provided": "USER_REPORTED",
                "unclear": "UNCLEAR",
                "not_provided": "MISSING",
                "conflicted": "CONFLICTED",
            }[field.disposition]
            results.append(
                FieldAnalysis(
                    **field.model_dump(),
                    status=status,
                    evidence_type=(
                        EvidenceType.USER_STATEMENT if field.source_ids else EvidenceType.UNVERIFIED
                    ),
                )
            )
        return AnalysisResponse(
            project_id=context.project_id,
            snapshot_version=context.snapshot_version,
            mode=self.settings.mode,
            fields=results,
        )

    def analyze(self, context: ProjectContext) -> AnalysisResponse:
        return self.analyze_prepared(
            self.prepare(context, "창작 과정 AI 활용 직접 수정 선택 배치 의도")
        )

    def contributions_from(self, analysis: AnalysisResponse) -> ContributionResponse:
        categories = {
            TargetField.HUMAN_EDIT,
            TargetField.SELECTION_ARRANGEMENT,
            TargetField.CREATIVE_INTENT,
        }
        return ContributionResponse(
            project_id=analysis.project_id,
            snapshot_version=analysis.snapshot_version,
            mode=self.settings.mode,
            contributions=[
                Contribution(category=f.target_field, statement=quote, source_ids=[sid])
                for f in analysis.fields
                if f.target_field in categories and f.status == "USER_REPORTED"
                for sid, quote in zip(f.source_ids, f.quotes)
            ],
            unresolved_fields=[
                f.target_field for f in analysis.fields if f.status != "USER_REPORTED"
            ],
        )

    def observe(self, request: ImageRequest) -> ImageResponse:
        if self.settings.mode == "mock":
            draft = ObservationDraft(
                observations=[], limitations=["테스트 모드: 실제 이미지를 분석하지 않았습니다."]
            )
        else:
            draft = self.llm.generate(
                ObservationDraft,
                "첨부 이미지에서 직접 볼 수 있는 색, 형태, 배치만 기술한다. "
                "직접 수정, 저자, AI 사용, 제작 순서를 추론하지 않는다.",
                {"attachment_source_id": request.attachment_source_id},
                request.image_data_uri,
            )
        digest = hashlib.sha256(request.image_data_uri.encode()).hexdigest()[:16]
        return ImageResponse(
            **draft.model_dump(),
            project_id=request.context.project_id,
            mode=self.settings.mode,
            source_id="obs-" + digest,
            parent_source_ids=[request.attachment_source_id],
        )

    def brief(self, context: ProjectContext) -> BriefResponse:
        context = self.prepare(context, "창작 과정 AI 활용 직접 수정 선택 배치 의도")
        analysis = self.analyze_prepared(context)
        legal_hits = search(
            SearchRequest(context=context, query="저작권 등록 신청 창작", scope="legal"),
            self.settings,
        ).hits
        legal = [hit.source for hit in legal_hits]
        ids = {s.source_id for s in context.sources}
        if ids & {s.source_id for s in legal}:
            raise ServiceError("SOURCE_CONFLICT", "프로젝트와 법률 출처 ID 충돌", 422)

        def section(title: str, targets: set[TargetField]) -> BriefSection:
            relevant = [f for f in analysis.fields if f.target_field in targets]
            return BriefSection(
                title=title,
                status=(
                    "USER_REPORTED"
                    if all(f.status == "USER_REPORTED" for f in relevant)
                    else "INCOMPLETE"
                ),
                statements=[
                    f"[{f.status}] 사용자 진술: {quote}" for f in relevant for quote in f.quotes
                ]
                or ["미확인: 사용자 진술이 필요합니다."],
                source_ids=list(dict.fromkeys(sid for f in relevant for sid in f.source_ids)),
            )

        gaps = [QUESTIONS[f.target_field] for f in analysis.fields if f.status != "USER_REPORTED"]
        if not legal:
            gaps.append("검토된 공식 법률자료/신청 지침 판본이 연결되지 않았습니다.")
        sections = BriefSections(
            work_overview=section("1. 작품 개요", {TargetField.WORK_OVERVIEW}),
            ai_usage=section("2. AI 활용 내역", {TargetField.AI_USAGE}),
            human_contribution=section(
                "3. 인간의 창작 기여에 관한 진술",
                {
                    TargetField.HUMAN_EDIT,
                    TargetField.SELECTION_ARRANGEMENT,
                    TargetField.CREATIVE_INTENT,
                },
            ),
            evidence_summary=BriefSection(
                title="4. 제출 근거 목록",
                status="AVAILABLE" if context.sources else "INCOMPLETE",
                statements=[f"[{s.kind.value}] {s.title}" for s in context.sources],
                source_ids=[s.source_id for s in context.sources],
            ),
            gaps_and_guidance=BriefSection(
                title="5. 보완 질문 및 공식 지침",
                status="INCOMPLETE" if gaps else "AVAILABLE",
                statements=gaps + [f"[공식 지침 {s.edition}] {s.content}" for s in legal],
                source_ids=[s.source_id for s in legal],
            ),
        )
        sources = [*context.sources, *legal]
        allowed = {s.source_id for s in sources}
        for s in sections.model_dump().values():
            if not set(s["source_ids"]) <= allowed:
                raise ServiceError("INVALID_SOURCE_REFERENCE", "리포트 출처 검증 실패")
        return BriefResponse(
            project_id=context.project_id,
            snapshot_version=context.snapshot_version,
            mode=self.settings.mode,
            sections=sections,
            sources=sources,
            legal_editions=legal,
            notices=[
                "창작 기여 항목은 사용자 진술의 분류이며 사실 인증이나 기여 점수가 아닙니다.",
                "이미지 관찰과 첨부 파일만으로 직접 창작 또는 저작자를 확정하지 않습니다.",
                "이 초안은 저작권 성립, 법적 판단 또는 등록 가능성을 보장하지 않습니다.",
            ]
            + (
                ["테스트 모드: 답변 의미 분석을 수행하지 않았습니다."]
                if self.settings.mode == "mock"
                else []
            ),
        )
