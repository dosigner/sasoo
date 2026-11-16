-- FigureExplain identity and resources extend the existing runtime ledgers.
CREATE TABLE runtime_figure_resources (
    paper_id INTEGER NOT NULL,
    figure_id INTEGER NOT NULL,
    source_sha256 BLOB NOT NULL CHECK(length(source_sha256)=32),
    asset_sha256 BLOB NOT NULL CHECK(length(asset_sha256)=32),
    version_token TEXT NOT NULL,
    PRIMARY KEY(paper_id,figure_id)
);
CREATE TABLE runtime_figure_snapshots (
    operation_id TEXT PRIMARY KEY REFERENCES runtime_operations(operation_id),
    figure_id INTEGER NOT NULL,
    identity_json TEXT NOT NULL,
    identity_hash BLOB NOT NULL CHECK(length(identity_hash)=32),
    owner_id TEXT NOT NULL,
    source_bytes BLOB NOT NULL,
    asset_bytes BLOB NOT NULL,
    config_bytes BLOB NOT NULL,
    config_hash BLOB NOT NULL CHECK(length(config_hash)=32),
    settings_revision INTEGER NOT NULL,
    credential_refs_json TEXT NOT NULL,
    resource_version TEXT NOT NULL
);
CREATE INDEX idx_runtime_figure_identity ON runtime_figure_snapshots(identity_hash);
