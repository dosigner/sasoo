use axum::{
    body::Body,
    http::{Request, StatusCode},
};
use http_body_util::BodyExt;
use sasoo_backend::http::{ApiState, build_router};
use serde_json::{Value, json};
use tower::ServiceExt;

fn state() -> ApiState {
    ApiState {
        api_token: Some("contract-token".into()),
        shutdown_token: Some("shutdown-test".into()),
        production: true,
        library_path: "/synthetic/library".into(),
        shutdown_signal: None,
        library: None,
        #[cfg(feature = "pdf-xberg-native")]
        pdf_candidate: None,
        paper_service: None,
    }
}
async fn call(
    method: &str,
    path: &str,
    headers: &[(&str, &str)],
    state: ApiState,
) -> (StatusCode, axum::http::HeaderMap, Vec<u8>) {
    let mut req = Request::builder().method(method).uri(path);
    for (key, val) in headers {
        req = req.header(*key, *val);
    }
    let res = build_router(state)
        .oneshot(req.body(Body::empty()).unwrap())
        .await
        .unwrap();
    let status = res.status();
    let headers = res.headers().clone();
    (
        status,
        headers,
        res.into_body().collect().await.unwrap().to_bytes().to_vec(),
    )
}
#[tokio::test]
async fn health_matches_shared_hmac_and_root_requires_auth() {
    let (status, _, body) = call("GET", "/health", &[], state()).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        serde_json::from_slice::<Value>(&body).unwrap(),
        json!({"status":"ok","instance_proof":"7723551a40c4ab8b1b68febd7dda4bb0524572253842d2172c55aa96852ac5c2"})
    );
    let (status, headers, _) = call("GET", "/", &[("Origin", "null")], state()).await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
    assert!(!headers.contains_key("access-control-allow-origin"));
    let (status, _, body) = call(
        "GET",
        "/",
        &[("Authorization", "Bearer contract-token")],
        state(),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        serde_json::from_slice::<Value>(&body).unwrap()["library_path"],
        "/synthetic/library"
    );
}
#[tokio::test]
async fn missing_production_token_is_503_but_options_and_health_exempt() {
    let mut s = state();
    s.api_token = None;
    assert_eq!(
        call("GET", "/", &[], s.clone()).await.0,
        StatusCode::SERVICE_UNAVAILABLE
    );
    assert_eq!(
        call("GET", "/health", &[], s.clone()).await.0,
        StatusCode::OK
    );
    let (status, headers, body) = call(
        "OPTIONS",
        "/api/papers",
        &[
            ("Origin", "null"),
            ("Access-Control-Request-Method", "GET"),
            ("Access-Control-Request-Headers", "Authorization"),
        ],
        s,
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(headers["access-control-allow-origin"], "null");
    assert_eq!(body, b"OK");
}
#[tokio::test]
async fn shutdown_requires_both_tokens_and_a_controller() {
    assert_eq!(
        call(
            "POST",
            "/shutdown",
            &[("X-Shutdown-Token", "shutdown-test")],
            state()
        )
        .await
        .0,
        StatusCode::UNAUTHORIZED
    );
    assert_eq!(
        call(
            "POST",
            "/shutdown",
            &[("Authorization", "Bearer contract-token")],
            state()
        )
        .await
        .0,
        StatusCode::FORBIDDEN
    );
    assert_eq!(
        call(
            "POST",
            "/shutdown",
            &[
                ("Authorization", "Bearer contract-token"),
                ("X-Shutdown-Token", "shutdown-test")
            ],
            state()
        )
        .await
        .0,
        StatusCode::SERVICE_UNAVAILABLE
    );
    let (tx, mut rx) = tokio::sync::watch::channel(false);
    let mut s = state();
    s.shutdown_signal = Some(tx);
    assert_eq!(
        call(
            "POST",
            "/shutdown",
            &[
                ("Authorization", "Bearer contract-token"),
                ("X-Shutdown-Token", "shutdown-test")
            ],
            s
        )
        .await
        .0,
        StatusCode::OK
    );
    rx.changed().await.unwrap();
    assert!(*rx.borrow());
}
#[tokio::test]
async fn asset_capability_is_path_scoped_decoded_and_not_general_auth() {
    let fixture: Value =
        serde_json::from_str(include_str!("../../contract-fixtures/hmac-vectors.json")).unwrap();
    for (path, token) in fixture["assets"].as_object().unwrap() {
        let path = format!("{path}?sasoo_asset_token={}", token.as_str().unwrap());
        assert_eq!(
            call("GET", &path, &[], state()).await.0,
            StatusCode::NOT_IMPLEMENTED
        );
    }
    assert_eq!(
        call(
            "GET",
            "/?sasoo_asset_token=9bf619e0a7d97535fbcf0d1d574019577f62f664eebce5045dc25229ef1a5267",
            &[],
            state()
        )
        .await
        .0,
        StatusCode::UNAUTHORIZED
    );
    let path = "/static/library/%ED%95%9C%EA%B8%80%20%25.pdf";
    let token =
        sasoo_backend::http::auth::asset_proof("contract-token", "/static/library/한글 %.pdf");
    assert_eq!(
        call(
            "GET",
            &format!("{path}?sasoo_asset_token={token}"),
            &[],
            state()
        )
        .await
        .0,
        StatusCode::NOT_IMPLEMENTED
    );
}
#[tokio::test]
async fn docs_schema_route_coverage_redirect_and_head_contract() {
    let auth = [("Authorization", "Bearer contract-token")];
    let (status, _, body) = call("GET", "/openapi.json", &auth, state()).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        serde_json::from_slice::<Value>(&body).unwrap(),
        serde_json::from_str::<Value>(include_str!(
            "../../backend/api/fixtures/openapi_snapshot.json"
        ))
        .unwrap()
    );
    for path in ["/docs", "/redoc"] {
        let (status, h, b) = call("GET", path, &auth, state()).await;
        assert_eq!(status, StatusCode::OK);
        assert!(h["content-type"].to_str().unwrap().starts_with("text/html"));
        assert!(!b.is_empty());
    }
    let (status, h, _) = call("GET", "/health/", &auth, state()).await;
    assert_eq!(status, StatusCode::TEMPORARY_REDIRECT);
    assert_eq!(h["location"], "http://localhost/health");
    assert_eq!(
        call("HEAD", "/health", &auth, state()).await.0,
        StatusCode::METHOD_NOT_ALLOWED
    );
    assert_eq!(
        call("GET", "/not-a-route", &auth, state()).await.0,
        StatusCode::NOT_FOUND
    );
    assert_eq!(
        call("POST", "/health", &auth, state()).await.0,
        StatusCode::METHOD_NOT_ALLOWED
    );
}

#[tokio::test]
async fn every_declared_operation_has_a_deliberate_milestone_response() {
    let schema: Value = serde_json::from_str(include_str!(
        "../../backend/api/fixtures/openapi_snapshot.json"
    ))
    .unwrap();
    let mut count = 0;
    for (template, operations) in schema["paths"].as_object().unwrap() {
        let mut path = template.to_string();
        for (name, value) in [
            ("paper_id", "7"),
            ("figure_id", "figure-1"),
            ("viz_id", "viz-1"),
            ("name", "test-agent"),
        ] {
            path = path.replace(&format!("{{{name}}}"), value);
        }
        for method in operations
            .as_object()
            .unwrap()
            .keys()
            .filter(|m| ["get", "post", "put", "patch", "delete"].contains(&m.as_str()))
        {
            let (status, _, _) = call(
                &method.to_uppercase(),
                &path,
                &[("Authorization", "Bearer contract-token")],
                state(),
            )
            .await;
            assert_eq!(
                status,
                match path.as_str() {
                    "/" | "/health" => StatusCode::OK,
                    "/shutdown" => StatusCode::FORBIDDEN,
                    _ => StatusCode::NOT_IMPLEMENTED,
                },
                "{method} {template}"
            );
            count += 1;
        }
    }
    assert_eq!(count, 38);
}
#[tokio::test]
async fn preflight_rejects_disallowed_origin_and_method_with_legacy_cors_headers() {
    let (status, headers, body) = call(
        "OPTIONS",
        "/api/papers",
        &[
            ("Origin", "https://external.invalid"),
            ("Access-Control-Request-Method", "TRACE"),
        ],
        state(),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert!(!headers.contains_key("access-control-allow-origin"));
    assert_eq!(headers["access-control-allow-credentials"], "true");
    assert_eq!(body, b"Disallowed CORS origin, method");
}

#[tokio::test]
async fn captured_python_document_bodies_remain_byte_identical() {
    use base64::{Engine as _, engine::general_purpose::STANDARD};
    let captured: Value = serde_json::from_str(include_str!(
        "../../contract-fixtures/rust-backend-v2/http.json"
    ))
    .unwrap();
    for (id, path) in [
        ("openapi", "/openapi.json"),
        ("docs", "/docs"),
        ("redoc", "/redoc"),
    ] {
        let case = captured["cases"]
            .as_array()
            .unwrap()
            .iter()
            .find(|c| c["id"] == id)
            .unwrap();
        let expected = STANDARD
            .decode(case["response"]["body_base64"].as_str().unwrap())
            .unwrap();
        let (status, headers, body) = call(
            "GET",
            path,
            &[("Authorization", "Bearer contract-token")],
            state(),
        )
        .await;
        assert_eq!(
            status.as_u16(),
            case["response"]["status"].as_u64().unwrap() as u16
        );
        assert_eq!(body, expected, "{id} wire body");
        assert_eq!(
            headers["content-type"].to_str().unwrap(),
            case["response"]["headers"]["content-type"]
                .as_str()
                .unwrap()
        );
    }
}
