CREATE TABLE pdf_candidate_operations (
    operation_id TEXT PRIMARY KEY,
    version TEXT REFERENCES pdf_candidate_versions(version),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
