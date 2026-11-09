-- Dedicated Idea2IP database only. Does not touch Spring domain tables.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS idea2ip_chunks (
  namespace text NOT NULL CHECK (namespace IN ('project', 'legal')),
  project_id text NOT NULL,
  snapshot_version text NOT NULL,
  index_version text NOT NULL,
  source_id text NOT NULL,
  embedding_model text NOT NULL,
  payload jsonb NOT NULL,
  content_sha256 text NOT NULL,
  embedding vector(1024) NOT NULL,
  PRIMARY KEY(namespace, project_id, snapshot_version, index_version, source_id),
  CHECK (payload->>'source_id' = source_id),
  CHECK ((namespace = 'project' AND payload->>'project_id' = project_id
          AND payload->>'kind' <> 'OFFICIAL_GUIDE')
      OR (namespace = 'legal' AND project_id = '__legal__'
          AND snapshot_version = '__legal__' AND payload->>'kind' = 'OFFICIAL_GUIDE'))
);
CREATE INDEX IF NOT EXISTS idea2ip_chunks_scope_idx
  ON idea2ip_chunks(namespace, project_id, snapshot_version, index_version, embedding_model);
-- Exact cosine search first. Add HNSW only after corpus-specific quality evaluation.
