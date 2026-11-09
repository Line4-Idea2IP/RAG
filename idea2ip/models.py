from __future__ import annotations

import base64
from datetime import date
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Id = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EvidenceType(str, Enum):
    USER_STATEMENT = "USER_STATEMENT"
    ATTACHED_FILE = "ATTACHED_FILE"
    IMAGE_OBSERVATION = "IMAGE_OBSERVATION"
    OFFICIAL_GUIDE = "OFFICIAL_GUIDE"
    UNVERIFIED = "UNVERIFIED"


class TargetField(str, Enum):
    WORK_OVERVIEW = "work_overview"
    AI_USAGE = "ai_usage"
    HUMAN_EDIT = "human_edit"
    SELECTION_ARRANGEMENT = "selection_arrangement"
    CREATIVE_INTENT = "creative_intent"


class Source(StrictModel):
    source_id: Id
    project_id: Id
    kind: EvidenceType
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    content: Text
    target_field: TargetField | None = None
    parent_source_ids: list[Id] = Field(default_factory=list, max_length=10)
    locator: str | None = Field(default=None, max_length=300)


class ProjectContext(StrictModel):
    project_id: Id
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    snapshot_version: Id = "sample-v1"
    sources: list[Source] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def isolate(self) -> ProjectContext:
        lookup = {s.source_id: s for s in self.sources}
        if len(lookup) != len(self.sources):
            raise ValueError("duplicate source_id")
        if sum(len(s.content) for s in self.sources) > 100_000:
            raise ValueError("context exceeds 100000 characters")
        for s in self.sources:
            if s.project_id != self.project_id:
                raise ValueError("cross-project source rejected")
            if s.kind == EvidenceType.OFFICIAL_GUIDE:
                raise ValueError("official guides must come from the server catalog")
            if s.kind == EvidenceType.IMAGE_OBSERVATION and not s.parent_source_ids:
                raise ValueError("image observation requires attachment parents")
            for parent in s.parent_source_ids:
                if parent not in lookup or lookup[parent].kind != EvidenceType.ATTACHED_FILE:
                    raise ValueError("parent must reference an attachment in this project")
        return self


class QuestionRequest(StrictModel):
    context: ProjectContext
    target_field: TargetField


class QuestionDraft(StrictModel):
    target_field: TargetField
    question: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    source_ids: list[Id] = Field(max_length=20)


class QuestionResponse(QuestionDraft):
    mode: Literal["mock", "live"]
    project_id: Id
    snapshot_version: Id


class FieldCandidate(StrictModel):
    target_field: TargetField
    disposition: Literal["provided", "unclear", "not_provided", "conflicted"]
    source_ids: list[Id] = Field(max_length=100)
    quotes: list[Text] = Field(max_length=100)


class AnalysisDraft(StrictModel):
    fields: list[FieldCandidate] = Field(min_length=5, max_length=5)


class FieldAnalysis(FieldCandidate):
    status: Literal["MISSING", "UNCLEAR", "USER_REPORTED", "CONFLICTED"]
    evidence_type: EvidenceType


class AnalysisResponse(StrictModel):
    project_id: Id
    snapshot_version: Id
    mode: Literal["mock", "live"]
    fields: list[FieldAnalysis]


class Contribution(StrictModel):
    category: TargetField
    statement: Text
    source_ids: list[Id]
    evidence_type: Literal[EvidenceType.USER_STATEMENT] = EvidenceType.USER_STATEMENT
    status: Literal["USER_REPORTED"] = "USER_REPORTED"


class ContributionResponse(StrictModel):
    project_id: Id
    snapshot_version: Id
    mode: Literal["mock", "live"]
    contributions: list[Contribution]
    unresolved_fields: list[TargetField]


class ImageRequest(StrictModel):
    context: ProjectContext
    attachment_source_id: Id
    image_data_uri: str = Field(min_length=1, max_length=7_000_000, repr=False)

    @model_validator(mode="after")
    def validate_image(self) -> ImageRequest:
        header, sep, body = self.image_data_uri.partition(",")
        if not sep or header not in ("data:image/png;base64", "data:image/jpeg;base64"):
            raise ValueError("only base64 PNG/JPEG data URI is supported; remote URLs rejected")
        try:
            raw = base64.b64decode(body, validate=True)
        except ValueError as exc:
            raise ValueError("invalid base64 image") from exc
        if not raw or len(raw) > 5_000_000:
            raise ValueError("image size must be 1..5000000 bytes")
        if header == "data:image/png;base64" and not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("PNG signature mismatch")
        if header == "data:image/jpeg;base64" and not raw.startswith(b"\xff\xd8\xff"):
            raise ValueError("JPEG signature mismatch")
        parents = {s.source_id: s for s in self.context.sources}
        parent = parents.get(self.attachment_source_id)
        if parent is None or parent.kind != EvidenceType.ATTACHED_FILE:
            raise ValueError("image must reference an attachment in this project")
        return self


class ObservationDraft(StrictModel):
    observations: list[Annotated[str, StringConstraints(min_length=1, max_length=500)]] = Field(
        max_length=10
    )
    limitations: list[Annotated[str, StringConstraints(min_length=1, max_length=300)]] = Field(
        max_length=10
    )


class ImageResponse(ObservationDraft):
    project_id: Id
    mode: Literal["mock", "live"]
    source_id: Id
    parent_source_ids: list[Id]
    evidence_type: Literal[EvidenceType.IMAGE_OBSERVATION] = EvidenceType.IMAGE_OBSERVATION
    authorship_verified: Literal[False] = False


class LegalEdition(StrictModel):
    source_id: Id
    kind: Literal[EvidenceType.OFFICIAL_GUIDE] = EvidenceType.OFFICIAL_GUIDE
    title: Text
    publisher: Text
    jurisdiction: Literal["KR"] = "KR"
    official_url: str
    edition: Text
    published_on: date | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    retrieved_on: date | None = None
    reviewed: bool = False
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    content: Text


class SearchRequest(StrictModel):
    context: ProjectContext
    query: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    scope: Literal["project", "legal"] = "project"


class SearchHit(StrictModel):
    source: Source | LegalEdition
    similarity: float = Field(ge=0, le=1)


class SearchResponse(StrictModel):
    project_id: Id
    scope: Literal["project", "legal"]
    backend: Literal["none", "fixture", "pgvector"]
    hits: list[SearchHit]


class BriefSection(StrictModel):
    title: str
    status: Literal["USER_REPORTED", "AVAILABLE", "INCOMPLETE"]
    statements: list[str]
    source_ids: list[Id]


class BriefSections(StrictModel):
    work_overview: BriefSection
    ai_usage: BriefSection
    human_contribution: BriefSection
    evidence_summary: BriefSection
    gaps_and_guidance: BriefSection


class BriefResponse(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    project_id: Id
    snapshot_version: Id
    mode: Literal["mock", "live"]
    status: Literal["DRAFT"] = "DRAFT"
    sections: BriefSections
    sources: list[Source | LegalEdition]
    legal_editions: list[LegalEdition]
    notices: list[str]
