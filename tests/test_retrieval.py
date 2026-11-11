import hashlib
from datetime import date

import pytest
from pydantic import SecretStr

from idea2ip.errors import ServiceError
from idea2ip.legal import eligible, load_catalog
from idea2ip.models import LegalEdition, SearchRequest
from idea2ip.retrieval import SELECT_SQL, search, select_hits, vector_literal


def test_scoped_injected_vector_search(settings, context):
    settings = settings.model_copy(
        update={
            "retrieval": "pgvector",
            "database_url": SecretStr("configured"),
        }
    )
    request = SearchRequest(context=context, query="눈 수정")

    def embedder(query, config):
        assert query == "눈 수정"
        return [0.1] * 1024

    def rows(vector, req, config):
        assert req.context.project_id == context.project_id
        assert len(vector.split(",")) == 1024
        return [
            {
                "source_id": context.sources[0].source_id,
                "payload": context.sources[0].model_dump(mode="json"),
                "distance": 0.5,
            },
            {
                "source_id": context.sources[1].source_id,
                "payload": context.sources[1].model_dump(mode="json"),
                "distance": 0.51,
            },
        ]

    result = search(request, settings, embedder, rows)
    assert len(result.hits) == 1
    assert result.hits[0].similarity == 0.5
    for term in (
        "project_id = %s",
        "namespace = %s",
        "index_version = %s",
        "snapshot_version = %s",
    ):
        assert term in SELECT_SQL


def test_cross_project_rows_fail_closed(settings, context):
    source = context.sources[0].model_dump(mode="json")
    source["project_id"] = "another-project"
    with pytest.raises(ServiceError) as error:
        select_hits(
            [{"source_id": source["source_id"], "payload": source, "distance": 0.1}],
            SearchRequest(context=context, query="작품"),
            settings,
            [],
        )
    assert error.value.code == "SCOPE_VIOLATION"


@pytest.mark.parametrize("vector", [[0.1], [float("nan")] * 1024, [0.0] * 1024])
def test_vector_validation(vector):
    with pytest.raises(ServiceError):
        vector_literal(vector)


def test_vector_db_unconfigured_is_explicit(settings, context):
    with pytest.raises(ServiceError) as error:
        search(
            SearchRequest(context=context, query="작품"),
            settings.model_copy(update={"retrieval": "pgvector"}),
        )
    assert error.value.code == "VECTOR_DB_UNCONFIGURED"


def test_legal_placeholder_is_excluded(settings):
    assert load_catalog(settings) == []


def legal():
    content = "테스트용 공식 지침 본문; 실제 법률 안내가 아닙니다."
    return LegalEdition(
        source_id="law-test",
        title="가상 테스트 지침 — 실제 공식 자료 아님",
        publisher="가상 테스트 발행기관",
        edition="fixture-v1",
        official_url="https://www.copyright.or.kr/test",
        published_on=date(2026, 1, 1),
        effective_from=date(2026, 1, 1),
        retrieved_on=date(2026, 1, 2),
        reviewed=True,
        content=content,
        sha256=hashlib.sha256(content.encode()).hexdigest(),
    )


@pytest.mark.parametrize("mutation", ["expired", "future", "unreviewed", "hash", "host"])
def test_legal_edition_controls(mutation):
    item = legal()
    assert eligible(item, date(2026, 11, 9))
    if mutation == "expired":
        item.effective_to = date(2026, 10, 1)
    elif mutation == "future":
        item.effective_from = date(2027, 1, 1)
    elif mutation == "unreviewed":
        item.reviewed = False
    elif mutation == "hash":
        item.content = "바뀐 내용"
    else:
        item.official_url = "https://www.copyright.or.kr.attacker.example/test"
    assert not eligible(item, date(2026, 11, 9))


def test_legal_row_must_match_catalog_exactly(settings, context):
    item = legal()
    payload = item.model_dump(mode="json")
    payload["content"] = "다른 내용"
    hits = select_hits(
        [{"source_id": item.source_id, "payload": payload, "distance": 0.1}],
        SearchRequest(context=context, query="지침", scope="legal"),
        settings,
        [item],
    )
    assert hits == []


@pytest.mark.parametrize(
    "scope,expected_project,expected_snapshot",
    [("project", "project-moon-garden", "v1"), ("legal", "__legal__", "__legal__")],
)
def test_db_adapter_binds_scope_parameters(
    settings, context, monkeypatch, scope, expected_project, expected_snapshot
):
    import sys
    from types import ModuleType

    from idea2ip.retrieval import fetch_rows

    seen = {}

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params):
            seen["sql"], seen["params"] = sql, params
            return self

        def fetchall(self):
            return []

    def connect(dsn, **kwargs):
        assert kwargs["connect_timeout"] == 5
        assert "statement_timeout=10000" in kwargs["options"]
        return Connection()

    module = ModuleType("psycopg")
    module.connect = connect
    rows = ModuleType("psycopg.rows")
    rows.dict_row = object()
    monkeypatch.setitem(sys.modules, "psycopg", module)
    monkeypatch.setitem(sys.modules, "psycopg.rows", rows)
    settings = settings.model_copy(update={"database_url": SecretStr("local-test-dsn")})
    assert (
        fetch_rows("[vector]", SearchRequest(context=context, query="test", scope=scope), settings)
        == []
    )
    assert seen["params"] == (
        "[vector]",
        scope,
        expected_project,
        settings.index_version,
        settings.kure_model,
        expected_snapshot,
        "[vector]",
        settings.top_k * 2,
    )


def test_embedding_service_unavailable_is_explicit(settings, monkeypatch):
    from idea2ip import retrieval

    def unavailable(_model):
        raise RuntimeError("offline")

    monkeypatch.setattr(retrieval, "load_kure", unavailable)
    with pytest.raises(ServiceError) as error:
        retrieval.embed("테스트", settings)
    assert error.value.code == "EMBEDDING_UNAVAILABLE"


def test_eligible_legal_guidance_is_separate_in_brief(settings, context, tmp_path):
    import json

    from idea2ip.engine import Engine

    item = legal()
    item.content = "저작권 등록 신청 창작 테스트 자료. 실제 법률 안내가 아닙니다."
    item.sha256 = hashlib.sha256(item.content.encode()).hexdigest()
    path = tmp_path / "legal.json"
    path.write_text(json.dumps([item.model_dump(mode="json")]), encoding="utf-8")
    engine = Engine(settings.model_copy(update={"retrieval": "fixture", "legal_catalog": path}))
    report = engine.brief(context)
    assert report.legal_editions[0].source_id == item.source_id
    assert item.source_id in report.sections.gaps_and_guidance.source_ids
    assert item.source_id not in report.sections.human_contribution.source_ids
    assert all(s.source_id != "legal-placeholder-kr-v0" for s in report.sources)


def test_brief_preserves_test_edition_metadata(settings, context, tmp_path):
    import json

    from idea2ip.engine import Engine

    item = legal()
    item.content = "저작권 등록 신청 창작 테스트 자료. 실제 법률 안내가 아닙니다."
    item.sha256 = hashlib.sha256(item.content.encode()).hexdigest()
    path = tmp_path / "test-only-catalog.json"
    path.write_text(json.dumps([item.model_dump(mode="json")]))
    report = Engine(
        settings.model_copy(update={"retrieval": "fixture", "legal_catalog": path})
    ).brief(context)
    assert report.legal_editions == [item]
    saved = next(source for source in report.sources if source.source_id == item.source_id)
    assert saved == item
