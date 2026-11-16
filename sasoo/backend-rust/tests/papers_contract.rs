use rusqlite::Connection;
use sasoo_backend::{
    error::SasooError,
    http::papers::{PaperObservation, PaperPatch, PaperQuery, PaperService},
    storage::{
        db::{DbAccess, open_db},
        paths::RuntimePaths,
    },
    types::PaperId,
};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use tempfile::TempDir;

fn fixture() -> (TempDir, PaperService) {
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
    let conn = Connection::open(&paths.db_path).unwrap();
    conn.execute_batch(include_str!("fixtures/legacy/schema.sql"))
        .unwrap();
    conn.execute_batch("INSERT INTO papers(id,title,authors,folder_name,notes,tags,status,created_at) VALUES(1,'Alpha','author needle','one',NULL,NULL,'completed','2026-01-01'),(2,'Beta',NULL,'two','note needle',NULL,'pending','2026-02-01'),(3,'Gamma',NULL,'three',NULL,'tag needle','completed','2026-03-01'),(4,'Title needle',NULL,'four',NULL,NULL,'error','2026-04-01');").unwrap();
    let db = open_db(&paths, DbAccess::ServerOwner).unwrap();
    let observations = (1..=4)
        .map(|id| {
            (
                id,
                PaperObservation {
                    resolved_title: None,
                    text_ready: true,
                    visual_ready: false,
                    visual_state: "partial".into(),
                    visual_error: None,
                    openalex_field: None,
                },
            )
        })
        .collect();
    let domain_agents = BTreeMap::from([
        ("optics".into(), "photon".into()),
        ("ai_ml".into(), "neural".into()),
        ("general".into(), "photon".into()),
    ]);
    (
        dir,
        PaperService {
            db,
            observations,
            domain_agents,
            filesystem_root: None,
        },
    )
}

#[test]
fn search_uses_all_four_legacy_columns_and_counts_the_filtered_population() {
    let (_dir, service) = fixture();
    let result = service
        .list_papers(PaperQuery {
            search: Some("needle".into()),
            page_size: 2,
            ..Default::default()
        })
        .unwrap();
    assert_eq!(result.total, 4);
    assert_eq!(result.completed_count, Some(2));
    assert_eq!(
        result
            .papers
            .iter()
            .map(|p| p.fields["id"].as_i64().unwrap())
            .collect::<Vec<_>>(),
        vec![4, 3]
    );
    let page2 = service
        .list_papers(PaperQuery {
            search: Some("needle".into()),
            page: 2,
            page_size: 2,
            ..Default::default()
        })
        .unwrap();
    assert_eq!(page2.papers[0].fields["id"], 2);
    assert_eq!(page2.papers[1].fields["id"], 1);
    assert!(page2.papers[0].fields["authors"].is_null());
    assert_eq!(page2.papers[0].fields["visual_state"], "partial");
    assert_eq!(page2.papers[0].fields["artifacts_ready"], false);
}

#[test]
fn sort_allowlist_rejects_sql_injection_and_query_bounds_match_legacy() {
    let (_dir, service) = fixture();
    let result = service
        .list_papers(PaperQuery {
            sort_by: "title; DROP TABLE papers".into(),
            sort_order: "sideways".into(),
            ..Default::default()
        })
        .unwrap();
    assert_eq!(result.papers[0].fields["id"], 4);
    for query in [
        PaperQuery {
            page: 0,
            ..Default::default()
        },
        PaperQuery {
            page_size: 101,
            ..Default::default()
        },
    ] {
        assert!(matches!(
            service.list_papers(query),
            Err(SasooError::InvalidInput(_))
        ));
    }
    let ascending = service
        .list_papers(PaperQuery {
            sort_by: "title".into(),
            sort_order: "ASC".into(),
            ..Default::default()
        })
        .unwrap();
    assert_eq!(ascending.papers[0].fields["title"], "Alpha");
}

#[test]
fn null_patch_is_ignored_empty_strings_clear_and_focus_keeps_python_json_spacing() {
    let (_dir, service) = fixture();
    let patch:PaperPatch=serde_json::from_value(json!({"title":null,"notes":"","analysis_focus":{"chips":["재현"],"note":"한글"},"unknown":"ignored"})).unwrap();
    let updated = service.patch_paper(PaperId(1), patch).unwrap();
    assert_eq!(updated.fields["title"], "Alpha");
    assert_eq!(updated.fields["notes"], "");
    assert_eq!(
        updated.fields["analysis_focus"],
        "{\"chips\": [\"재현\"], \"note\": \"한글\"}"
    );
    let no_fields: PaperPatch = serde_json::from_value(json!({"title":null})).unwrap();
    assert!(
        matches!(service.patch_paper(PaperId(1),no_fields),Err(SasooError::InvalidInput(message)) if message=="No fields to update.")
    );
}

#[test]
fn changed_domain_uses_frozen_catalog_unless_agent_was_explicitly_set() {
    let (_dir, service) = fixture();
    let updated = service
        .patch_paper(
            PaperId(1),
            serde_json::from_value(json!({"domain":"ai_ml"})).unwrap(),
        )
        .unwrap();
    assert_eq!(updated.fields["agent_used"], "neural");
    let updated = service
        .patch_paper(
            PaperId(1),
            serde_json::from_value(json!({"domain":"optics","agent_used":"circuit"})).unwrap(),
        )
        .unwrap();
    assert_eq!(updated.fields["agent_used"], "circuit");
    let bad: PaperPatch = serde_json::from_value(json!({"domain":"invented"})).unwrap();
    assert!(matches!(
        service.patch_paper(PaperId(1), bad),
        Err(SasooError::InvalidInput(_))
    ));
}

#[test]
fn active_queue_prevents_idle_reads_and_patch_without_mutating_original() {
    let (_dir, service) = fixture();
    service
        .db
        .blocking_call(|conn| {
            conn.execute(
                "INSERT INTO analysis_runs(paper_id,status) VALUES(1,'queued')",
                [],
            )
            .map_err(sasoo_backend::storage::db::db_sql_error)?;
            Ok(())
        })
        .unwrap();
    assert!(matches!(
        service.get_paper(PaperId(1)),
        Err(SasooError::Unsupported(_))
    ));
    assert!(matches!(
        service.patch_paper(
            PaperId(1),
            serde_json::from_value(json!({"notes":"must not persist"})).unwrap()
        ),
        Err(SasooError::Unsupported(_))
    ));
    let notes: Value = service
        .db
        .blocking_call(|conn| {
            Ok(conn
                .query_row("SELECT notes FROM papers WHERE id=1", [], |r| {
                    r.get::<_, Option<String>>(0)
                })
                .unwrap()
                .map(Value::String)
                .unwrap_or(Value::Null))
        })
        .unwrap();
    assert!(notes.is_null());
}

#[test]
fn missing_observation_is_explicit_and_missing_paper_keeps_legacy_detail() {
    let (_dir, mut service) = fixture();
    service.observations.remove(&1);
    assert!(matches!(
        service.get_paper(PaperId(1)),
        Err(SasooError::Unsupported(_))
    ));
    assert!(
        matches!(service.get_paper(PaperId(999)),Err(SasooError::NotFound(message)) if message=="Paper 999 not found.")
    );
}

#[test]
fn read_only_services_keep_active_queue_and_runtime_history_guards() {
    use sasoo_backend::http::files::{AssetAccess, AssetRequest, AssetService};
    for mutation in [
        "UPDATE papers SET status='analyzing' WHERE id=1",
        "INSERT INTO analysis_runs(paper_id,status) VALUES(1,'queued')",
        "CREATE TABLE runtime_executions(execution_id TEXT); INSERT INTO runtime_executions VALUES('history')",
    ] {
        let (dir, mut service) = fixture();
        service
            .db
            .blocking_call(move |conn| {
                conn.execute_batch(mutation)
                    .map_err(sasoo_backend::storage::db::db_sql_error)?;
                Ok(())
            })
            .unwrap();
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
        service.db = open_db(&paths, DbAccess::ReadOnly).unwrap();
        assert!(
            matches!(
                service.list_papers(PaperQuery::default()),
                Err(SasooError::Unsupported(_))
            ),
            "{mutation}"
        );
        assert!(
            matches!(
                service.get_paper(PaperId(1)),
                Err(SasooError::Unsupported(_))
            ),
            "{mutation}"
        );
        let assets = AssetService {
            db: service.db.clone(),
            search_roots: vec![root],
            access: AssetAccess::default(),
        };
        assert!(
            matches!(
                assets.resolve_asset(AssetRequest::Pdf {
                    paper_id: PaperId(1)
                }),
                Err(SasooError::Unsupported(_))
            ),
            "{mutation}"
        );
    }
}

#[tokio::test]
async fn fixed_observation_fixtures_cannot_become_the_http_read_implementation() {
    use axum::{
        body::Body,
        http::{Request, StatusCode},
    };
    use sasoo_backend::http::{ApiState, build_router};
    use std::sync::Arc;
    use tower::ServiceExt;
    let (_dir, service) = fixture();
    let app = build_router(ApiState {
        api_token: None,
        shutdown_token: None,
        production: false,
        library_path: "/synthetic/library".into(),
        shutdown_signal: None,
        library: None,
        #[cfg(feature = "pdf-xberg-native")]
        pdf_candidate: None,
        paper_service: Some(Arc::new(service)),
    });
    let response = app
        .oneshot(
            Request::builder()
                .uri("/api/papers")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::NOT_IMPLEMENTED);
}
