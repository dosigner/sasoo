-- Additive runtime data. Audit rows intentionally do not cascade with papers.
CREATE TABLE runtime_server_state (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    schema_revision INTEGER NOT NULL,
    owner_id TEXT NOT NULL,
    quiescing INTEGER NOT NULL DEFAULT 0 CHECK(quiescing IN (0,1)),
    library_revision INTEGER NOT NULL DEFAULT 0,
    settings_revision INTEGER NOT NULL DEFAULT 0 CHECK(settings_revision >= 0)
);
CREATE TABLE runtime_credential_epochs (
    provider TEXT PRIMARY KEY CHECK(provider IN ('openai','gemini')),
    epoch INTEGER NOT NULL DEFAULT 0 CHECK(epoch >= 0)
);
CREATE TABLE runtime_operations (
    operation_id TEXT PRIMARY KEY,
    paper_id INTEGER NOT NULL,
    paper_epoch INTEGER NOT NULL,
    kind TEXT NOT NULL,
    source_sha256 TEXT,
    expected_versions_json TEXT NOT NULL,
    state TEXT NOT NULL,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at_ms INTEGER NOT NULL
);
CREATE TABLE runtime_imports (
    import_id TEXT PRIMARY KEY,
    source_sha256 TEXT NOT NULL,
    library_revision INTEGER NOT NULL,
    state TEXT NOT NULL,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at_ms INTEGER NOT NULL
);
CREATE TABLE runtime_requests (
    request_id TEXT PRIMARY KEY,
    paper_id INTEGER,
    execution_id TEXT,
    attempt_id TEXT,
    operation_id TEXT,
    import_id TEXT,
    generation INTEGER,
    state TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    remote_id TEXT,
    terminal TEXT,
    response_ref TEXT,
    created_at_ms INTEGER,
    dispatched_at_ms INTEGER,
    settled_at_ms INTEGER
);
CREATE TABLE runtime_usage_events (
    event_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    event_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    usage_state TEXT NOT NULL,
    received_at_ms INTEGER NOT NULL,
    UNIQUE(request_id,event_hash)
);
CREATE TABLE runtime_artifact_versions (
    version_id TEXT PRIMARY KEY,
    paper_id INTEGER,
    execution_id TEXT,
    attempt_id TEXT,
    operation_id TEXT,
    import_id TEXT,
    resource_key TEXT NOT NULL,
    source_sha256 TEXT,
    artifact_sha256 TEXT NOT NULL,
    relative_path TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL
);
CREATE TABLE runtime_latest (
    paper_id INTEGER NOT NULL,
    resource_key TEXT NOT NULL,
    version_id TEXT NOT NULL REFERENCES runtime_artifact_versions(version_id),
    PRIMARY KEY(paper_id,resource_key)
);
CREATE TABLE runtime_tombstones (
    paper_id INTEGER PRIMARY KEY,
    paper_epoch INTEGER NOT NULL,
    deleted_at_ms INTEGER NOT NULL
);
CREATE TABLE runtime_delete_intents (
    intent_id TEXT PRIMARY KEY,
    paper_id INTEGER NOT NULL,
    paths_json TEXT NOT NULL,
    state TEXT NOT NULL,
    error TEXT,
    created_at_ms INTEGER NOT NULL
);
CREATE TABLE runtime_permits (
    request_id TEXT PRIMARY KEY,
    provider TEXT,
    class TEXT NOT NULL,
    reservation_decimal TEXT,
    policy_version TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL
);
CREATE INDEX idx_runtime_requests_paper ON runtime_requests(paper_id,created_at_ms);
CREATE INDEX idx_runtime_operations_paper ON runtime_operations(paper_id,state);
CREATE INDEX idx_runtime_artifact_versions_paper ON runtime_artifact_versions(paper_id,resource_key);

CREATE TABLE runtime_paper_epochs (
    paper_id INTEGER PRIMARY KEY,
    paper_epoch INTEGER NOT NULL DEFAULT 0 CHECK(paper_epoch >= 0),
    source_sha256 BLOB CHECK(source_sha256 IS NULL OR length(source_sha256) = 32),
    current_execution_id TEXT,
    updated_at_ms INTEGER
);
CREATE TABLE runtime_executions (
    execution_id TEXT PRIMARY KEY,
    paper_id INTEGER NOT NULL,
    paper_epoch INTEGER NOT NULL,
    source_sha256 BLOB NOT NULL CHECK(length(source_sha256) = 32),
    extraction_version TEXT NOT NULL,
    config_bytes BLOB NOT NULL,
    config_hash BLOB NOT NULL CHECK(length(config_hash) = 32),
    settings_revision INTEGER NOT NULL,
    state TEXT NOT NULL,
    current_attempt_id TEXT,
    generation INTEGER NOT NULL DEFAULT 0,
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancel_requested IN (0,1)),
    created_at_ms INTEGER NOT NULL
);
CREATE TABLE runtime_attempts (
    attempt_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL REFERENCES runtime_executions(execution_id),
    paper_id INTEGER NOT NULL,
    generation INTEGER NOT NULL,
    state TEXT NOT NULL,
    claim_nonce TEXT NOT NULL,
    boot_id TEXT NOT NULL,
    worker_identity_json TEXT,
    started_at_ms INTEGER NOT NULL,
    heartbeat_at_ms INTEGER,
    lease_deadline_ms INTEGER,
    finished_at_ms INTEGER,
    error TEXT
);
CREATE INDEX idx_runtime_executions_paper ON runtime_executions(paper_id,created_at_ms);
CREATE INDEX idx_runtime_attempts_execution ON runtime_attempts(execution_id,state);
