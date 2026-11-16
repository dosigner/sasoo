use sasoo_backend::{
    storage::{
        db::{Db, DbAccess, open_db},
        discussion::{
            Answer, active_context, append_answer, append_reset, append_user, list_messages,
        },
        paths::RuntimePaths,
    },
    types::PaperId,
};
use serde_json::json;
use tempfile::TempDir;

fn fixture() -> (TempDir, RuntimePaths, Db) {
    let dir = TempDir::new().unwrap();
    let root = dir.path().to_path_buf();
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
    conn.execute_batch("ALTER TABLE discussion_messages ADD COLUMN context_json TEXT; INSERT INTO papers(id,title,folder_name) VALUES(1,'paper','fixture');").unwrap();
    let db = open_db(&paths, DbAccess::ServerOwner).unwrap();
    (dir, paths, db)
}
fn answer(status: &str, id: i64) -> Answer {
    Answer {
        content: format!("answer {id}"),
        status: status.into(),
        model_used: Some("fixture".into()),
        tokens_in: Some(10),
        tokens_out: Some(2),
        cost_usd: Some(0.0),
        context: Some(
            json!({"requested_at":"2026-11-16T00:00:00Z","sources":[{"key":"citation","result_id":id}]}),
        ),
    }
}
#[test]
fn history_survives_reanalysis_and_each_answer_keeps_its_snapshot() {
    let (_dir, _paths, db) = fixture();
    let id = PaperId(1);
    append_user(&db, id, "first".into()).unwrap();
    append_answer(&db, id, answer("complete", 17)).unwrap();
    append_user(&db, id, "next".into()).unwrap();
    append_answer(&db, id, answer("complete", 18)).unwrap();
    let messages = list_messages(&db, id).unwrap();
    assert_eq!(messages.len(), 4);
    assert_eq!(
        messages[1].context.as_ref().unwrap()["sources"][0]["result_id"],
        17
    );
    assert_eq!(
        messages[3].context.as_ref().unwrap()["sources"][0]["result_id"],
        18
    );
    assert_eq!(active_context(&db, id).unwrap().len(), 4);
}
#[test]
fn interrupted_answers_are_saved_but_not_in_followup_context_and_reset_is_explicit() {
    let (_dir, _paths, db) = fixture();
    let id = PaperId(1);
    append_user(&db, id, "first".into()).unwrap();
    append_answer(&db, id, answer("interrupted", 17)).unwrap();
    append_user(&db, id, "next".into()).unwrap();
    assert_eq!(list_messages(&db, id).unwrap().len(), 3);
    assert_eq!(
        active_context(&db, id)
            .unwrap()
            .iter()
            .map(|m| m.content.as_str())
            .collect::<Vec<_>>(),
        ["first", "next"]
    );
    append_reset(&db, id, "manual".into()).unwrap();
    assert!(active_context(&db, id).unwrap().is_empty());
}
#[test]
fn read_only_cannot_write_and_invalid_usage_is_rejected() {
    let (_dir, paths, db) = fixture();
    let read = open_db(&paths, DbAccess::ReadOnly).unwrap();
    assert!(append_user(&read, PaperId(1), "no".into()).is_err());
    let mut invalid = answer("complete", 1);
    invalid.cost_usd = Some(f64::NAN);
    assert!(append_answer(&db, PaperId(1), invalid).is_err());
    assert!(list_messages(&db, PaperId(1)).unwrap().is_empty());
}

#[test]
fn legacy_database_without_context_column_remains_readable_and_unmodified() {
    let dir = TempDir::new().unwrap();
    let root = dir.path().to_path_buf();
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
    conn.execute_batch("INSERT INTO papers(id,title,folder_name) VALUES(1,'old','old'); INSERT INTO discussion_messages(paper_id,kind,content) VALUES(1,'user','legacy question')").unwrap();
    let db = open_db(&paths, DbAccess::ServerOwner).unwrap();
    let messages = list_messages(&db, PaperId(1)).unwrap();
    assert_eq!(messages[0].content, "legacy question");
    assert!(messages[0].context.is_none());
    assert!(append_user(&db, PaperId(1), "new question".into()).is_err());
    assert!(append_answer(&db, PaperId(1), answer("complete", 1)).is_err());
    assert_eq!(list_messages(&db, PaperId(1)).unwrap().len(), 1);
}

#[test]
fn source_metadata_survives_a_new_read_connection() {
    let (_dir, paths, db) = fixture();
    append_user(&db, PaperId(1), "question".into()).unwrap();
    append_answer(&db, PaperId(1), answer("complete", 301)).unwrap();
    let reopened = open_db(&paths, DbAccess::ReadOnly).unwrap();
    let messages = list_messages(&reopened, PaperId(1)).unwrap();
    assert_eq!(
        messages[1].context.as_ref().unwrap()["sources"][0]["result_id"],
        301
    );
    assert_eq!(messages[1].content, "answer 301");
}

#[test]
fn guarded_legacy_context_migration_preserves_rows_and_requires_fresh_backup() {
    use sasoo_backend::storage::migrations::{create_backup, migrate_discussion_context};
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
    conn.execute_batch("INSERT INTO papers(id,title,folder_name) VALUES(1,'old','old'); INSERT INTO discussion_messages(paper_id,kind,content) VALUES(1,'user','legacy')").unwrap();
    let db = open_db(&paths, DbAccess::ServerOwner).unwrap();
    let stale = create_backup(&db, &root.join("stale.sqlite")).unwrap();
    conn.execute(
        "UPDATE discussion_messages SET content='changed' WHERE paper_id=1",
        [],
    )
    .unwrap();
    assert!(migrate_discussion_context(&db, &stale).is_err());
    let backup = create_backup(&db, &root.join("current.sqlite")).unwrap();
    assert!(migrate_discussion_context(&db, &backup).unwrap());
    let rows = list_messages(&db, PaperId(1)).unwrap();
    assert_eq!(rows[0].content, "changed");
    assert!(rows[0].context.is_none());
    append_answer(&db, PaperId(1), answer("complete", 7)).unwrap();
    let fresh = create_backup(&db, &root.join("fresh.sqlite")).unwrap();
    assert!(!migrate_discussion_context(&db, &fresh).unwrap());
}

#[test]
fn begin_turn_atomically_records_question_and_loads_only_prior_active_history() {
    use sasoo_backend::storage::discussion::begin_turn;
    let (_dir, _paths, db) = fixture();
    append_user(&db, PaperId(1), "old question".into()).unwrap();
    append_answer(&db, PaperId(1), answer("complete", 17)).unwrap();
    let (history, id) = begin_turn(&db, PaperId(1), "new question".into()).unwrap();
    assert_eq!(history.len(), 2);
    assert_eq!(
        history[1].context.as_ref().unwrap()["sources"][0]["result_id"],
        17
    );
    assert_eq!(list_messages(&db, PaperId(1)).unwrap()[2].id, id);
    assert!(begin_turn(&db, PaperId(999), "wrong paper".into()).is_err());
    assert_eq!(list_messages(&db, PaperId(1)).unwrap().len(), 3);
}

#[test]
fn transcript_preserves_previous_analysis_ids_without_interrupted_answer() {
    use sasoo_backend::analysis::chat_context::transcript;
    let (_dir, _paths, db) = fixture();
    append_user(&db, PaperId(1), "first".into()).unwrap();
    append_answer(&db, PaperId(1), answer("complete", 17)).unwrap();
    append_user(&db, PaperId(1), "second".into()).unwrap();
    append_answer(&db, PaperId(1), answer("interrupted", 18)).unwrap();
    let output = transcript(&active_context(&db, PaperId(1)).unwrap(), "follow-up").unwrap();
    assert_eq!(
        output,
        "사용자: first\n사수: answer 17\n[이 답변 당시 분석 결과 ID: [[\"citation\", 17]]]\n사용자: second\n사용자: follow-up"
    );
    assert!(!output.contains("answer 18"));
}

#[test]
fn assembled_context_and_saved_history_remain_consistent_across_phase_changes() {
    use sasoo_backend::analysis::{
        chat_context::{Phase, PhaseState, assemble_context, transcript},
        chat_retrieval::Document,
    };
    use sasoo_backend::storage::discussion::begin_turn;
    let (_dir, _paths, db) = fixture();
    let doc = Document {
        parser_version: "v1".into(),
        full_text: "--- Page 1 ---\n\nTable 1 Shows clear results from three benchmark models."
            .into(),
    };
    let pdf = vec!["Table 1 Shows clear results from three benchmark models.".into()];
    let first = assemble_context(
        &doc,
        "Table 1 citation",
        Some(&pdf),
        None,
        &[Phase {
            name: "citation".into(),
            result_id: Some(17),
            state: PhaseState::Completed,
            text: "old analysis".into(),
        }],
    )
    .unwrap();
    let (history, _) = begin_turn(&db, PaperId(1), "Table 1".into()).unwrap();
    assert!(history.is_empty());
    let mut result = answer("complete", 17);
    result.context = Some(json!({"requested_at":"2026-11-16T00:00:00Z","sources":first.sources}));
    append_answer(&db, PaperId(1), result).unwrap();
    let second = assemble_context(
        &doc,
        "Table 1 citation",
        Some(&pdf),
        None,
        &[
            Phase {
                name: "citation".into(),
                result_id: Some(18),
                state: PhaseState::Completed,
                text: "new analysis".into(),
            },
            Phase {
                name: "recipe".into(),
                result_id: Some(19),
                state: PhaseState::Partial,
                text: "unfinished phase".into(),
            },
        ],
    )
    .unwrap();
    let (history, _) = begin_turn(&db, PaperId(1), "Table 1 follow-up".into()).unwrap();
    let input = transcript(&history, "Table 1 follow-up").unwrap();
    assert!(input.contains("[[\"citation\", 17]]"));
    assert!(!second.model_material.contains("unfinished phase"));
    let mut result = answer("interrupted", 18);
    result.context = Some(json!({"requested_at":"2026-11-16T00:00:01Z","sources":second.sources}));
    append_answer(&db, PaperId(1), result).unwrap();
    let messages = list_messages(&db, PaperId(1)).unwrap();
    assert_eq!(
        messages[1].context.as_ref().unwrap()["sources"]
            .as_array()
            .unwrap()
            .iter()
            .find(|s| s["key"] == "citation")
            .unwrap()["result_id"],
        17
    );
    assert_eq!(
        messages[3].context.as_ref().unwrap()["sources"]
            .as_array()
            .unwrap()
            .iter()
            .find(|s| s["key"] == "citation")
            .unwrap()["result_id"],
        18
    );
    assert_eq!(active_context(&db, PaperId(1)).unwrap().len(), 3);
}
