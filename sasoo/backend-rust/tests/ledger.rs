use sasoo_backend::{
    analysis::pricing::KnownUsage,
    error::SasooError,
    providers::types::{
        NewRequestSpec, ProviderInput, ProviderOutcome, RequestOutcome, UsageState,
    },
    runtime::ledger::Ledger,
    storage::{
        db::{Db, DbAccess, open_db},
        migrations::{create_backup, migrate_owned_db},
        paths::RuntimePaths,
    },
    types::{
        AttemptId, CommitScope, ExecutionId, Generation, LocalRequestId, PaperId, ProviderId,
        PublicationScope,
    },
};
use tempfile::TempDir;
use uuid::Uuid;

struct Fixture {
    _dir: TempDir,
    db: Db,
    ledger: Ledger,
    scope: PublicationScope,
}

fn fixture() -> Fixture {
    let dir = TempDir::new().unwrap();
    let root = dir.path().to_path_buf();
    std::fs::write(root.join(".sasoo-rust-isolated-fixture"), "synthetic-only\n").unwrap();
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
    conn.execute_batch(include_str!("fixtures/legacy/schema.sql")).unwrap();
    drop(conn);
    let db = open_db(&paths, DbAccess::ServerOwner).unwrap();
    let backup = create_backup(&db, &root.join("before-runtime.sqlite")).unwrap();
    migrate_owned_db(&db, &backup).unwrap();
    let ledger = Ledger::open(db.clone(), root.join("ledger-spool")).unwrap();
    let scope = PublicationScope::Analysis(CommitScope {
        paper_id: PaperId(1),
        execution_id: ExecutionId(Uuid::new_v4()),
        attempt_id: AttemptId(Uuid::new_v4()),
        generation: Generation(3),
    });
    Fixture { _dir: dir, db, ledger, scope }
}

fn spec() -> NewRequestSpec {
    NewRequestSpec {
        provider: ProviderId::OpenAi,
        model: "gpt-fixture".into(),
        input: ProviderInput { parts: vec![] },
        instructions: Some("system".into()),
        schema: None,
        strict_schema: false,
        effort: Some("low".into()),
        previous_id: None,
        store: false,
        max_output_tokens: None,
        service_tier: None,
        source_identity: None,
    }
}

fn outcome(text: &str, terminal: RequestOutcome, usage: UsageState) -> ProviderOutcome {
    ProviderOutcome {
        remote_id: Some("resp_1".into()),
        terminal,
        content: Some(serde_json::json!({"text": text})),
        usage,
        raw_response: br#"{"id":"resp_1"}"#.to_vec(),
        received_at: 1_000,
    }
}

fn known(tokens_in: u64, tokens_out: u64) -> UsageState {
    UsageState::Known(KnownUsage {
        tokens_in,
        tokens_out,
        tokens_cached: None,
        tokens_cache_write: None,
    })
}

fn row(db: &Db, id: LocalRequestId) -> (String, Option<String>, Option<String>, i64) {
    let request = id.0.to_string();
    db.blocking_call(move |conn| {
        Ok(conn
            .query_row(
                "SELECT state,terminal,remote_id,(SELECT COUNT(*) FROM runtime_usage_events e WHERE e.request_id=r.request_id) FROM runtime_requests r WHERE request_id=?1",
                [request],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
            )
            .unwrap())
    })
    .unwrap()
}

fn set_state(db: &Db, id: LocalRequestId, state: &'static str) {
    let request = id.0.to_string();
    db.blocking_call(move |conn| {
        conn.execute(
            "UPDATE runtime_requests SET state=?1 WHERE request_id=?2",
            [state, request.as_str()],
        )
        .unwrap();
        Ok(())
    })
    .unwrap();
}

#[test]
fn prepare_issues_one_id_and_stores_scope_columns() {
    let f = fixture();
    let a = f.ledger.prepare_request(&f.scope, spec()).unwrap();
    let b = f.ledger.prepare_request(&f.scope, spec()).unwrap();
    assert_ne!(a.spec.id, b.spec.id);
    assert_eq!(a.spec.new.model, "gpt-fixture");
    let request = a.spec.id.0.to_string();
    let (paper, generation, state, spec_json): (i64, i64, String, String) = f
        .db
        .blocking_call(move |conn| {
            Ok(conn
                .query_row(
                    "SELECT paper_id,generation,state,spec_json FROM runtime_requests WHERE request_id=?1",
                    [request],
                    |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
                )
                .unwrap())
        })
        .unwrap();
    assert_eq!((paper, generation, state.as_str()), (1, 3, "prepared"));
    assert!(spec_json.contains("\"gpt-fixture\""));
}

#[test]
fn dispatch_is_granted_once() {
    let f = fixture();
    let id = f.ledger.prepare_request(&f.scope, spec()).unwrap().spec.id;
    f.ledger.mark_dispatched(id).unwrap();
    assert!(matches!(f.ledger.mark_dispatched(id), Err(SasooError::Conflict(_))));
    assert!(matches!(
        f.ledger.mark_dispatched(LocalRequestId(Uuid::new_v4())),
        Err(SasooError::NotFound(_))
    ));
}

#[test]
fn outcome_before_dispatch_is_rejected_without_spool() {
    let f = fixture();
    let id = f.ledger.prepare_request(&f.scope, spec()).unwrap().spec.id;
    let err = f
        .ledger
        .append_outcome(id, &outcome("a", RequestOutcome::Completed, known(1, 2)))
        .unwrap_err();
    assert!(matches!(err, SasooError::Incomplete(_)));
    assert_eq!(std::fs::read_dir(f.ledger.spool_root()).unwrap().count(), 0);
}

#[test]
fn identical_outcome_is_idempotent_and_settles() {
    let f = fixture();
    let id = f.ledger.prepare_request(&f.scope, spec()).unwrap().spec.id;
    f.ledger.mark_dispatched(id).unwrap();
    let o = outcome("a", RequestOutcome::Completed, known(0, 0));
    f.ledger.append_outcome(id, &o).unwrap();
    let mut later = o.clone();
    later.received_at = 9_999;
    f.ledger.append_outcome(id, &later).unwrap();
    assert_eq!(
        row(&f.db, id),
        ("settled".into(), Some("complete".into()), Some("resp_1".into()), 1)
    );
}

#[test]
fn different_second_outcome_is_conflicting() {
    let f = fixture();
    let id = f.ledger.prepare_request(&f.scope, spec()).unwrap().spec.id;
    f.ledger.mark_dispatched(id).unwrap();
    f.ledger
        .append_outcome(id, &outcome("a", RequestOutcome::Completed, known(1, 2)))
        .unwrap();
    f.ledger
        .append_outcome(id, &outcome("b", RequestOutcome::Completed, known(1, 2)))
        .unwrap();
    assert_eq!(
        row(&f.db, id),
        ("outcome_unknown".into(), Some("conflicting".into()), Some("resp_1".into()), 2)
    );
}

#[test]
fn unknown_outcome_and_incomplete_map_to_shared_vocabulary() {
    let f = fixture();
    let unknown = f.ledger.prepare_request(&f.scope, spec()).unwrap().spec.id;
    f.ledger.mark_dispatched(unknown).unwrap();
    f.ledger
        .append_outcome(
            unknown,
            &outcome("", RequestOutcome::OutcomeUnknown, UsageState::Unknown { reason: "timeout".into() }),
        )
        .unwrap();
    assert_eq!(row(&f.db, unknown).0, "outcome_unknown");
    assert_eq!(row(&f.db, unknown).1.as_deref(), Some("incomplete"));

    let failed = f.ledger.prepare_request(&f.scope, spec()).unwrap().spec.id;
    f.ledger.mark_dispatched(failed).unwrap();
    f.ledger
        .append_outcome(
            failed,
            &outcome("", RequestOutcome::Incomplete, UsageState::Unknown { reason: "missing_usage".into() }),
        )
        .unwrap();
    assert_eq!(row(&f.db, failed).0, "settled");
    assert_eq!(row(&f.db, failed).1.as_deref(), Some("incomplete"));

    let id = f.ledger.prepare_request(&f.scope, spec()).unwrap().spec.id;
    assert!(matches!(
        f.ledger.append_outcome(id, &outcome("", RequestOutcome::InFlight, known(1, 1))),
        Err(SasooError::InvalidInput(_))
    ));
}

#[test]
fn recovery_unknown_is_not_overwritten() {
    let f = fixture();
    let id = f.ledger.prepare_request(&f.scope, spec()).unwrap().spec.id;
    f.ledger.mark_dispatched(id).unwrap();
    set_state(&f.db, id, "recovery_unknown");
    f.ledger
        .append_outcome(id, &outcome("a", RequestOutcome::Completed, known(1, 2)))
        .unwrap();
    assert_eq!(row(&f.db, id).0, "recovery_unknown");
    assert_eq!(row(&f.db, id).3, 1);
}

#[test]
fn replay_records_a_spool_written_before_a_crash() {
    let f = fixture();
    let id = f.ledger.prepare_request(&f.scope, spec()).unwrap().spec.id;
    f.ledger.mark_dispatched(id).unwrap();
    f.ledger
        .append_outcome(id, &outcome("a", RequestOutcome::Completed, known(5, 6)))
        .unwrap();
    let file = std::fs::read_dir(f.ledger.spool_root())
        .unwrap()
        .map(|e| e.unwrap().path())
        .find(|p| p.extension().is_some_and(|e| e == "json"))
        .unwrap();
    // Simulate a crash after the spool fsync and before the DB transaction.
    let request = id.0.to_string();
    f.db.blocking_call(move |conn| {
        conn.execute("DELETE FROM runtime_usage_events WHERE request_id=?1", [&request])
            .unwrap();
        conn.execute(
            "UPDATE runtime_requests SET state='dispatched',terminal=NULL WHERE request_id=?1",
            [&request],
        )
        .unwrap();
        Ok(())
    })
    .unwrap();
    let receipt = f.ledger.replay_spool(&file).unwrap();
    assert!(receipt.inserted);
    assert_eq!(receipt.request_id, id);
    assert!(!f.ledger.replay_spool(&file).unwrap().inserted);
    assert_eq!(row(&f.db, id).0, "settled");

    let renamed = f.ledger.spool_root().join(format!("{}-{}.json", id.0, "0".repeat(64)));
    std::fs::copy(&file, &renamed).unwrap();
    assert!(matches!(f.ledger.replay_spool(&renamed), Err(SasooError::Incomplete(_))));
    let outside = TempDir::new().unwrap();
    let copy = outside.path().join(file.file_name().unwrap());
    std::fs::copy(&file, &copy).unwrap();
    assert!(matches!(f.ledger.replay_spool(&copy), Err(SasooError::Forbidden(_))));
}

#[test]
fn spool_never_contains_request_secrets() {
    let f = fixture();
    let id = f.ledger.prepare_request(&f.scope, spec()).unwrap().spec.id;
    f.ledger.mark_dispatched(id).unwrap();
    f.ledger
        .append_outcome(id, &outcome("a", RequestOutcome::Completed, known(1, 2)))
        .unwrap();
    for entry in std::fs::read_dir(f.ledger.spool_root()).unwrap() {
        let text = std::fs::read_to_string(entry.unwrap().path()).unwrap();
        assert!(!text.to_ascii_lowercase().contains("authorization"));
        assert!(!text.contains("x-goog-api-key"));
    }
}
