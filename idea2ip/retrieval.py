"""Scoped pgvector search; adapts Centerton's cutoff and injected pipeline pattern."""

import math
import re
from functools import lru_cache

import httpx

from .config import Settings
from .errors import ServiceError
from .legal import load_catalog
from .models import LegalEdition, SearchHit, SearchRequest, SearchResponse, Source

SELECT_SQL = """
SELECT source_id, payload, embedding <=> %s::vector AS distance
FROM idea2ip_chunks
WHERE namespace = %s AND project_id = %s AND index_version = %s
  AND embedding_model = %s AND snapshot_version = %s
ORDER BY embedding <=> %s::vector
LIMIT %s
"""


def vector_literal(values: list[float]) -> str:
    if len(values) != 1024 or any(not math.isfinite(v) for v in values):
        raise ServiceError("EMBEDDING_INVALID", "KURE 임베딩은 유한한 1024차원이어야 합니다", 503)
    if not any(values):
        raise ServiceError("EMBEDDING_INVALID", "영벡터는 사용할 수 없습니다", 503)
    return "[" + ",".join(f"{v:.9f}" for v in values) + "]"


@lru_cache(maxsize=1)
def load_kure(model_name: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name, trust_remote_code=False)


def embed(text: str, settings: Settings) -> list[float]:
    try:
        if settings.embedding_url:
            with httpx.Client(timeout=30, trust_env=False) as client:
                response = client.post(
                    settings.embedding_url,
                    json={"model": settings.kure_model, "input": [text]},
                )
                response.raise_for_status()
                data = response.json()
            if data["model"] != settings.kure_model or data["dimensions"] != 1024:
                raise ValueError("embedding model/dimension mismatch")
            values = [float(v) for v in data["embeddings"][0]]
        else:
            model = load_kure(settings.kure_model)
            values = [
                float(v)
                for v in model.encode([text], normalize_embeddings=True, show_progress_bar=False)[0]
            ]
        vector_literal(values)
        return values
    except ServiceError:
        raise
    except Exception as exc:
        raise ServiceError(
            "EMBEDDING_UNAVAILABLE", "KURE 모델/임베딩 서비스 이용 불가", 503
        ) from exc


def fetch_rows(vector: str, request: SearchRequest, settings: Settings) -> list[dict]:
    if not settings.database_url.get_secret_value():
        raise ServiceError("VECTOR_DB_UNCONFIGURED", "IDEA2IP_DATABASE_URL 미설정", 503)
    try:
        import psycopg
        from psycopg.rows import dict_row

        scope = request.scope
        project = request.context.project_id if scope == "project" else "__legal__"
        with psycopg.connect(
            settings.database_url.get_secret_value(),
            connect_timeout=5,
            row_factory=dict_row,
            options="-c statement_timeout=10000",
        ) as connection:
            rows = connection.execute(
                SELECT_SQL,
                (
                    vector,
                    scope,
                    project,
                    settings.index_version,
                    settings.kure_model,
                    request.context.snapshot_version if scope == "project" else "__legal__",
                    vector,
                    settings.top_k * 2,
                ),
            ).fetchall()
        return rows
    except Exception as exc:
        raise ServiceError("VECTOR_DB_UNAVAILABLE", "pgvector 연결/검색 실패", 503) from exc


def select_hits(
    rows: list[dict], request: SearchRequest, settings: Settings, catalog: list[LegalEdition]
) -> list[SearchHit]:
    allowed_legal = {row.source_id: row for row in catalog}
    kept = []
    for row in rows:
        distance = float(row["distance"])
        if not math.isfinite(distance):
            raise ServiceError("VECTOR_DATA_INVALID", "검색 거리 값이 유효하지 않습니다", 503)
        score = max(0.0, min(1.0, 1.0 - distance))
        if score < settings.min_similarity:
            continue
        payload = row["payload"]
        if request.scope == "project":
            source = Source.model_validate(payload)
            # Defense in depth if a DB adapter or query is accidentally changed.
            if source.project_id != request.context.project_id:
                raise ServiceError("SCOPE_VIOLATION", "다른 프로젝트의 검색 결과 차단", 503)
            if source.kind.value == "OFFICIAL_GUIDE":
                raise ServiceError("SCOPE_VIOLATION", "프로젝트 색인의 법률자료 차단", 503)
        else:
            source = allowed_legal.get(row["source_id"])
            if source is None or source.model_dump(mode="json") != payload:
                continue
        if source.source_id != row["source_id"]:
            raise ServiceError("VECTOR_DATA_INVALID", "검색 출처 ID 불일치", 503)
        kept.append(SearchHit(source=source, similarity=score))
    return sorted(kept, key=lambda h: h.similarity, reverse=True)[: settings.top_k]


def search(
    request: SearchRequest, settings: Settings, embedder=embed, row_fetcher=fetch_rows
) -> SearchResponse:
    if settings.retrieval == "none":
        return SearchResponse(
            project_id=request.context.project_id, scope=request.scope, backend="none", hits=[]
        )
    catalog = load_catalog(settings) if request.scope == "legal" else []
    if settings.retrieval == "fixture":
        # Lexical fixture only: this is deliberately not called semantic retrieval.
        sources = request.context.sources if request.scope == "project" else catalog
        tokens = set(re.findall(r"\w+", request.query.lower()))
        rows = []
        for source in sources:
            haystack = source.title.lower() + " " + source.content.lower()
            score = sum(token in haystack for token in tokens) / max(len(tokens), 1)
            if score > 0:
                rows.append(
                    {
                        "source_id": source.source_id,
                        "payload": source.model_dump(mode="json"),
                        "distance": 1 - score,
                    }
                )
    else:
        if not settings.database_url.get_secret_value():
            raise ServiceError("VECTOR_DB_UNCONFIGURED", "IDEA2IP_DATABASE_URL 미설정", 503)
        rows = row_fetcher(vector_literal(embedder(request.query, settings)), request, settings)
    try:
        hits = select_hits(rows, request, settings, catalog)
    except (ValueError, KeyError, TypeError) as exc:
        raise ServiceError("VECTOR_DATA_INVALID", "검색 자료 스키마 검증 실패", 503) from exc
    return SearchResponse(
        project_id=request.context.project_id,
        scope=request.scope,
        backend=settings.retrieval,
        hits=hits,
    )
