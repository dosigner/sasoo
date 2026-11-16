use sasoo_backend::{
    analysis::config::{ConfigInput, FrozenAgent, PdfIdentity, resolve_config},
    error::SasooError,
    runtime::figure_explain::{FigureCore, FigureInput, FigureOutcome, Publication},
    storage::{
        db::{Db, DbAccess, open_db},
        migrations::{create_backup, migrate_figure_runtime, migrate_owned_db},
        paths::RuntimePaths,
    },
    types::{KeyEpoch, PaperId, ProviderId, SecretRef},
};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    path::PathBuf,
    sync::{Arc, Barrier},
};
use tempfile::TempDir;

const SOURCE: &[u8] = b"%PDF-1.4\nsynthetic paper bytes\n%%EOF";
const ASSET: &[u8] = b"synthetic decoded figure asset bytes";
fn digest(bytes: &[u8]) -> [u8; 32] {
    Sha256::digest(bytes).into()
}

fn config(source: &[u8]) -> ConfigInput {
    let agent = "# Synthetic figure agent\nExplain the supplied figure.".to_owned();
    ConfigInput {
        schema_version: 1,
        provider_roles: BTreeMap::from([("figure".into(), ProviderId::OpenAi)]),
        models: BTreeMap::from([("figure".into(), "synthetic-figure-model".into())]),
        efforts: BTreeMap::from([("figure".into(), None)]),
        prompt_schema_hashes: BTreeMap::from([(
            "figure-prompt".into(),
            digest(b"synthetic prompt"),
        )]),
        raw_agent_hash: Some(digest(agent.as_bytes())),
        frozen_agent_catalog: vec![FrozenAgent {
            name: "synthetic".into(),
            enabled: true,
            keywords: vec!["figure".into()],
            sha256: digest(agent.as_bytes()),
            raw_md: agent,
        }],
        agent_selection_policy_version: "synthetic-policy-v1".into(),
        profile: json!({"reader":"synthetic"}),
        focus: json!({"figure":true}),
        pdf_identity: PdfIdentity {
            source_sha256: digest(source),
            engine: "synthetic".into(),
            engine_revision: "v1".into(),
            options_hash: digest(b"synthetic PDF options"),
        },
        limits: BTreeMap::from([("max_output_tokens".into(), 256)]),
        cache_version: "synthetic-figure-v1".into(),
        secret_refs: vec![SecretRef {
            provider: ProviderId::OpenAi,
            epoch: KeyEpoch(3),
        }],
    }
}
fn input() -> FigureInput {
    FigureInput {
        paper_id: PaperId(1),
        figure_id: 7,
        source_bytes: SOURCE.to_vec(),
        asset_bytes: ASSET.to_vec(),
        config: resolve_config(&config(SOURCE)).unwrap(),
        settings_revision: 0,
    }
}
fn outcome(request_id: sasoo_backend::types::LocalRequestId) -> FigureOutcome {
    FigureOutcome {
        request_id,
        explanation: Some("A valid synthetic explanation.".into()),
        raw: "{\"explanation\":\"A valid synthetic explanation.\"}".into(),
        terminal: true,
        usage: json!({"tokens_in":100,"tokens_out":25,"tokens_cached":20,"cost_usd":0.01}),
    }
}
struct Fixture {
    _dir: TempDir,
    paths: RuntimePaths,
    db: Db,
    core: FigureCore,
}
fn fixture() -> Fixture {
    let dir = TempDir::new().unwrap();
    let root = dir.path().to_path_buf();
    std::fs::write(
        root.join(".sasoo-rust-isolated-fixture"),
        "synthetic-only\n",
    )
    .unwrap();
    let paths = RuntimePaths {
        app_data_root: root.clone(),
        db_path: root.join("sasoo.db"),
        config_path: root.join("config.json"),
        default_library_root: root.join("library"),
        library_root: root.join("library"),
        library_search_roots: vec![root.join("library")],
        owner_lock_path: root.join("owner.lock"),
    };
    let conn = rusqlite::Connection::open(&paths.db_path).unwrap();
    conn.execute_batch(include_str!("fixtures/legacy/schema.sql"))
        .unwrap();
    conn.execute_batch("INSERT INTO papers(id,title,folder_name,status) VALUES(1,'Synthetic','one','completed'),(2,'Other','two','completed'); INSERT INTO figures(id,paper_id,figure_num,detailed_explanation) VALUES(7,1,'1','legacy explanation'),(8,2,'1','other legacy'); INSERT INTO analysis_results(paper_id,phase,result,cost_usd) VALUES(1,'recipe','paid result',1.25);").unwrap();
    let db = open_db(&paths, DbAccess::ServerOwner).unwrap();
    let backup = create_backup(&db, &root.join("before-runtime.sqlite")).unwrap();
    migrate_owned_db(&db, &backup).unwrap();
    conn.execute(
        "INSERT INTO runtime_credential_epochs(provider,epoch) VALUES('openai',3)",
        [],
    )
    .unwrap();
    let backup = create_backup(&db, &root.join("before-figure.sqlite")).unwrap();
    migrate_figure_runtime(&db, &backup).unwrap();
    let core = FigureCore::open(db.clone(), root.join("figure-spool")).unwrap();
    core.register_resource(PaperId(1), 7, SOURCE, ASSET)
        .unwrap();
    Fixture {
        _dir: dir,
        paths,
        db,
        core,
    }
}
fn count(f: &Fixture, table: &str) -> i64 {
    let c = rusqlite::Connection::open(&f.paths.db_path).unwrap();
    c.query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |r| r.get(0))
        .unwrap()
}
fn settle(f: &Fixture, o: FigureOutcome) -> PathBuf {
    let path = f.core.spool(&o).unwrap();
    f.core.ingest(&path).unwrap();
    path
}

#[test]
fn same_identity_two_connections_dispatch_and_publish_exactly_once() {
    let f = fixture();
    let peer = FigureCore::open(
        f.db.owner_peer().unwrap(),
        f.paths.app_data_root.join("figure-spool"),
    )
    .unwrap();
    let barrier = Arc::new(Barrier::new(2));
    let tasks = [f.core.clone(), peer].map(|core| {
        let b = barrier.clone();
        std::thread::spawn(move || {
            b.wait();
            core.accept(input()).unwrap()
        })
    });
    let [a, b] = tasks;
    let a = a.join().unwrap();
    let b = b.join().unwrap();
    assert_eq!(a.scope, b.scope);
    assert_eq!(a.request_id, b.request_id);
    assert_ne!(a.created, b.created);
    assert!(f.core.dispatch(&a).unwrap());
    assert!(!f.core.dispatch(&b).unwrap());
    let path = settle(&f, outcome(a.request_id));
    assert!(matches!(
        f.core.publish(&path).unwrap(),
        Publication::Published(_)
    ));
    assert!(matches!(
        f.core.publish(&path).unwrap(),
        Publication::AlreadyPublished(_)
    ));
    assert_eq!(count(&f, "runtime_operations"), 1);
    assert_eq!(count(&f, "runtime_requests"), 1);
    assert_eq!(count(&f, "runtime_usage_events"), 1);
    assert_eq!(count(&f, "runtime_artifact_versions"), 1);
    assert_eq!(count(&f, "runtime_latest"), 1);
    let c = rusqlite::Connection::open(&f.paths.db_path).unwrap();
    let (source,asset,config_bytes,config_hash):(Vec<u8>,Vec<u8>,Vec<u8>,Vec<u8>)=c.query_row("SELECT source_bytes,asset_bytes,config_bytes,config_hash FROM runtime_figure_snapshots",[],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?))).unwrap();
    assert_eq!(source, SOURCE);
    assert_eq!(asset, ASSET);
    assert_eq!(digest(&config_bytes).to_vec(), config_hash);
    assert_eq!(
        c.query_row(
            "SELECT detailed_explanation FROM figures WHERE id=7",
            [],
            |r| r.get::<_, String>(0)
        )
        .unwrap(),
        "legacy explanation"
    );
    assert_eq!(
        c.query_row(
            "SELECT cost_usd FROM analysis_results WHERE paper_id=1",
            [],
            |r| r.get::<_, f64>(0)
        )
        .unwrap(),
        1.25
    );
}

#[test]
fn missing_inputs_and_source_or_asset_mismatch_are_blocked_without_a_request() {
    for change in [
        "source",
        "asset",
        "config-source",
        "settings",
        "missing-asset",
    ] {
        let f = fixture();
        let mut i = input();
        match change {
            "source" => i.source_bytes.push(1),
            "asset" => i.asset_bytes.push(2),
            "config-source" => i.config = resolve_config(&config(b"different source")).unwrap(),
            "settings" => i.settings_revision = 1,
            "missing-asset" => i.asset_bytes.clear(),
            _ => unreachable!(),
        }
        assert!(f.core.accept(i).is_err(), "{change}");
        assert_eq!(count(&f, "runtime_requests"), 0);
    }
}

#[test]
fn every_publication_fence_rejects_stale_output_but_preserves_late_usage_and_latest() {
    for mutation in [
        "UPDATE runtime_server_state SET quiescing=1",
        "UPDATE runtime_server_state SET owner_id='different-owner'",
        "UPDATE runtime_server_state SET settings_revision=settings_revision+1",
        "UPDATE runtime_credential_epochs SET epoch=epoch+1",
        "UPDATE runtime_paper_epochs SET paper_epoch=paper_epoch+1",
        "UPDATE runtime_paper_epochs SET source_sha256=zeroblob(32)",
        "UPDATE runtime_figure_resources SET version_token='changed'",
        "UPDATE runtime_figure_resources SET asset_sha256=zeroblob(32)",
        "UPDATE figures SET paper_id=2 WHERE id=7",
        "DELETE FROM figures WHERE id=7",
        "DELETE FROM papers WHERE id=1",
        "UPDATE runtime_operations SET cancel_requested=1",
        "UPDATE runtime_operations SET state='cancelled'",
        "INSERT INTO runtime_tombstones VALUES(1,99,1)",
    ] {
        let f = fixture();
        let a = f.core.accept(input()).unwrap();
        assert!(f.core.dispatch(&a).unwrap());
        let c = rusqlite::Connection::open(&f.paths.db_path).unwrap();
        c.execute_batch(mutation).unwrap();
        let path = settle(&f, outcome(a.request_id));
        assert!(
            matches!(f.core.publish(&path).unwrap(), Publication::Rejected(_)),
            "{mutation}"
        );
        assert_eq!(count(&f, "runtime_usage_events"), 1, "{mutation}");
        assert_eq!(count(&f, "runtime_latest"), 0, "{mutation}");
    }
}

#[test]
fn cancelled_or_deleted_work_records_usage_after_producer_finishes() {
    for delete in [false, true] {
        let f = fixture();
        let a = f.core.accept(input()).unwrap();
        f.core.dispatch(&a).unwrap();
        if delete {
            f.core.tombstone(PaperId(1)).unwrap();
        } else {
            f.core.cancel(a.scope.operation_id).unwrap();
        }
        let path = settle(&f, outcome(a.request_id));
        assert!(matches!(
            f.core.publish(&path).unwrap(),
            Publication::Rejected(_)
        ));
        assert_eq!(count(&f, "runtime_usage_events"), 1);
    }
}

#[test]
fn malformed_incomplete_unknown_and_actual_zero_remain_distinct() {
    for (usage, terminal, text, accepted, state) in [
        (json!({}), true, Some("valid"), false, "unknown"),
        (
            json!({"tokens_in":2}),
            true,
            Some("valid"),
            false,
            "partial",
        ),
        (
            json!({"tokens_in":-1,"tokens_out":2}),
            true,
            Some("valid"),
            false,
            "unknown",
        ),
        (
            json!({"tokens_in":"2","tokens_out":2}),
            true,
            Some("valid"),
            false,
            "unknown",
        ),
        (
            json!({"tokens_in":0,"tokens_out":0,"cost_usd":0}),
            true,
            Some("valid"),
            true,
            "reported",
        ),
        (
            json!({"tokens_in":1,"tokens_out":2}),
            false,
            Some("partial"),
            false,
            "reported",
        ),
        (
            json!({"tokens_in":1,"tokens_out":2}),
            true,
            Some("  "),
            false,
            "reported",
        ),
        (
            json!({"tokens_in":1,"tokens_out":2}),
            true,
            None,
            false,
            "reported",
        ),
    ] {
        let f = fixture();
        let a = f.core.accept(input()).unwrap();
        f.core.dispatch(&a).unwrap();
        let mut o = outcome(a.request_id);
        o.usage = usage;
        o.terminal = terminal;
        o.explanation = text.map(str::to_owned);
        let path = settle(&f, o);
        assert_eq!(
            matches!(f.core.publish(&path).unwrap(), Publication::Published(_)),
            accepted
        );
        let c = rusqlite::Connection::open(&f.paths.db_path).unwrap();
        assert_eq!(
            c.query_row("SELECT usage_state FROM runtime_usage_events", [], |r| {
                r.get::<_, String>(0)
            })
            .unwrap(),
            state
        );
    }
}

#[test]
fn immutable_spool_deduplicates_outcomes_and_preserves_conflicting_evidence() {
    let f = fixture();
    let a = f.core.accept(input()).unwrap();
    f.core.dispatch(&a).unwrap();
    let first = outcome(a.request_id);
    let path = f.core.spool(&first).unwrap();
    assert_eq!(count(&f, "runtime_usage_events"), 0);
    assert_eq!(f.core.spool(&first).unwrap(), path);
    f.core.ingest(&path).unwrap();
    f.core.ingest(&path).unwrap();
    assert_eq!(count(&f, "runtime_usage_events"), 1);
    let mut conflicting = first.clone();
    conflicting.usage = json!({"tokens_in":101,"tokens_out":25});
    conflicting.raw = "second original outcome".into();
    let second = f.core.spool(&conflicting).unwrap();
    assert_ne!(path, second);
    f.core.ingest(&second).unwrap();
    assert!(matches!(
        f.core.publish(&path).unwrap(),
        Publication::Rejected(_)
    ));
    assert_eq!(count(&f, "runtime_usage_events"), 2);
    let c = rusqlite::Connection::open(&f.paths.db_path).unwrap();
    assert_eq!(
        c.query_row(
            "SELECT COUNT(*) FROM runtime_usage_events WHERE usage_state='conflicting'",
            [],
            |r| r.get::<_, i64>(0)
        )
        .unwrap(),
        2
    );
    let raw = std::fs::read_to_string(second).unwrap();
    assert!(raw.contains("second original outcome"));
    assert!(
        std::fs::read_to_string(path)
            .unwrap()
            .contains(&first.raw.replace('"', "\\\""))
    );
}

#[test]
fn db_busy_and_replay_retry_storage_without_creating_a_second_request() {
    let f = fixture();
    let a = f.core.accept(input()).unwrap();
    f.core.dispatch(&a).unwrap();
    let path = f.core.spool(&outcome(a.request_id)).unwrap();
    f.db.blocking_call(|c| {
        c.busy_timeout(std::time::Duration::ZERO)
            .map_err(sasoo_backend::storage::db::db_sql_error)?;
        Ok(())
    })
    .unwrap();
    let c = rusqlite::Connection::open(&f.paths.db_path).unwrap();
    c.execute_batch("BEGIN IMMEDIATE").unwrap();
    assert!(matches!(
        f.core.ingest(&path),
        Err(SasooError::StorageBusy(_))
    ));
    assert!(path.is_file());
    assert_eq!(count(&f, "runtime_usage_events"), 0);
    c.execute_batch("ROLLBACK").unwrap();
    f.core.replay().unwrap();
    f.core.replay().unwrap();
    assert_eq!(count(&f, "runtime_requests"), 1);
    assert_eq!(count(&f, "runtime_usage_events"), 1);
    assert_eq!(count(&f, "runtime_artifact_versions"), 1);
}

#[test]
fn source_and_asset_replacement_invalidate_scopes_and_keep_preexisting_latest() {
    let f = fixture();
    let first = f.core.accept(input()).unwrap();
    f.core.dispatch(&first).unwrap();
    let path = settle(&f, outcome(first.request_id));
    f.core.publish(&path).unwrap();
    let c = rusqlite::Connection::open(&f.paths.db_path).unwrap();
    let latest: String = c
        .query_row("SELECT version_id FROM runtime_latest", [], |r| r.get(0))
        .unwrap();
    let mut changed = input();
    let mut cfg = config(SOURCE);
    cfg.models.insert("figure".into(), "different-model".into());
    changed.config = resolve_config(&cfg).unwrap();
    let second = f.core.accept(changed).unwrap();
    f.core.dispatch(&second).unwrap();
    f.core
        .register_resource(PaperId(1), 7, SOURCE, b"new synthetic asset bytes")
        .unwrap();
    let rejected = settle(&f, outcome(second.request_id));
    assert!(matches!(
        f.core.publish(&rejected).unwrap(),
        Publication::Rejected(_)
    ));
    assert_eq!(
        c.query_row("SELECT version_id FROM runtime_latest", [], |r| r
            .get::<_, String>(0))
            .unwrap(),
        latest
    );
    assert_eq!(count(&f, "runtime_usage_events"), 2);
    let mut changed = input();
    changed.source_bytes = b"new source".to_vec();
    changed.asset_bytes = b"new synthetic asset bytes".to_vec();
    changed.config = resolve_config(&config(&changed.source_bytes)).unwrap();
    f.core
        .register_resource(PaperId(1), 7, &changed.source_bytes, &changed.asset_bytes)
        .unwrap();
    assert!(f.core.accept(changed).is_ok());
}

#[test]
fn cancel_and_delete_commit_before_a_waiting_publication_on_a_second_connection() {
    for mutation in [
        "UPDATE runtime_operations SET cancel_requested=1,state='cancelled'",
        "INSERT INTO runtime_tombstones VALUES(1,90,1); DELETE FROM figures WHERE paper_id=1; DELETE FROM papers WHERE id=1",
    ] {
        let f = fixture();
        let a = f.core.accept(input()).unwrap();
        f.core.dispatch(&a).unwrap();
        let path = settle(&f, outcome(a.request_id));
        let c = rusqlite::Connection::open(&f.paths.db_path).unwrap();
        c.execute_batch("BEGIN IMMEDIATE").unwrap();
        c.execute_batch(mutation).unwrap();
        let barrier = Arc::new(Barrier::new(2));
        let b = barrier.clone();
        let core = f.core.clone();
        let handle = std::thread::spawn(move || {
            b.wait();
            core.publish(&path)
        });
        barrier.wait();
        c.execute_batch("COMMIT").unwrap();
        assert!(matches!(
            handle.join().unwrap().unwrap(),
            Publication::Rejected(_)
        ));
        assert_eq!(count(&f, "runtime_usage_events"), 1);
        assert_eq!(count(&f, "runtime_latest"), 0);
    }
}

#[test]
fn owner_handoff_replays_late_usage_but_never_redispatches_unknown_producers() {
    let f = fixture();
    let a = f.core.accept(input()).unwrap();
    f.core.dispatch(&a).unwrap();
    let path = f.core.spool(&outcome(a.request_id)).unwrap();
    let Fixture {
        _dir,
        paths,
        db,
        core,
    } = f;
    drop(core);
    drop(db);
    let next = loop {
        match open_db(&paths, DbAccess::ServerOwner) {
            Ok(db) => break db,
            Err(SasooError::Conflict(_)) => std::thread::yield_now(),
            Err(e) => panic!("{e}"),
        }
    };
    let core = FigureCore::open(next, paths.app_data_root.join("figure-spool")).unwrap();
    let recovered = core.claim_owner().unwrap();
    assert_eq!(recovered, 1);
    assert!(!core.dispatch(&a).unwrap());
    core.ingest(&path).unwrap();
    assert!(matches!(
        core.publish(&path).unwrap(),
        Publication::Rejected(_)
    ));
    core.replay().unwrap();
    let c = rusqlite::Connection::open(&paths.db_path).unwrap();
    assert_eq!(
        c.query_row("SELECT COUNT(*) FROM runtime_usage_events", [], |r| r
            .get::<_, i64>(0))
            .unwrap(),
        1
    );
    assert_eq!(
        c.query_row("SELECT COUNT(*) FROM runtime_requests", [], |r| r
            .get::<_, i64>(0))
            .unwrap(),
        1
    );
    assert_eq!(
        c.query_row("SELECT state FROM runtime_requests", [], |r| r
            .get::<_, String>(0))
            .unwrap(),
        "recovery_unknown"
    );
    drop(_dir);
}

#[test]
fn concurrent_dispatch_and_publication_grant_authority_exactly_once() {
    let f = fixture();
    let a = f.core.accept(input()).unwrap();
    let peer = FigureCore::open(
        f.db.owner_peer().unwrap(),
        f.paths.app_data_root.join("figure-spool"),
    )
    .unwrap();
    let barrier = Arc::new(Barrier::new(2));
    let tasks = [f.core.clone(), peer.clone()].map(|core| {
        let a = a.clone();
        let b = barrier.clone();
        std::thread::spawn(move || {
            b.wait();
            core.dispatch(&a).unwrap()
        })
    });
    let [one, two] = tasks;
    assert_eq!(
        [one.join().unwrap(), two.join().unwrap()]
            .iter()
            .filter(|v| **v)
            .count(),
        1
    );
    let path = settle(&f, outcome(a.request_id));
    let tasks = [f.core.clone(), peer].map(|core| {
        let path = path.clone();
        let b = barrier.clone();
        std::thread::spawn(move || {
            b.wait();
            core.publish(&path).unwrap()
        })
    });
    let [one, two] = tasks;
    let results = [one.join().unwrap(), two.join().unwrap()];
    assert_eq!(
        results
            .iter()
            .filter(|r| matches!(r, Publication::Published(_)))
            .count(),
        1
    );
    assert_eq!(
        results
            .iter()
            .filter(|r| matches!(r, Publication::AlreadyPublished(_)))
            .count(),
        1
    );
    assert_eq!(count(&f, "runtime_artifact_versions"), 1);
}

#[test]
fn restart_replay_ingests_all_conflicts_before_attempting_publication() {
    let f = fixture();
    let a = f.core.accept(input()).unwrap();
    f.core.dispatch(&a).unwrap();
    let first = outcome(a.request_id);
    let mut second = first.clone();
    second.raw = "conflicting second outcome".into();
    f.core.spool(&first).unwrap();
    f.core.spool(&second).unwrap();
    std::fs::write(
        f.paths
            .app_data_root
            .join("figure-spool/.pending-simulated-crash"),
        "truncated",
    )
    .unwrap();
    let results = f.core.replay().unwrap();
    assert_eq!(results.len(), 2);
    assert!(
        results
            .iter()
            .all(|r| matches!(r, Publication::Rejected(_)))
    );
    assert_eq!(count(&f, "runtime_latest"), 0);
    assert_eq!(count(&f, "runtime_usage_events"), 2);
}

#[test]
fn schema_upgrade_is_additive_revision_checked_and_preserves_legacy_rows() {
    let f = fixture();
    let c = rusqlite::Connection::open(&f.paths.db_path).unwrap();
    assert_eq!(
        c.query_row(
            "SELECT schema_revision FROM runtime_server_state",
            [],
            |r| r.get::<_, i64>(0)
        )
        .unwrap(),
        2
    );
    let before: String = c
        .query_row(
            "SELECT result FROM analysis_results WHERE paper_id=1",
            [],
            |r| r.get(0),
        )
        .unwrap();
    let backup = create_backup(&f.db, &f.paths.app_data_root.join("idempotent.sqlite")).unwrap();
    let report = migrate_figure_runtime(&f.db, &backup).unwrap();
    assert_eq!(report.revision, 2);
    assert_eq!(report.legacy_rows_changed, 0);
    assert_eq!(
        c.query_row(
            "SELECT result FROM analysis_results WHERE paper_id=1",
            [],
            |r| r.get::<_, String>(0)
        )
        .unwrap(),
        before
    );
    c.execute_batch("ALTER TABLE runtime_figure_resources ADD COLUMN unexpected TEXT")
        .unwrap();
    let backup = create_backup(&f.db, &f.paths.app_data_root.join("tampered.sqlite")).unwrap();
    assert!(matches!(
        migrate_figure_runtime(&f.db, &backup),
        Err(SasooError::Unsupported(_))
    ));
}

#[test]
fn a_recovered_identity_does_not_allocate_another_request_automatically() {
    let f = fixture();
    let a = f.core.accept(input()).unwrap();
    f.core.dispatch(&a).unwrap();
    let c = rusqlite::Connection::open(&f.paths.db_path).unwrap();
    c.execute_batch("UPDATE runtime_operations SET state='recovery_unknown'; UPDATE runtime_requests SET state='recovery_unknown'").unwrap();
    assert!(matches!(
        f.core.accept(input()),
        Err(SasooError::OutcomeUnknown(_))
    ));
    assert_eq!(count(&f, "runtime_requests"), 1);
}

#[cfg(unix)]
#[test]
fn immutable_spool_does_not_read_or_overwrite_external_symlink_targets() {
    use std::os::unix::fs::symlink;
    let f = fixture();
    let a = f.core.accept(input()).unwrap();
    f.core.dispatch(&a).unwrap();
    let o = outcome(a.request_id);
    let path = f.core.spool(&o).unwrap();
    let bytes = std::fs::read(&path).unwrap();
    std::fs::remove_file(&path).unwrap();
    let outside = tempfile::tempdir().unwrap();
    let external = outside.path().join("evidence.json");
    std::fs::write(&external, &bytes).unwrap();
    symlink(&external, &path).unwrap();
    assert!(matches!(f.core.spool(&o), Err(SasooError::Forbidden(_))));
    assert!(matches!(
        f.core.ingest(&path),
        Err(SasooError::Forbidden(_))
    ));
    assert_eq!(std::fs::read(external).unwrap(), bytes);
}

#[test]
fn review_incomplete_flag() {
    let usage =
        json!({"tokens_in": 100, "tokens_out": 25, "usage_complete": false, "cost_usd": 0.01});
    assert!(sasoo_backend::analysis::pricing::reported_usage(&usage).is_err());
    let f = fixture();
    let a = f.core.accept(input()).unwrap();
    f.core.dispatch(&a).unwrap();
    let mut o = outcome(a.request_id);
    o.usage = usage.clone();
    let path = settle(&f, o);
    let result = f.core.publish(&path).unwrap();
    assert!(
        !matches!(result, Publication::Published(_)),
        "invalid usage adopted: {usage}; result {result:?}"
    );
}

#[test]
fn review_negative_cached() {
    let usage = json!({"tokens_in": 100, "tokens_out": 25, "tokens_cached": -1, "cost_usd": 0.01});
    assert!(sasoo_backend::analysis::pricing::reported_usage(&usage).is_err());
    let f = fixture();
    let a = f.core.accept(input()).unwrap();
    f.core.dispatch(&a).unwrap();
    let mut o = outcome(a.request_id);
    o.usage = usage.clone();
    let path = settle(&f, o);
    let result = f.core.publish(&path).unwrap();
    assert!(
        !matches!(result, Publication::Published(_)),
        "invalid usage adopted: {usage}; result {result:?}"
    );
}

#[test]
fn review_string_cache_write() {
    let usage =
        json!({"tokens_in": 100, "tokens_out": 25, "tokens_cache_write": "bad", "cost_usd": 0.01});
    assert!(sasoo_backend::analysis::pricing::reported_usage(&usage).is_err());
    let f = fixture();
    let a = f.core.accept(input()).unwrap();
    f.core.dispatch(&a).unwrap();
    let mut o = outcome(a.request_id);
    o.usage = usage.clone();
    let path = settle(&f, o);
    let result = f.core.publish(&path).unwrap();
    assert!(
        !matches!(result, Publication::Published(_)),
        "invalid usage adopted: {usage}; result {result:?}"
    );
}

#[test]
fn review_cached_exceeds_input() {
    let usage = json!({"tokens_in": 100, "tokens_out": 25, "tokens_cached": 101, "cost_usd": 0.01});
    assert!(sasoo_backend::analysis::pricing::reported_usage(&usage).is_err());
    let f = fixture();
    let a = f.core.accept(input()).unwrap();
    f.core.dispatch(&a).unwrap();
    let mut o = outcome(a.request_id);
    o.usage = usage.clone();
    let path = settle(&f, o);
    let result = f.core.publish(&path).unwrap();
    assert!(
        !matches!(result, Publication::Published(_)),
        "invalid usage adopted: {usage}; result {result:?}"
    );
}

#[test]
fn review_resource_replacement_revokes_pending_dispatch() {
    let f = fixture();
    let a = f.core.accept(input()).unwrap();
    f.core
        .register_resource(PaperId(1), 7, SOURCE, b"new asset bytes")
        .unwrap();
    let granted = f.core.dispatch(&a).unwrap();
    assert!(!granted, "old resource scope still grants dispatch");
}

#[test]
fn newer_identity_should_revoke_older_before_first_result() {
    let f = fixture();
    let older = f.core.accept(input()).unwrap();
    f.core.dispatch(&older).unwrap();
    let mut i = input();
    let mut cfg = config(SOURCE);
    cfg.frozen_agent_catalog[0]
        .raw_md
        .push_str("\nRevised synthetic prompt");
    cfg.frozen_agent_catalog[0].sha256 = digest(cfg.frozen_agent_catalog[0].raw_md.as_bytes());
    cfg.raw_agent_hash = Some(cfg.frozen_agent_catalog[0].sha256);
    i.config = resolve_config(&cfg).unwrap();
    let newer = f.core.accept(i).unwrap();
    f.core.dispatch(&newer).unwrap();
    assert_ne!(older.scope.operation_id, newer.scope.operation_id);
    let old = settle(&f, outcome(older.request_id));
    let new = settle(&f, outcome(newer.request_id));
    assert!(
        matches!(f.core.publish(&old).unwrap(), Publication::Rejected(_)),
        "prior identity retained adoption authority after newer config was accepted"
    );
    assert!(matches!(
        f.core.publish(&new).unwrap(),
        Publication::Published(_)
    ));
}

#[test]
fn repeated_active_identity_keeps_one_producer_across_other_identity_acceptance() {
    let f = fixture();
    let first = f.core.accept(input()).unwrap();
    f.core.dispatch(&first).unwrap();
    let mut other = input();
    let mut cfg = config(SOURCE);
    cfg.models
        .insert("figure".into(), "different-synthetic-model".into());
    other.config = resolve_config(&cfg).unwrap();
    let second = f.core.accept(other).unwrap();
    f.core.dispatch(&second).unwrap();
    let conn = rusqlite::Connection::open(&f.paths.db_path).unwrap();
    let token: String = conn
        .query_row(
            "SELECT version_token FROM runtime_figure_resources",
            [],
            |r| r.get(0),
        )
        .unwrap();
    let repeated = f.core.accept(input()).unwrap();
    assert_eq!(
        conn.query_row(
            "SELECT version_token FROM runtime_figure_resources",
            [],
            |r| r.get::<_, String>(0)
        )
        .unwrap(),
        token
    );
    assert_eq!(repeated.request_id, first.request_id);
    assert_eq!(repeated.scope.operation_id, first.scope.operation_id);
    assert!(!f.core.dispatch(&repeated).unwrap());
    assert_eq!(count(&f, "runtime_requests"), 2);
}

#[test]
fn every_current_fence_revokes_a_prepared_dispatch() {
    for mutation in [
        "UPDATE runtime_server_state SET quiescing=1",
        "UPDATE runtime_server_state SET owner_id='other'",
        "UPDATE runtime_server_state SET settings_revision=1",
        "UPDATE runtime_credential_epochs SET epoch=4",
        "UPDATE runtime_paper_epochs SET paper_epoch=paper_epoch+1",
        "UPDATE runtime_paper_epochs SET source_sha256=zeroblob(32)",
        "UPDATE runtime_figure_resources SET asset_sha256=zeroblob(32)",
        "UPDATE runtime_figure_resources SET source_sha256=zeroblob(32)",
        "UPDATE runtime_figure_resources SET version_token='new'",
        "UPDATE figures SET paper_id=2 WHERE id=7",
        "DELETE FROM figures WHERE id=7",
        "DELETE FROM papers WHERE id=1",
        "UPDATE runtime_operations SET cancel_requested=1",
        "INSERT INTO runtime_tombstones VALUES(1,99,1)",
    ] {
        let f = fixture();
        let accepted = f.core.accept(input()).unwrap();
        let c = rusqlite::Connection::open(&f.paths.db_path).unwrap();
        c.execute_batch(mutation).unwrap();
        assert!(
            !matches!(f.core.dispatch(&accepted), Ok(true)),
            "{mutation}"
        );
        assert_eq!(
            c.query_row("SELECT state FROM runtime_requests", [], |r| r
                .get::<_, String>(0))
                .unwrap(),
            "prepared"
        );
    }
}

#[test]
fn canonical_partial_usage_keeps_raw_fields_and_rejects_cache_overflow() {
    for usage in [
        json!({"tokens_in":100,"tokens_out":25,"tokens_cached":90,"tokens_cache_write":11}),
        json!({"tokens_in":100,"tokens_out":25,"tokens_cached":u64::MAX,"tokens_cache_write":1}),
        json!({"tokens_in":100,"tokens_cached":101}),
        json!({"tokens_in":100,"usage_complete":false,"tokens_cached":-1}),
    ] {
        let f = fixture();
        let a = f.core.accept(input()).unwrap();
        f.core.dispatch(&a).unwrap();
        let mut o = outcome(a.request_id);
        o.usage = usage.clone();
        let path = settle(&f, o);
        assert!(!matches!(
            f.core.publish(&path).unwrap(),
            Publication::Published(_)
        ));
        let c = rusqlite::Connection::open(&f.paths.db_path).unwrap();
        let (payload, state): (String, String) = c
            .query_row(
                "SELECT payload_json,usage_state FROM runtime_usage_events",
                [],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .unwrap();
        assert_eq!(
            serde_json::from_str::<serde_json::Value>(&payload).unwrap()["usage"],
            usage
        );
        assert_eq!(state, "unknown");
    }
}

#[test]
fn noncanonical_extra_usage_is_retained_without_claiming_known_counters() {
    let f = fixture();
    let a = f.core.accept(input()).unwrap();
    f.core.dispatch(&a).unwrap();
    let mut o = outcome(a.request_id);
    o.usage = json!({"cached_tokens":20});
    let path = settle(&f, o);
    let c = rusqlite::Connection::open(&f.paths.db_path).unwrap();
    let (state, payload): (String, String) = c
        .query_row(
            "SELECT usage_state,payload_json FROM runtime_usage_events",
            [],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .unwrap();
    assert_eq!(
        serde_json::from_str::<serde_json::Value>(&payload).unwrap()["usage"],
        json!({"cached_tokens":20})
    );
    assert_eq!(state, "unknown");
    assert!(!matches!(
        f.core.publish(&path).unwrap(),
        Publication::Published(_)
    ));
}
