use sasoo_backend::{
    analysis::config::{ConfigInput, FrozenAgent, PdfIdentity, resolve_config},
    error::SasooError,
    runtime::accept::{AcceptInput, PdfPreparationReceipt, accept_run},
    storage::{
        db::{Db, DbAccess, open_db},
        migrations::{create_backup, migrate_owned_db},
        paths::RuntimePaths,
    },
    types::{KeyEpoch, PaperEpoch, PaperId, ProviderId, SecretRef},
};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::sync::Arc;
use tempfile::TempDir;
use tokio::sync::Barrier;

fn config_input() -> ConfigInput {
    let agent = "# photon\n합성 원문".to_string();
    let hash = Sha256::digest(agent.as_bytes()).into();
    ConfigInput {
        schema_version: 1,
        provider_roles: BTreeMap::from([
            ("screening".into(), ProviderId::OpenAi),
            ("image".into(), ProviderId::OpenAi),
        ]),
        models: BTreeMap::from([
            ("screening".into(), "frozen-text-model".into()),
            ("image".into(), "frozen-image-model".into()),
        ]),
        efforts: BTreeMap::from([
            ("screening".into(), Some("high".into())),
            ("image".into(), None),
        ]),
        prompt_schema_hashes: BTreeMap::from([
            ("screening-prompt".into(), [2; 32]),
            ("screening-schema".into(), [3; 32]),
        ]),
        raw_agent_hash: None,
        frozen_agent_catalog: vec![FrozenAgent {
            name: "photon".into(),
            enabled: true,
            keywords: vec!["광학".into()],
            raw_md: agent,
            sha256: hash,
        }],
        agent_selection_policy_version: "legacy-policy-v1".into(),
        profile: json!({"role":"연구자","preferences":{"b":2,"a":1}}),
        focus: json!({"question":"검증"}),
        pdf_identity: PdfIdentity {
            source_sha256: [7; 32],
            engine: "legacy-explicit".into(),
            engine_revision: "fixture-v1".into(),
            options_hash: [8; 32],
        },
        limits: BTreeMap::from([("max_output_tokens".into(), 8192)]),
        cache_version: "legacy-v1".into(),
        secret_refs: vec![SecretRef {
            provider: ProviderId::OpenAi,
            epoch: KeyEpoch(4),
        }],
    }
}

fn fixture() -> (TempDir, RuntimePaths, Db) {
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
        default_library_root: root.clone(),
        library_root: root.clone(),
        library_search_roots: vec![root.clone()],
        owner_lock_path: root.join("owner.lock"),
    };
    let conn = rusqlite::Connection::open(&paths.db_path).unwrap();
    conn.execute_batch(include_str!("fixtures/legacy/schema.sql"))
        .unwrap();
    conn.execute(
        "INSERT INTO papers(id,title,folder_name,status) VALUES(1,'합성 논문','one','completed')",
        [],
    )
    .unwrap();
    conn.execute("INSERT INTO analysis_results(paper_id,phase,result,cost_usd) VALUES(1,'recipe','{\"paid\":true}',1.25)",[]).unwrap();
    let db = open_db(&paths, DbAccess::ServerOwner).unwrap();
    let backup = create_backup(&db, &root.join("before.sqlite")).unwrap();
    migrate_owned_db(&db, &backup).unwrap();
    conn.execute(
        "INSERT INTO runtime_credential_epochs(provider,epoch) VALUES('openai',4)",
        [],
    )
    .unwrap();
    conn.execute(
        "INSERT INTO settings(key,value) VALUES('openai_api_key','enc:v1:synthetic')",
        [],
    )
    .unwrap();
    conn.execute(
        "INSERT INTO runtime_paper_epochs(paper_id,paper_epoch,source_sha256) VALUES(1,3,?1)",
        [vec![7u8; 32]],
    )
    .unwrap();
    (dir, paths, db)
}

fn accept_input() -> AcceptInput {
    AcceptInput {
        paper_id: PaperId(1),
        pdf_receipt: PdfPreparationReceipt {
            paper_id: PaperId(1),
            paper_epoch: PaperEpoch(3),
            source_sha256: [7; 32],
            extraction_version: "prepared-fixture-v1".into(),
            ready: true,
        },
        config: resolve_config(&config_input()).unwrap(),
        settings_revision: 0,
    }
}

#[test]
fn config_is_canonical_and_freezes_every_input_without_secret_plaintext() {
    let mut input = config_input();
    let first = resolve_config(&input).unwrap();
    input.profile = json!({"preferences":{"a":1,"b":2},"role":"연구자"});
    let reordered = resolve_config(&input).unwrap();
    assert_eq!(first.canonical_bytes(), reordered.canonical_bytes());
    let expected_hash: [u8; 32] = Sha256::digest(first.canonical_bytes()).into();
    assert_eq!(first.sha256(), expected_hash);
    input.models.insert("screening".into(), "new-model".into());
    input.frozen_agent_catalog[0].raw_md.push_str(" changed");
    assert!(
        String::from_utf8(first.canonical_bytes().to_vec())
            .unwrap()
            .contains("frozen-text-model")
    );
    assert!(
        !String::from_utf8(first.canonical_bytes().to_vec())
            .unwrap()
            .contains("new-model")
    );
    assert_eq!(first.snapshot().secret_refs[0].epoch, KeyEpoch(4));
    assert!(resolve_config(&input).is_err());
}

#[test]
fn missing_config_or_structured_secret_values_are_rejected() {
    let mut missing = config_input();
    missing.models.remove("image");
    assert!(matches!(
        resolve_config(&missing),
        Err(SasooError::InvalidInput(_))
    ));
    let mut secret = config_input();
    secret.profile = json!({"provider":{"api_key":"synthetic-secret"}});
    assert!(matches!(
        resolve_config(&secret),
        Err(SasooError::InvalidInput(_))
    ));
    let mut camel_secret = config_input();
    camel_secret.focus = json!({"provider":{"apiKey":"synthetic-secret"}});
    assert!(matches!(
        resolve_config(&camel_secret),
        Err(SasooError::InvalidInput(_))
    ));
    let mut ref_missing = config_input();
    ref_missing.secret_refs.clear();
    assert!(resolve_config(&ref_missing).is_err());
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn two_connections_accept_once_and_preserve_paid_results() {
    let (_dir, paths, db) = fixture();
    let peer = db.owner_peer().unwrap();
    let barrier = Arc::new(Barrier::new(2));
    let tasks = [db.clone(), peer].map(|connection| {
        let barrier = barrier.clone();
        tokio::spawn(async move {
            barrier.wait().await;
            accept_run(&connection, accept_input()).await
        })
    });
    let [first, second] = tasks;
    let outcomes = [first.await.unwrap(), second.await.unwrap()];
    assert_eq!(outcomes.iter().filter(|result| result.is_ok()).count(), 1);
    assert_eq!(
        outcomes
            .iter()
            .filter(|result| matches!(result, Err(SasooError::Conflict(_))))
            .count(),
        1
    );
    let conn = rusqlite::Connection::open(&paths.db_path).unwrap();
    assert_eq!(
        conn.query_row("SELECT COUNT(*) FROM runtime_executions", [], |r| r
            .get::<_, i64>(0))
            .unwrap(),
        1
    );
    assert_eq!(
        conn.query_row(
            "SELECT COUNT(*) FROM analysis_runs WHERE paper_id=1 AND status='queued'",
            [],
            |r| r.get::<_, i64>(0)
        )
        .unwrap(),
        1
    );
    assert_eq!(
        conn.query_row("SELECT status FROM papers WHERE id=1", [], |r| r
            .get::<_, String>(0))
            .unwrap(),
        "analyzing"
    );
    assert_eq!(
        conn.query_row(
            "SELECT cost_usd FROM analysis_results WHERE paper_id=1",
            [],
            |r| r.get::<_, f64>(0)
        )
        .unwrap(),
        1.25
    );
    let (bytes, hash): (Vec<u8>, Vec<u8>) = conn
        .query_row(
            "SELECT config_bytes,config_hash FROM runtime_executions",
            [],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .unwrap();
    assert_eq!(hash, Sha256::digest(&bytes).to_vec());
    conn.execute("UPDATE runtime_server_state SET settings_revision=99", [])
        .unwrap();
    assert_eq!(
        conn.query_row("SELECT config_bytes FROM runtime_executions", [], |r| r
            .get::<_, Vec<u8>>(0))
            .unwrap(),
        bytes
    );
    assert!(
        String::from_utf8(bytes)
            .unwrap()
            .contains("frozen-image-model")
    );
}

#[tokio::test]
async fn preparation_races_reject_deleted_changed_or_unready_input_without_enqueue() {
    for mutation in [
        "DELETE FROM papers WHERE id=1",
        "UPDATE runtime_server_state SET settings_revision=1",
        "UPDATE runtime_paper_epochs SET paper_epoch=4",
        "UPDATE runtime_paper_epochs SET source_sha256=zeroblob(32)",
        "UPDATE runtime_server_state SET quiescing=1",
        "INSERT INTO runtime_tombstones(paper_id,paper_epoch,deleted_at_ms) VALUES(1,4,0)",
    ] {
        let (_dir, paths, db) = fixture();
        let conn = rusqlite::Connection::open(&paths.db_path).unwrap();
        conn.execute(mutation, []).unwrap();
        assert!(accept_run(&db, accept_input()).await.is_err(), "{mutation}");
        assert_eq!(
            conn.query_row("SELECT COUNT(*) FROM runtime_executions", [], |r| r
                .get::<_, i64>(0))
                .unwrap(),
            0
        );
        assert_eq!(
            conn.query_row("SELECT COUNT(*) FROM analysis_runs", [], |r| r
                .get::<_, i64>(0))
                .unwrap(),
            0
        );
    }
    let (_dir, paths, db) = fixture();
    let mut input = accept_input();
    input.pdf_receipt.ready = false;
    assert!(matches!(
        accept_run(&db, input).await,
        Err(SasooError::Incomplete(_))
    ));
    assert_eq!(
        rusqlite::Connection::open(paths.db_path)
            .unwrap()
            .query_row("SELECT status FROM papers WHERE id=1", [], |r| r
                .get::<_, String>(0))
            .unwrap(),
        "completed"
    );
}

#[tokio::test]
async fn worker_cannot_enqueue_and_stale_secret_epoch_is_rejected() {
    let (_dir, paths, db) = fixture();
    let worker = open_db(&paths, DbAccess::Worker).unwrap();
    assert!(matches!(
        accept_run(&worker, accept_input()).await,
        Err(SasooError::Forbidden(_))
    ));
    let conn = rusqlite::Connection::open(paths.db_path).unwrap();
    // Credential epoch is a reference, never the secret bytes.
    conn.execute(
        "UPDATE runtime_credential_epochs SET epoch=5 WHERE provider='openai'",
        [],
    )
    .unwrap();
    assert!(matches!(
        accept_run(&db, accept_input()).await,
        Err(SasooError::CredentialUnavailable(_))
    ));
    assert_eq!(
        conn.query_row("SELECT COUNT(*) FROM runtime_executions", [], |r| r
            .get::<_, i64>(0))
            .unwrap(),
        0
    );
}

#[tokio::test]
async fn transaction_failure_rolls_back_execution_queue_and_epoch_before_safe_storage_retry() {
    let (_dir, paths, db) = fixture();
    let conn = rusqlite::Connection::open(paths.db_path).unwrap();
    conn.execute_batch("CREATE TRIGGER deny_status BEFORE UPDATE ON papers BEGIN SELECT RAISE(ABORT,'injected storage failure'); END;").unwrap();
    assert!(accept_run(&db, accept_input()).await.is_err());
    assert_eq!(
        conn.query_row("SELECT COUNT(*) FROM runtime_executions", [], |r| r
            .get::<_, i64>(0))
            .unwrap(),
        0
    );
    assert_eq!(
        conn.query_row("SELECT COUNT(*) FROM analysis_runs", [], |r| r
            .get::<_, i64>(0))
            .unwrap(),
        0
    );
    assert_eq!(
        conn.query_row(
            "SELECT paper_epoch FROM runtime_paper_epochs WHERE paper_id=1",
            [],
            |r| r.get::<_, i64>(0)
        )
        .unwrap(),
        3
    );
    assert_eq!(
        conn.query_row("SELECT status FROM papers WHERE id=1", [], |r| r
            .get::<_, String>(0))
            .unwrap(),
        "completed"
    );
    assert_eq!(
        conn.query_row(
            "SELECT cost_usd FROM analysis_results WHERE paper_id=1",
            [],
            |r| r.get::<_, f64>(0)
        )
        .unwrap(),
        1.25
    );
    conn.execute_batch("DROP TRIGGER deny_status;").unwrap();
    accept_run(&db, accept_input()).await.unwrap();
    assert_eq!(
        conn.query_row("SELECT COUNT(*) FROM runtime_executions", [], |r| r
            .get::<_, i64>(0))
            .unwrap(),
        1
    );
}
