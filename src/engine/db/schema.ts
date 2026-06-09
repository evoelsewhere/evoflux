export const SCHEMA_SQL = `
CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS providers (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  type TEXT NOT NULL,
  api_key TEXT DEFAULT '',
  base_url TEXT DEFAULT '',
  default_model TEXT DEFAULT '',
  models_json TEXT DEFAULT '[]',
  is_default INTEGER DEFAULT 0,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS workflows (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT DEFAULT '',
  nodes_json TEXT NOT NULL DEFAULT '[]',
  edges_json TEXT NOT NULL DEFAULT '[]',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'running',
  input_json TEXT,
  output_json TEXT,
  started_at INTEGER NOT NULL,
  finished_at INTEGER,
  FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS node_runs (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  node_id TEXT NOT NULL,
  node_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'running',
  input_json TEXT,
  output_json TEXT,
  error TEXT,
  started_at INTEGER NOT NULL,
  finished_at INTEGER,
  FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS memory_semantic (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  type TEXT NOT NULL,
  content TEXT NOT NULL,
  embedding BLOB,
  metadata_json TEXT,
  created_at INTEGER NOT NULL,
  access_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS memory_episodic (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  task_description TEXT,
  trajectory_json TEXT NOT NULL,
  outcome TEXT NOT NULL,
  feedback TEXT,
  embedding BLOB,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_procedural (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT NOT NULL,
  pattern TEXT NOT NULL,
  source_episodes_json TEXT,
  usage_count INTEGER DEFAULT 0,
  success_rate REAL DEFAULT 0,
  maturity_score REAL DEFAULT 0,
  embedding BLOB,
  created_at INTEGER NOT NULL,
  last_used_at INTEGER
);

CREATE TABLE IF NOT EXISTS memory_edges (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  target_id TEXT NOT NULL,
  type TEXT NOT NULL,
  weight REAL DEFAULT 1.0,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS env_variables (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  is_secret INTEGER DEFAULT 0,
  UNIQUE(workflow_id, key)
);

CREATE INDEX IF NOT EXISTS idx_runs_workflow ON runs(workflow_id);
CREATE INDEX IF NOT EXISTS idx_node_runs_run ON node_runs(run_id);
CREATE INDEX IF NOT EXISTS idx_semantic_workflow ON memory_semantic(workflow_id);
CREATE INDEX IF NOT EXISTS idx_episodic_workflow ON memory_episodic(workflow_id);
CREATE INDEX IF NOT EXISTS idx_procedural_workflow ON memory_procedural(workflow_id);
CREATE INDEX IF NOT EXISTS idx_edges_source ON memory_edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON memory_edges(target_id);
CREATE TABLE IF NOT EXISTS knowledge_bases (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT DEFAULT '',
  config_json TEXT DEFAULT '{}',
  stats_json TEXT DEFAULT '{}',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS kb_sources (
  id TEXT PRIMARY KEY,
  kb_id TEXT NOT NULL,
  path TEXT NOT NULL,
  type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  file_count INTEGER DEFAULT 0,
  error TEXT,
  git_repo_path TEXT,
  git_branch TEXT,
  git_commit_hash TEXT,
  git_synced_at INTEGER,
  auto_sync INTEGER DEFAULT 0,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (kb_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS kb_documents (
  id TEXT PRIMARY KEY,
  kb_id TEXT NOT NULL,
  source_id TEXT,
  path TEXT NOT NULL,
  name TEXT NOT NULL,
  extension TEXT,
  size INTEGER,
  content_preview TEXT,
  chunk_count INTEGER DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'pending',
  error TEXT,
  git_status TEXT DEFAULT 'clean',
  indexed_content_hash TEXT,
  current_content_hash TEXT,
  git_diff_preview TEXT,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (kb_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE,
  FOREIGN KEY (source_id) REFERENCES kb_sources(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS kb_chunks (
  id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  kb_id TEXT NOT NULL,
  chunk_index INTEGER,
  content TEXT NOT NULL,
  embedding BLOB,
  metadata_json TEXT,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (doc_id) REFERENCES kb_documents(id) ON DELETE CASCADE,
  FOREIGN KEY (kb_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_kb_sources_kb ON kb_sources(kb_id);
CREATE INDEX IF NOT EXISTS idx_kb_documents_kb ON kb_documents(kb_id);
CREATE INDEX IF NOT EXISTS idx_kb_documents_source ON kb_documents(source_id);
CREATE INDEX IF NOT EXISTS idx_kb_chunks_kb ON kb_chunks(kb_id);
CREATE INDEX IF NOT EXISTS idx_kb_chunks_doc ON kb_chunks(doc_id);

CREATE INDEX IF NOT EXISTS idx_env_workflow ON env_variables(workflow_id);
`

export const SCHEMA_VERSION = 4

export const MIGRATIONS: Record<number, string> = {
  2: `
    CREATE TABLE IF NOT EXISTS providers (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      type TEXT NOT NULL,
      api_key TEXT DEFAULT '',
      base_url TEXT DEFAULT '',
      default_model TEXT DEFAULT '',
      models_json TEXT DEFAULT '[]',
      is_default INTEGER DEFAULT 0,
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS settings (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL,
      updated_at INTEGER NOT NULL
    );
  `,
  3: `
    CREATE TABLE IF NOT EXISTS knowledge_bases (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      description TEXT DEFAULT '',
      config_json TEXT DEFAULT '{}',
      stats_json TEXT DEFAULT '{}',
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS kb_sources (
      id TEXT PRIMARY KEY,
      kb_id TEXT NOT NULL,
      path TEXT NOT NULL,
      type TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending',
      file_count INTEGER DEFAULT 0,
      error TEXT,
      git_repo_path TEXT,
      git_branch TEXT,
      git_commit_hash TEXT,
      git_synced_at INTEGER,
      auto_sync INTEGER DEFAULT 0,
      created_at INTEGER NOT NULL,
      FOREIGN KEY (kb_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS kb_documents (
      id TEXT PRIMARY KEY,
      kb_id TEXT NOT NULL,
      source_id TEXT,
      path TEXT NOT NULL,
      name TEXT NOT NULL,
      extension TEXT,
      size INTEGER,
      content_preview TEXT,
      chunk_count INTEGER DEFAULT 0,
      status TEXT NOT NULL DEFAULT 'pending',
      error TEXT,
      git_status TEXT DEFAULT 'clean',
      indexed_content_hash TEXT,
      current_content_hash TEXT,
      git_diff_preview TEXT,
      created_at INTEGER NOT NULL,
      FOREIGN KEY (kb_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE,
      FOREIGN KEY (source_id) REFERENCES kb_sources(id) ON DELETE SET NULL
    );
    CREATE TABLE IF NOT EXISTS kb_chunks (
      id TEXT PRIMARY KEY,
      doc_id TEXT NOT NULL,
      kb_id TEXT NOT NULL,
      chunk_index INTEGER,
      content TEXT NOT NULL,
      embedding BLOB,
      metadata_json TEXT,
      created_at INTEGER NOT NULL,
      FOREIGN KEY (doc_id) REFERENCES kb_documents(id) ON DELETE CASCADE,
      FOREIGN KEY (kb_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_kb_sources_kb ON kb_sources(kb_id);
    CREATE INDEX IF NOT EXISTS idx_kb_documents_kb ON kb_documents(kb_id);
    CREATE INDEX IF NOT EXISTS idx_kb_documents_source ON kb_documents(source_id);
    CREATE INDEX IF NOT EXISTS idx_kb_chunks_kb ON kb_chunks(kb_id);
CREATE INDEX IF NOT EXISTS idx_kb_chunks_doc ON kb_chunks(doc_id);

CREATE VIRTUAL TABLE IF NOT EXISTS kb_chunks_fts USING fts5(
  content,
  content='kb_chunks',
  content_rowid='rowid',
  tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS kb_chunks_fts_ai AFTER INSERT ON kb_chunks BEGIN
  INSERT INTO kb_chunks_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TRIGGER IF NOT EXISTS kb_chunks_fts_ad AFTER DELETE ON kb_chunks BEGIN
  INSERT INTO kb_chunks_fts(kb_chunks_fts, rowid, content) VALUES('delete', old.rowid, old.content);
END;

CREATE TRIGGER IF NOT EXISTS kb_chunks_fts_au AFTER UPDATE ON kb_chunks BEGIN
  INSERT INTO kb_chunks_fts(kb_chunks_fts, rowid, content) VALUES('delete', old.rowid, old.content);
  INSERT INTO kb_chunks_fts(rowid, content) VALUES (new.rowid, new.content);
END;
  `,
  4: `
CREATE TABLE IF NOT EXISTS wiki_entities (
  id TEXT PRIMARY KEY,
  kb_id TEXT NOT NULL,
  name TEXT NOT NULL,
  type TEXT NOT NULL,
  summary TEXT,
  description TEXT,
  chunk_ids TEXT,
  embedding BLOB,
  metadata_json TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  FOREIGN KEY (kb_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS wiki_relationships (
  id TEXT PRIMARY KEY,
  kb_id TEXT NOT NULL,
  source_entity_id TEXT NOT NULL,
  target_entity_id TEXT NOT NULL,
  type TEXT NOT NULL,
  label TEXT,
  weight REAL DEFAULT 1.0,
  chunk_ids TEXT,
  metadata_json TEXT,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (kb_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE,
  FOREIGN KEY (source_entity_id) REFERENCES wiki_entities(id) ON DELETE CASCADE,
  FOREIGN KEY (target_entity_id) REFERENCES wiki_entities(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS wiki_pages (
  id TEXT PRIMARY KEY,
  kb_id TEXT NOT NULL,
  entity_id TEXT,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  type TEXT NOT NULL,
  metadata_json TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  FOREIGN KEY (kb_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE,
  FOREIGN KEY (entity_id) REFERENCES wiki_entities(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS wiki_entity_chunks (
  entity_id TEXT NOT NULL,
  chunk_id TEXT NOT NULL,
  relevance REAL DEFAULT 1.0,
  batch_index INTEGER,
  processed_at INTEGER,
  PRIMARY KEY (entity_id, chunk_id),
  FOREIGN KEY (entity_id) REFERENCES wiki_entities(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS wiki_build_progress (
  id TEXT PRIMARY KEY,
  kb_id TEXT NOT NULL,
  status TEXT NOT NULL,
  total_batches INTEGER,
  completed_batches INTEGER,
  failed_batches INTEGER,
  total_entities INTEGER,
  total_relationships INTEGER,
  started_at INTEGER,
  completed_at INTEGER,
  error_log TEXT,
  FOREIGN KEY (kb_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_wiki_entities_kb ON wiki_entities(kb_id);
CREATE INDEX IF NOT EXISTS idx_wiki_entities_type ON wiki_entities(type);
CREATE INDEX IF NOT EXISTS idx_wiki_entities_name ON wiki_entities(name);
CREATE INDEX IF NOT EXISTS idx_wiki_relationships_kb ON wiki_relationships(kb_id);
CREATE INDEX IF NOT EXISTS idx_wiki_relationships_source ON wiki_relationships(source_entity_id);
CREATE INDEX IF NOT EXISTS idx_wiki_relationships_target ON wiki_relationships(target_entity_id);
CREATE INDEX IF NOT EXISTS idx_wiki_pages_kb ON wiki_pages(kb_id);
  `
}
