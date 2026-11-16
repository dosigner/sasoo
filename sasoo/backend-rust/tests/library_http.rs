#[path = "support/library_fixture.rs"]
mod fixture;

use axum::{
    body::Body,
    http::{Request, StatusCode},
};
use http_body_util::BodyExt;
use sasoo_backend::http::{ApiState, build_router, library::LibraryReader};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    fs,
    path::{Path, PathBuf},
    sync::Arc,
};
use tower::ServiceExt;

fn tree(root: &Path) -> BTreeMap<PathBuf, Vec<u8>> {
    fn visit(root: &Path, path: &Path, output: &mut BTreeMap<PathBuf, Vec<u8>>) {
        for entry in fs::read_dir(path).unwrap() {
            let path = entry.unwrap().path();
            if path.is_dir() {
                visit(root, &path, output);
            } else {
                output.insert(
                    path.strip_prefix(root).unwrap().into(),
                    fs::read(path).unwrap(),
                );
            }
        }
    }
    let mut output = BTreeMap::new();
    visit(root, root, &mut output);
    output
}

fn app(root: &Path) -> axum::Router {
    build_router(ApiState {
        api_token: Some("fixture-token".into()),
        shutdown_token: None,
        production: true,
        library_path: root.join("library"),
        shutdown_signal: None,
        library: Some(Arc::new(LibraryReader::open(root).unwrap())),
        #[cfg(feature = "pdf-xberg-native")]
        pdf_candidate: None,
        paper_service: None,
    })
}
async fn call(app: axum::Router, method: &str, path: &str) -> (StatusCode, Vec<u8>) {
    let response = app
        .oneshot(
            Request::builder()
                .method(method)
                .uri(path)
                .header("authorization", "Bearer fixture-token")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status();
    let bytes = response
        .into_body()
        .collect()
        .await
        .unwrap()
        .to_bytes()
        .to_vec();
    (status, bytes)
}
async fn get(app: axum::Router, path: &str) -> Value {
    let (status, bytes) = call(app, "GET", path).await;
    assert_eq!(
        status,
        StatusCode::OK,
        "{path}: {}",
        String::from_utf8_lossy(&bytes)
    );
    serde_json::from_slice(&bytes).unwrap()
}

#[tokio::test]
async fn reads_existing_data_sources_and_nullable_usage_without_writes() {
    for legacy in [false, true] {
        let dir = tempfile::tempdir().unwrap();
        fixture::seed(dir.path(), !legacy);
        let before = tree(dir.path());
        let app = app(dir.path());
        let papers = get(app.clone(), "/api/papers?page=1&page_size=1&sort_order=asc").await;
        assert_eq!(papers["total"], 2);
        assert_eq!(papers["papers"][0]["id"], 1);
        assert_eq!(papers["papers"][0]["notes"], "보존할 메모");
        assert_eq!(papers["papers"][0]["text_ready"], true);
        let detail = get(app.clone(), "/api/papers/1").await;
        assert_eq!(detail["title"], "합성 광학 논문");
        assert_eq!(get(app.clone(), "/api/papers/2").await["text_ready"], false);
        let (status, pdf) = call(app.clone(), "GET", "/api/papers/1/pdf").await;
        assert_eq!(status, 200);
        assert_eq!(pdf, fixture::minimal_pdf());
        let discussion = get(app.clone(), "/api/analysis/1/discussion").await;
        assert_eq!(discussion["messages"].as_array().unwrap().len(), 3);
        assert_eq!(discussion["messages"][2]["status"], "interrupted");
        assert!(discussion["messages"][2]["cost_usd"].is_null());
        assert_eq!(discussion["context"]["context_tokens"], 100);
        if legacy {
            assert!(discussion["messages"][1]["context"].is_null());
        } else {
            assert_eq!(
                discussion["messages"][1]["context"]["sources"][0]["result_id"],
                10
            );
        }
        let results = get(app.clone(), "/api/analysis/1/results").await;
        assert_eq!(results["screening"]["summary"], "저장된 요약");
        assert_eq!(results["status"]["validation_state"], "legacy_unverified");
        assert!(results["status"]["phases"][0]["cost_usd"].is_null());
        let figures = get(app.clone(), "/api/analysis/1/figures").await;
        assert_eq!(figures["figures"][0]["id"], 7);
        assert_eq!(figures["figures"][0]["bbox"], json!([10, 20, 210, 120]));
        let tables = get(app.clone(), "/api/analysis/1/tables").await;
        assert_eq!(tables["tables"][0]["id"], 8);
        assert_eq!(tables["tables"][0]["review_required"], false);
        assert_eq!(
            get(app.clone(), "/api/analysis/1/recipe").await["recipe"]["title"],
            "합성 레시피"
        );
        assert_eq!(
            get(app.clone(), "/api/analysis/1/visualizations").await["items"],
            json!([])
        );
        let settings = get(app.clone(), "/api/settings").await;
        assert_eq!(settings["research_areas"], json!(["광학"]));
        assert_eq!(settings["active_provider"], Value::Null);
        assert_eq!(settings["gemini_key_unreadable"], true);
        let encoded = settings.to_string();
        assert!(!encoded.contains("synthetic-private-value"));
        assert!(!encoded.contains("synthetic-unreadable"));
        assert!(!encoded.contains("/outside/old"));
        for (method, path) in [
            ("POST", "/api/analysis/1/chat"),
            ("POST", "/api/analysis/1/run"),
            ("PATCH", "/api/papers/1"),
            ("PUT", "/api/settings"),
            ("DELETE", "/api/papers/1"),
            ("POST", "/api/analysis/1/discussion/reset"),
        ] {
            assert_eq!(call(app.clone(), method, path).await.0, 403, "{path}");
        }
        assert_eq!(
            tree(dir.path()),
            before,
            "HTTP reads and rejected writes must not change any file"
        );
    }
}

#[tokio::test]
async fn invalid_queries_missing_resources_auth_ranges_and_private_paths() {
    let dir = tempfile::tempdir().unwrap();
    fixture::seed(dir.path(), true);
    let app = app(dir.path());
    for path in [
        "/api/papers?page=0",
        "/api/papers?page_size=101",
        "/api/papers?page=no",
        "/api/papers?page=9223372036854775807&page_size=100",
        "/api/papers/abc",
        "/api/analysis/-1/discussion",
    ] {
        assert_eq!(call(app.clone(), "GET", path).await.0, 422, "{path}");
    }
    for path in [
        "/api/papers/999",
        "/api/analysis/999/discussion",
        "/api/papers/2/pdf",
        "/api/analysis/1/synthesis",
    ] {
        assert_eq!(call(app.clone(), "GET", path).await.0, 404, "{path}");
    }
    for path in [
        "/static/library/one/.document_context.json",
        "/static/library/one/../sasoo.db",
        "/static/library/one/%2e%2e/sasoo.db",
        "/static/library/one/%5c..%5csasoo.db",
    ] {
        assert_eq!(call(app.clone(), "GET", path).await.0, 422, "{path}");
    }
    let no_auth = app
        .clone()
        .oneshot(
            Request::builder()
                .uri("/api/papers")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(no_auth.status(), 401);
    let pdf = app
        .oneshot(
            Request::builder()
                .uri("/api/papers/1/pdf")
                .header("authorization", "Bearer fixture-token")
                .header("range", "bytes=0-7")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(pdf.status(), 206);
    assert_eq!(
        &pdf.into_body().collect().await.unwrap().to_bytes()[..],
        b"%PDF-1.4"
    );
}

#[test]
fn refuses_unmarked_missing_and_escaping_roots() {
    let dir = tempfile::tempdir().unwrap();
    assert!(LibraryReader::open(dir.path()).is_err());
    fixture::seed(dir.path(), false);
    fs::write(dir.path().join(".sasoo-rust-isolated-fixture"), "other\n").unwrap();
    assert!(LibraryReader::open(dir.path()).is_err());
}

#[cfg(unix)]
#[tokio::test]
async fn folder_and_asset_symlinks_cannot_escape_the_library() {
    use std::os::unix::fs::symlink;
    let dir = tempfile::tempdir().unwrap();
    fixture::seed(dir.path(), true);
    let outside = tempfile::tempdir().unwrap();
    fs::write(outside.path().join("private.txt"), "private").unwrap();
    symlink(
        outside.path().join("private.txt"),
        dir.path().join("library/one/public.txt"),
    )
    .unwrap();
    let app = app(dir.path());
    assert_eq!(
        call(app.clone(), "GET", "/static/library/one/public.txt")
            .await
            .0,
        404
    );
    symlink(outside.path(), dir.path().join("library/missing")).unwrap();
    assert_eq!(call(app, "GET", "/api/papers/2").await.0, 403);
}

#[tokio::test]
async fn rebases_old_absolute_asset_names_without_opening_the_old_library() {
    let dir = tempfile::tempdir().unwrap();
    fixture::seed(dir.path(), true);
    let conn = rusqlite::Connection::open(dir.path().join("sasoo.db")).unwrap();
    conn.execute(
        "UPDATE figures SET file_path='/outside/old/library/one/figures/figure.svg' WHERE id=7",
        [],
    )
    .unwrap();
    drop(conn);
    let app = app(dir.path());
    let figures = get(app.clone(), "/api/analysis/1/figures").await;
    let url = figures["figures"][0]["file_path"].as_str().unwrap();
    assert_eq!(url, "/static/library/one/figures/figure%2Esvg");
    assert_eq!(
        call(app, "GET", url).await.1,
        fs::read(dir.path().join("library/one/figures/figure.svg")).unwrap()
    );
}
