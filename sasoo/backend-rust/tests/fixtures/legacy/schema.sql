
CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    authors TEXT,
    year INTEGER,
    journal TEXT,
    doi TEXT,
    domain TEXT DEFAULT 'optics',
    agent_used TEXT DEFAULT 'photon',
    folder_name TEXT NOT NULL,
    tags TEXT,
    status TEXT DEFAULT 'pending',
    analyzed_at DATETIME,
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    explanation_level TEXT,
    analysis_focus TEXT,
    pdf_file_uri TEXT,
    pdf_file_expires_at TEXT,
    openalex_subfield_id INTEGER
);

CREATE TABLE IF NOT EXISTS analysis_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER REFERENCES papers(id) ON DELETE CASCADE,
    phase TEXT NOT NULL,
    result TEXT NOT NULL,
    model_used TEXT,
    tokens_in INTEGER,
    tokens_out INTEGER,
    cost_usd REAL,
    input_hash TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    interaction_id TEXT
);

CREATE TABLE IF NOT EXISTS figures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER REFERENCES papers(id) ON DELETE CASCADE,
    figure_num TEXT,
    caption TEXT,
    file_path TEXT,
    ai_analysis TEXT,
    quality TEXT,
    detailed_explanation TEXT,
    page_number INTEGER,
    bbox_json TEXT,
    extraction_engine TEXT,
    confidence REAL,
    classifier_label TEXT,
    classifier_model TEXT,
    parent_figure_id INTEGER REFERENCES figures(id) ON DELETE SET NULL,
    is_composite INTEGER,
    resolver_version TEXT,
    extraction_status TEXT
);

CREATE TABLE IF NOT EXISTS tables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER REFERENCES papers(id) ON DELETE CASCADE,
    table_num TEXT,
    caption TEXT,
    page_number INTEGER,
    bbox_json TEXT,
    csv_path TEXT,
    html_path TEXT,
    markdown_text TEXT,
    confidence REAL,
    parse_method TEXT,
    classifier_model TEXT,
    resolver_version TEXT,
    extraction_status TEXT,
    repair_attempted INTEGER DEFAULT 0,
    repair_reason TEXT,
    repair_confidence REAL,
    review_required INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_papers_status ON papers(status);
CREATE INDEX IF NOT EXISTS idx_papers_domain ON papers(domain);
CREATE INDEX IF NOT EXISTS idx_papers_year ON papers(year);
CREATE INDEX IF NOT EXISTS idx_analysis_paper_id ON analysis_results(paper_id);
CREATE INDEX IF NOT EXISTS idx_analysis_latest_phase ON analysis_results(paper_id, phase, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_analysis_phase ON analysis_results(phase);
CREATE INDEX IF NOT EXISTS idx_analysis_created_at ON analysis_results(created_at);
CREATE INDEX IF NOT EXISTS idx_analysis_cost ON analysis_results(cost_usd);
CREATE INDEX IF NOT EXISTS idx_analysis_cache ON analysis_results(paper_id, phase, input_hash);
CREATE INDEX IF NOT EXISTS idx_figures_paper_id ON figures(paper_id);
CREATE INDEX IF NOT EXISTS idx_tables_paper_id ON tables(paper_id);
CREATE INDEX IF NOT EXISTS idx_tables_sort ON tables(paper_id, page_number, table_num);

CREATE TABLE IF NOT EXISTS analysis_cache_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER REFERENCES papers(id) ON DELETE CASCADE,
    phase TEXT NOT NULL,
    input_hash TEXT,
    source_model TEXT,
    estimated_cost_usd REAL DEFAULT 0,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_analysis_cache_events_created_at ON analysis_cache_events(created_at);
CREATE INDEX IF NOT EXISTS idx_analysis_cache_events_phase ON analysis_cache_events(phase);

CREATE TABLE IF NOT EXISTS experiment_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER REFERENCES papers(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    model_used TEXT,
    tokens_in INTEGER,
    tokens_out INTEGER,
    cost_usd REAL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_experiment_plans_paper_id ON experiment_plans(paper_id);

-- 토의 기록(docs/superpowers/specs/2026-10-07-discussion-design.md 6장). 논문당 하나이며
-- 맥락 초기화는 kind='reset' 행이다. 그 행 이후의 user와 complete sasoo만 맥락으로 보낸다.
CREATE TABLE IF NOT EXISTS discussion_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'complete',
    reset_reason TEXT,
    model_used TEXT,
    tokens_in INTEGER,
    tokens_out INTEGER,
    cost_usd REAL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_discussion_messages_paper ON discussion_messages(paper_id, id);


CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE IF NOT EXISTS analysis_runs (
    paper_id         INTEGER PRIMARY KEY,
    status           TEXT NOT NULL DEFAULT 'queued',
    generation       INTEGER NOT NULL DEFAULT 0,
    current_phase    TEXT,
    progress_pct     REAL NOT NULL DEFAULT 0,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    attempts         INTEGER NOT NULL DEFAULT 0,
    pid              INTEGER,
    error_message    TEXT,
    started_at       TEXT,
    last_attempt_at  TEXT,
    heartbeat_at     TEXT,
    updated_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_status ON analysis_runs(status, heartbeat_at);
