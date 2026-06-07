export const SCHEMA_SQL = `
CREATE TABLE IF NOT EXISTS workflow (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT DEFAULT '',
  dsl_json TEXT NOT NULL,
  config_json TEXT,
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
  FOREIGN KEY (workflow_id) REFERENCES workflow(id) ON DELETE CASCADE
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
CREATE INDEX IF NOT EXISTS idx_env_workflow ON env_variables(workflow_id);
`

export const SCHEMA_VERSION = 1
