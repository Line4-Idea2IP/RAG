"""Explicit, transactional ingestion; no automatic DB writes during API requests."""

import argparse
import hashlib
import json
from pathlib import Path

from idea2ip.config import Settings
from idea2ip.legal import load_catalog
from idea2ip.models import ProjectContext
from idea2ip.retrieval import embed, vector_literal

UPSERT = """
INSERT INTO idea2ip_chunks(namespace, project_id, snapshot_version, index_version,
 source_id, embedding_model, payload, content_sha256, embedding)
VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::vector)
ON CONFLICT(namespace, project_id, snapshot_version, index_version, source_id)
DO UPDATE SET embedding_model=EXCLUDED.embedding_model, payload=EXCLUDED.payload,
 content_sha256=EXCLUDED.content_sha256, embedding=EXCLUDED.embedding
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, help="project snapshot JSON")
    parser.add_argument("--legal", action="store_true", help="ingest eligible server catalog")
    args = parser.parse_args()
    if bool(args.project) == args.legal:
        parser.error("choose exactly one of --project or --legal")
    settings = Settings()
    if not settings.database_url.get_secret_value():
        parser.error("IDEA2IP_DATABASE_URL is required")
    if args.legal:
        sources = load_catalog(settings)
        namespace, project, snapshot = "legal", "__legal__", "__legal__"
    else:
        context = ProjectContext.model_validate_json(args.project.read_text(encoding="utf-8"))
        sources = context.sources
        namespace, project, snapshot = "project", context.project_id, context.snapshot_version
    if not sources:
        print("No eligible sources; nothing written.")
        return
    # Prepare all vectors before opening a transaction. Failure leaves existing rows untouched.
    rows = []
    for source in sources:
        body = source.model_dump_json()
        rows.append(
            (
                namespace,
                project,
                snapshot,
                settings.index_version,
                source.source_id,
                settings.kure_model,
                body,
                hashlib.sha256(body.encode()).hexdigest(),
                vector_literal(embed(source.title + "\n" + source.content, settings)),
            )
        )
    import psycopg

    with psycopg.connect(settings.database_url.get_secret_value(), connect_timeout=5) as connection:
        with connection.cursor() as cursor:
            cursor.executemany(UPSERT, rows)
    print(json.dumps({"ingested": len(rows), "namespace": namespace, "project_id": project}))


if __name__ == "__main__":
    main()
