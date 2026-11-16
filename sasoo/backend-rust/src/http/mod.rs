pub mod auth;
pub mod dto;
pub mod files;
pub mod library;
mod paper_files;
pub mod papers;
#[cfg(feature = "pdf-xberg-native")]
pub mod pdf_candidate;
pub mod settings;

use axum::{
    Json, Router,
    body::Body,
    extract::{Request, State},
    http::{HeaderMap, HeaderValue, Method, StatusCode},
    middleware::{self, Next},
    response::{Html, IntoResponse, Response},
    routing::any,
};
use percent_encoding::percent_decode_str;
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    path::PathBuf,
    sync::{Arc, OnceLock},
};
use tokio::sync::watch;

#[derive(Clone)]
pub struct ApiState {
    pub api_token: Option<String>,
    pub shutdown_token: Option<String>,
    pub production: bool,
    pub library_path: PathBuf,
    pub shutdown_signal: Option<watch::Sender<bool>>,
    pub library: Option<Arc<library::LibraryReader>>,
    pub paper_service: Option<Arc<papers::PaperService>>,
    #[cfg(feature = "pdf-xberg-native")]
    pub pdf_candidate: Option<Arc<crate::pdf::import::PdfCandidate>>,
}

const OPENAPI: &str = include_str!("../../../backend/api/fixtures/openapi_snapshot.json");
const ALLOWED_ORIGINS: &[&str] = &[
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8080",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8080",
    "app://.",
    "null",
];
const METHODS: &str = "DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT";

pub fn build_router(state: ApiState) -> Router {
    let mut router = Router::new();
    for path in declared_routes().keys() {
        router = router.route(path, any(dispatch));
    }
    router
        .fallback(dispatch)
        .layer(axum::extract::DefaultBodyLimit::max(
            crate::pdf::artifacts::MAX_PDF_BYTES + 65536,
        ))
        .layer(middleware::from_fn_with_state(state.clone(), boundary))
        .with_state(state)
}

/// Source schema fixes the public inventory while unfinished handlers stay explicit.
pub fn declared_routes() -> &'static BTreeMap<String, Vec<String>> {
    static ROUTES: OnceLock<BTreeMap<String, Vec<String>>> = OnceLock::new();
    ROUTES.get_or_init(|| {
        let schema: Value =
            serde_json::from_str(OPENAPI).expect("Checked-in OpenAPI fixture must be valid");
        let mut routes = BTreeMap::new();
        for (path, ops) in schema["paths"].as_object().expect("OpenAPI paths") {
            let methods = ops
                .as_object()
                .expect("OpenAPI methods")
                .keys()
                .filter(|m| {
                    matches!(
                        m.as_str(),
                        "get" | "post" | "put" | "patch" | "delete" | "head" | "options"
                    )
                })
                .map(|m| m.to_ascii_uppercase())
                .collect();
            routes.insert(path.to_string(), methods);
        }
        for path in ["/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"] {
            routes.insert(path.into(), vec!["GET".into(), "HEAD".into()]);
        }
        routes.insert(
            "/static/library/{*requested_path}".into(),
            vec!["GET".into()],
        );
        #[cfg(feature = "pdf-xberg-native")]
        for (path, methods) in [
            ("/api/pdf-operations/{operation_id}", vec!["GET".into()]),
            (
                "/api/papers/{paper_id}/extraction",
                vec!["GET".into(), "POST".into()],
            ),
            ("/api/papers/{paper_id}/search", vec!["GET".into()]),
            (
                "/api/papers/{paper_id}/selection-context",
                vec!["POST".into()],
            ),
            (
                "/api/papers/upload/{operation_id}/cancel",
                vec!["POST".into()],
            ),
        ] {
            routes.insert(path.into(), methods);
        }
        routes
    })
}
fn decoded_path(req: &Request) -> String {
    percent_decode_str(req.uri().path())
        .decode_utf8_lossy()
        .into_owned()
}
fn header<'a>(headers: &'a HeaderMap, name: &str) -> Option<&'a str> {
    headers.get(name).and_then(|v| v.to_str().ok())
}
fn detail(code: StatusCode, message: &str) -> Response {
    (code, Json(json!({"detail":message}))).into_response()
}
fn matches_path(template: &str, path: &str) -> bool {
    let mut actual = path.split('/');
    for part in template.split('/') {
        if part.starts_with("{*") {
            return actual.next().is_some_and(|p| !p.is_empty());
        }
        let Some(value) = actual.next() else {
            return false;
        };
        if part.starts_with('{') && part.ends_with('}') {
            if value.is_empty() {
                return false;
            }
        } else if part != value {
            return false;
        }
    }
    actual.next().is_none()
}
fn methods_for(path: &str) -> Option<Vec<String>> {
    declared_routes()
        .iter()
        .find_map(|(template, methods)| matches_path(template, path).then(|| methods.clone()))
}
fn with_cors(mut response: Response, origin: Option<&str>) -> Response {
    if let Some(origin) = origin {
        response.headers_mut().insert(
            "access-control-allow-credentials",
            HeaderValue::from_static("true"),
        );
        if ALLOWED_ORIGINS.contains(&origin) {
            response.headers_mut().insert(
                "access-control-allow-origin",
                HeaderValue::from_str(origin).expect("Known origin"),
            );
            response
                .headers_mut()
                .insert("vary", HeaderValue::from_static("Origin"));
            response.headers_mut().insert(
                "access-control-expose-headers",
                HeaderValue::from_static("X-Sasoo-Backend-Mode"),
            );
        }
    }
    response
}
async fn boundary(State(state): State<ApiState>, req: Request, next: Next) -> Response {
    let path = decoded_path(&req);
    if req.method() != Method::OPTIONS && path != "/health" {
        let token = state.api_token.as_deref().unwrap_or("");
        if token.is_empty() {
            #[cfg(feature = "pdf-xberg-native")]
            if state.pdf_candidate.is_some() {
                return detail(
                    StatusCode::SERVICE_UNAVAILABLE,
                    "PDF candidate requires a local API token",
                );
            }
            if state.production {
                return detail(
                    StatusCode::SERVICE_UNAVAILABLE,
                    "Local API token is not configured",
                );
            }
        } else {
            let bearer = header(req.headers(), "authorization")
                .and_then(|v| v.strip_prefix("Bearer "))
                .unwrap_or("");
            let asset_token = req
                .uri()
                .query()
                .unwrap_or("")
                .rsplit('&')
                .find_map(|pair| {
                    pair.split_once('=')
                        .filter(|(k, _)| *k == "sasoo_asset_token")
                        .map(|(_, v)| {
                            percent_decode_str(&v.replace('+', " "))
                                .decode_utf8_lossy()
                                .into_owned()
                        })
                });
            let valid_asset = auth::is_asset_path(&path)
                && asset_token.is_some_and(|supplied| {
                    !supplied.is_empty() && auth::equal(&supplied, &auth::asset_proof(token, &path))
                });
            if !auth::equal(bearer, token) && !valid_asset {
                return detail(
                    StatusCode::UNAUTHORIZED,
                    "Missing or invalid local API token",
                );
            }
        }
    }
    let origin = header(req.headers(), "origin").map(str::to_owned);
    if req.method() == Method::OPTIONS
        && origin.is_some()
        && header(req.headers(), "access-control-request-method").is_some()
    {
        let origin = origin.as_deref().unwrap();
        let requested = header(req.headers(), "access-control-request-method").unwrap();
        let mut failures = Vec::new();
        if !ALLOWED_ORIGINS.contains(&origin) {
            failures.push("origin");
        }
        if !METHODS.split(", ").any(|m| m == requested) {
            failures.push("method");
        }
        let body = if failures.is_empty() {
            "OK".to_string()
        } else {
            format!("Disallowed CORS {}", failures.join(", "))
        };
        let mut response = (
            if failures.is_empty() {
                StatusCode::OK
            } else {
                StatusCode::BAD_REQUEST
            },
            body,
        )
            .into_response();
        response
            .headers_mut()
            .insert("vary", HeaderValue::from_static("Origin"));
        response.headers_mut().insert(
            "access-control-allow-methods",
            HeaderValue::from_static(METHODS),
        );
        response
            .headers_mut()
            .insert("access-control-max-age", HeaderValue::from_static("600"));
        if let Some(headers) = req.headers().get("access-control-request-headers") {
            response
                .headers_mut()
                .insert("access-control-allow-headers", headers.clone());
        }
        return with_cors(response, Some(origin));
    }
    with_cors(next.run(req).await, origin.as_deref())
}
async fn dispatch(State(state): State<ApiState>, req: Request) -> Response {
    let path = decoded_path(&req);
    let Some(methods) = methods_for(&path) else {
        let trimmed = path.trim_end_matches('/');
        if !trimmed.is_empty() && trimmed != path && methods_for(trimmed).is_some() {
            let host = header(req.headers(), "host")
                .or_else(|| req.uri().authority().map(|a| a.as_str()))
                .unwrap_or("localhost");
            let scheme = req.uri().scheme_str().unwrap_or("http");
            let query = req
                .uri()
                .query()
                .map(|q| format!("?{q}"))
                .unwrap_or_default();
            let mut response = StatusCode::TEMPORARY_REDIRECT.into_response();
            if let Ok(value) = HeaderValue::from_str(&format!("{scheme}://{host}{trimmed}{query}"))
            {
                response.headers_mut().insert("location", value);
            }
            return response;
        }
        return detail(StatusCode::NOT_FOUND, "Not Found");
    };
    if !methods.iter().any(|m| m == req.method().as_str()) {
        let mut response = detail(StatusCode::METHOD_NOT_ALLOWED, "Method Not Allowed");
        response
            .headers_mut()
            .insert("allow", HeaderValue::from_str(&methods.join(", ")).unwrap());
        return response;
    }
    #[cfg(feature = "pdf-xberg-native")]
    if let Some(candidate) = &state.pdf_candidate {
        if path.starts_with("/api/") || path.starts_with("/static/library/") {
            return pdf_candidate::dispatch(candidate.clone(), &path, req).await;
        }
    }
    if req.method() == Method::GET && path == "/api/papers" {
        if let Some(service) = &state.paper_service {
            return papers::list_http(service.clone(), req.uri().query().unwrap_or("")).await;
        }
    }
    if let Some(reader) = &state.library {
        if let Some(response) = library::dispatch(
            reader.clone(),
            &path,
            req.method(),
            req.uri().query().unwrap_or(""),
            req.headers(),
        )
        .await
        {
            return response;
        }
    }
    let mut response=match path.as_str(){
        "/"=>Json(json!({"service":"sasoo","status":"running","version":"1.3.0","library_path":state.library_path})).into_response(),
        "/health"=>Json(json!({"status":"ok","instance_proof":auth::health_proof(state.api_token.as_deref().unwrap_or(""))})).into_response(),
        "/shutdown"=>{
            match state.shutdown_token.as_deref().filter(|s|!s.is_empty()){
                None=>detail(StatusCode::SERVICE_UNAVAILABLE,"Shutdown token is not configured"),
                Some(token) if !header(req.headers(),"x-shutdown-token").is_some_and(|supplied|auth::equal(supplied,token))=>detail(StatusCode::FORBIDDEN,"Invalid shutdown token"),
                Some(_)=>match state.shutdown_signal{
                    None=>detail(StatusCode::SERVICE_UNAVAILABLE,"Graceful shutdown is unavailable"),
                    Some(sender)=>if sender.send(true).is_ok(){Json(json!({"status":"shutting_down"})).into_response()}else{detail(StatusCode::SERVICE_UNAVAILABLE,"Graceful shutdown is unavailable")},
                }
            }
        },
        "/openapi.json"=>([("content-type","application/json")],include_str!("../../resources/openapi-wire.json")).into_response(),
        "/docs"=>Html(include_str!("../../resources/docs.html")).into_response(),
        "/redoc"=>Html(include_str!("../../resources/redoc.html")).into_response(),
        "/docs/oauth2-redirect"=>Html(include_str!("../../resources/oauth2-redirect.html")).into_response(),
        _=>detail(StatusCode::NOT_IMPLEMENTED,"Rust backend milestone does not implement this operation"),
    };
    if req.method() == Method::HEAD {
        *response.body_mut() = Body::empty();
    }
    response
}
