#![cfg(feature = "pdf-xberg-native")]
#[path = "support/library_fixture.rs"]
mod fixture;
use axum::{
    body::Body,
    http::{Request, StatusCode},
};
use http_body_util::BodyExt;
use sasoo_backend::{
    http::{ApiState, build_router},
    pdf::import::{CANDIDATE_MARKER, PdfCandidate},
};
use serde_json::{Value, json};
use std::{fs, sync::Arc};
use tower::ServiceExt;

fn app(root: &std::path::Path) -> axum::Router {
    fixture::seed(root, true);
    rusqlite::Connection::open(root.join("sasoo.db"))
        .unwrap()
        .execute("UPDATE papers SET status='pending'", [])
        .unwrap();
    fs::write(root.join(".sasoo-rust-pdf-candidate"), CANDIDATE_MARKER).unwrap();
    build_router(ApiState {
        api_token: Some("fixture-token".into()),
        shutdown_token: None,
        production: true,
        library_path: root.join("library"),
        shutdown_signal: None,
        library: None,
        paper_service: None,
        pdf_candidate: Some(Arc::new(PdfCandidate::open(root).unwrap().with_execution(
            sasoo_backend::pdf::process::Policy::new(
                env!("CARGO_BIN_EXE_sasoo-backend"),
                std::time::Duration::from_secs(5),
            ),
        ))),
    })
}
async fn call(
    app: &axum::Router,
    method: &str,
    path: &str,
    content_type: &str,
    bytes: Vec<u8>,
    auth: bool,
) -> (StatusCode, Vec<u8>) {
    let mut builder = Request::builder()
        .method(method)
        .uri(path)
        .header("content-type", content_type);
    if auth {
        builder = builder.header("authorization", "Bearer fixture-token");
    }
    let response = app
        .clone()
        .oneshot(builder.body(Body::from(bytes)).unwrap())
        .await
        .unwrap();
    let status = response.status();
    (
        status,
        response
            .into_body()
            .collect()
            .await
            .unwrap()
            .to_bytes()
            .to_vec(),
    )
}
fn multipart(name: &str, bytes: &[u8]) -> Vec<u8> {
    let mut body=format!("--test-boundary\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\nContent-Type: application/pdf\r\n\r\n").into_bytes();
    body.extend_from_slice(bytes);
    body.extend_from_slice(b"\r\n--test-boundary--\r\n");
    body
}
async fn get(app: &axum::Router, path: &str) -> Value {
    let (code, bytes) = call(app, "GET", path, "application/json", vec![], true).await;
    assert_eq!(code, StatusCode::OK, "{}", String::from_utf8_lossy(&bytes));
    serde_json::from_slice(&bytes).unwrap()
}

#[tokio::test]
async fn actual_router_connects_multipart_publication_search_and_selection_with_unverified_pages() {
    let root = tempfile::tempdir().unwrap();
    let app = app(root.path());
    let body = multipart("source.PDF", &fixture::minimal_pdf());
    assert_eq!(
        call(
            &app,
            "POST",
            "/api/papers/upload",
            "multipart/form-data; boundary=test-boundary",
            body.clone(),
            false
        )
        .await
        .0,
        StatusCode::UNAUTHORIZED
    );
    let (code, bytes) = call(
        &app,
        "POST",
        "/api/papers/upload",
        "multipart/form-data; boundary=test-boundary",
        body,
        true,
    )
    .await;
    assert_eq!(code, StatusCode::OK, "{}", String::from_utf8_lossy(&bytes));
    let paper: Value = serde_json::from_slice(&bytes).unwrap();
    let id = paper["id"].as_i64().unwrap();
    assert_eq!(paper["pdf_candidate"], true);
    assert_eq!(paper["visual_ready"], false);
    assert_eq!(paper["status"], "pending");
    let list = get(&app, "/api/papers").await;
    assert!(
        list["papers"]
            .as_array()
            .unwrap()
            .iter()
            .any(|p| p["id"] == id && p["text_ready"] == true)
    );
    let found = get(&app, &format!("/api/papers/{id}/search?q=efficiency")).await;
    assert_eq!(found["independent_page_verification"], false);
    assert_eq!(found["results"][0]["page"], 1);
    assert_eq!(found["results"][0]["extraction_status"], "page_unverified");
    let selection = json!({"text":"Efficiency is 0.8","page":1,"end_page":1});
    let (code, bytes) = call(
        &app,
        "POST",
        &format!("/api/papers/{id}/selection-context"),
        "application/json",
        serde_json::to_vec(&selection).unwrap(),
        true,
    )
    .await;
    assert_eq!(code, StatusCode::OK);
    let context: Value = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(context["context"]["status"], "matched");
    assert_eq!(context["page_evidence"], "page_unverified");
    assert_eq!(
        call(
            &app,
            "POST",
            &format!("/api/papers/{id}/selection-context"),
            "application/json",
            br#"{"text":"efficiency","page":0,"end_page":1}"#.to_vec(),
            true
        )
        .await
        .0,
        StatusCode::UNPROCESSABLE_ENTITY
    );
    let version = paper["extraction"]["version"].as_str().unwrap();
    let folder = paper["folder_name"].as_str().unwrap();
    assert_eq!(
        call(
            &app,
            "GET",
            &format!("/static/library/{folder}/.sasoo-runtime/pdf/{version}/document.json"),
            "application/json",
            vec![],
            true
        )
        .await
        .0,
        StatusCode::NOT_FOUND
    );
    assert_eq!(
        call(
            &app,
            "GET",
            &format!("/api/papers/{id}/pdf"),
            "application/json",
            vec![],
            true
        )
        .await
        .1,
        fixture::minimal_pdf()
    );
    assert_eq!(
        call(
            &app,
            "POST",
            &format!("/api/analysis/{id}/run"),
            "application/json",
            b"{}".to_vec(),
            true
        )
        .await
        .0,
        StatusCode::FORBIDDEN
    );
}

#[tokio::test]
async fn malformed_uploads_and_oversize_bodies_have_no_published_paper() {
    let root = tempfile::tempdir().unwrap();
    let app = app(root.path());
    let before = get(&app, "/api/papers").await["total"].clone();
    for (name, bytes, expected) in [
        ("file.txt", b"%PDF-".as_slice(), StatusCode::BAD_REQUEST),
        ("file.pdf", b"bad".as_slice(), StatusCode::BAD_REQUEST),
        (
            "file.pdf",
            b"%PDF-1.7\nbroken".as_slice(),
            StatusCode::UNPROCESSABLE_ENTITY,
        ),
    ] {
        assert_eq!(
            call(
                &app,
                "POST",
                "/api/papers/upload",
                "multipart/form-data; boundary=test-boundary",
                multipart(name, bytes),
                true
            )
            .await
            .0,
            expected
        );
    }
    let oversize = vec![b'x'; 100 * 1024 * 1024 + 1];
    assert_eq!(
        call(
            &app,
            "POST",
            "/api/papers/upload",
            "multipart/form-data; boundary=test-boundary",
            multipart("file.pdf", &oversize),
            true
        )
        .await
        .0,
        StatusCode::PAYLOAD_TOO_LARGE
    );
    assert_eq!(get(&app, "/api/papers").await["total"], before);
}

#[tokio::test]
async fn operation_recovery_route_returns_committed_version_and_never_reuploads() {
    let root = tempfile::tempdir().unwrap();
    let app = app(root.path());
    let op = uuid::Uuid::new_v4();
    let response = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/papers/upload")
                .header("authorization", "Bearer fixture-token")
                .header(
                    "content-type",
                    "multipart/form-data; boundary=test-boundary",
                )
                .header("x-sasoo-pdf-operation-id", op.to_string())
                .body(Body::from(multipart("source.pdf", &fixture::minimal_pdf())))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let paper: Value =
        serde_json::from_slice(&response.into_body().collect().await.unwrap().to_bytes()).unwrap();
    let result = get(&app, &format!("/api/pdf-operations/{op}")).await;
    assert_eq!(result["publication_state"], "committed");
    assert_eq!(result["version"], paper["extraction"]["version"]);
    assert_eq!(result["automatic_retry"], false);
}
