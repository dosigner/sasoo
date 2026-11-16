CREATE TABLE pdf_candidate_versions (
    version TEXT PRIMARY KEY,
    paper_id INTEGER NOT NULL REFERENCES papers(id),
    filename TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    options_sha256 TEXT NOT NULL,
    document_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(paper_id, version)
);
CREATE TABLE pdf_candidate_current (
    paper_id INTEGER PRIMARY KEY REFERENCES papers(id),
    version TEXT NOT NULL,
    FOREIGN KEY(paper_id, version) REFERENCES pdf_candidate_versions(paper_id, version)
);
