//! Candidate-only API, with no provider calls or default backend selection.
use crate::{
    analysis::{
        chat_retrieval::{Document, search},
        selection_context::{Selection, match_selection},
    },
    error::{Result, SasooError},
    pdf::{
        artifacts::{MAX_PDF_BYTES, full_text, page_text},
        import::PdfCandidate,
    },
    types::PaperId,
};
use axum::{
    Json,
    extract::{FromRequest, Multipart, Request},
    http::{HeaderValue, Method, StatusCode},
    response::{IntoResponse, Response},
};
use serde_json::{Value, json};
use std::sync::Arc;
use tokio_util::sync::CancellationToken;

pub(crate) async fn produce<T, F>(service: Arc<PdfCandidate>, id: uuid::Uuid, f: F) -> Result<T>
where
    T: Send + 'static,
    F: FnOnce(Arc<PdfCandidate>, CancellationToken) -> Result<T> + Send + 'static,
{
    let permit = service.admission.clone().try_acquire_owned().map_err(|_| {
        SasooError::StorageBusy("A PDF producer is still running; retry after it returns".into())
    })?;
    let cancel = CancellationToken::new();
    let operation = service.register(id, cancel.clone())?;
    let _guard = cancel.clone().drop_guard();
    tokio::task::spawn_blocking(move || {
        let _permit = permit;
        let _operation = operation;
        f(service, cancel)
    })
    .await
    .map_err(|_| SasooError::Internal("PDF producer stopped".into()))?
}

fn failure(error: SasooError) -> Response {
    let status = match error {
        SasooError::NotFound(_) => StatusCode::NOT_FOUND,
        SasooError::InvalidInput(_) => StatusCode::UNPROCESSABLE_ENTITY,
        SasooError::Forbidden(_) => StatusCode::FORBIDDEN,
        SasooError::Conflict(_) => StatusCode::CONFLICT,
        SasooError::StorageBusy(_) => StatusCode::SERVICE_UNAVAILABLE,
        SasooError::Incomplete(_) => StatusCode::UNPROCESSABLE_ENTITY,
        SasooError::Unsupported(_) => StatusCode::NOT_IMPLEMENTED,
        _ => StatusCode::INTERNAL_SERVER_ERROR,
    };
    let message = if status == StatusCode::INTERNAL_SERVER_ERROR {
        "PDF operation failed; incomplete files were not published".into()
    } else {
        error.to_string()
    };
    (status, Json(json!({"detail":message}))).into_response()
}

pub(crate) fn reader(service: &PdfCandidate) -> super::library::LibraryReader {
    super::library::LibraryReader {
        db: service.db.clone(),
        root: service.db.path().parent().unwrap().into(),
        assets: service.assets(),
    }
}

pub(crate) async fn dispatch(service: Arc<PdfCandidate>, path: &str, req: Request) -> Response {
    if path.starts_with("/static/library/") && path.split('/').any(|part| part.starts_with('.')) {
        return failure(SasooError::NotFound(
            "Private extraction files are not public assets".into(),
        ));
    }
    let method = req.method().clone();
    if let Some(id) = path.strip_prefix("/api/pdf-operations/") {
        return match uuid::Uuid::parse_str(id)
            .map_err(|_| SasooError::InvalidInput("Invalid PDF operation ID".into()))
            .and_then(|id| service.operation_status(id))
        {
            Ok(v) => Json(v).into_response(),
            Err(e) => failure(e),
        };
    }
    if let Some(id) = path
        .strip_prefix("/api/papers/upload/")
        .and_then(|v| v.strip_suffix("/cancel"))
    {
        return match uuid::Uuid::parse_str(id).map_err(|_|SasooError::InvalidInput("Invalid PDF operation ID".into())).and_then(|id|service.cancel(id)) {
            Ok(active)=>Json(json!({"cancel_requested":active,"native_stop":"cancel_requested_exit_not_confirmed","publication_state":"unknown_until_producer_returns"})).into_response(),Err(e)=>failure(e)
        };
    }
    let mut response = if path == "/api/papers/upload" && method == Method::POST {
        upload(service, req).await
    } else {
        let parts: Vec<_> = path.trim_start_matches('/').split('/').collect();
        let id = parts
            .get(2)
            .and_then(|id| id.parse::<i64>().ok())
            .filter(|id| *id > 0)
            .map(PaperId);
        let query = req.uri().query().unwrap_or("").to_owned();
        if path == "/api/papers" && method == Method::GET {
            let result = tokio::task::spawn_blocking(move || {
                let mut value = reader(&service).papers(super::library::paper_query(&query)?)?;
                for item in value["papers"]
                    .as_array_mut()
                    .ok_or_else(|| SasooError::Internal("Invalid paper list".into()))?
                {
                    let id = PaperId(item["id"].as_i64().unwrap());
                    if is_native(&service, id)? {
                        *item = service.paper(id)?;
                    }
                }
                Ok(value)
            })
            .await;
            encoded(result)
        } else if parts.get(1) == Some(&"papers") && id.is_some() {
            paper_route(service, id.unwrap(), parts.get(3).copied(), method, req).await
        } else if path == "/api/agents" && method == Method::GET {
            Json(json!([])).into_response()
        } else if parts.get(1) == Some(&"analysis") && id.is_some() && method == Method::GET {
            let id = id.unwrap();
            let resource = parts.get(3).unwrap_or(&"").to_string();
            encoded(
                tokio::task::spawn_blocking(move || {
                    let mut value = reader(&service).analysis(id, &resource)?;
                    if is_native(&service, id)? {
                        let status = if resource == "results" {
                            &mut value["status"]
                        } else {
                            &mut value
                        };
                        if resource == "status" || resource == "results" {
                            status["validation_state"] = json!("pdf_candidate_analysis_not_run");
                        }
                    }
                    Ok(value)
                })
                .await,
            )
        } else if path == "/api/settings" && method == Method::GET {
            encoded(
                tokio::task::spawn_blocking(move || {
                    let mut value = reader(&service).settings()?;
                    value["pdf_candidate"] = json!(true);
                    Ok(value)
                })
                .await,
            )
        } else if method == Method::GET {
            let reader = Arc::new(reader(&service));
            super::library::dispatch(reader, path, &method, &query, req.headers())
                .await
                .unwrap_or_else(|| {
                    failure(SasooError::Unsupported(
                        "Candidate resource is not connected".into(),
                    ))
                })
        } else {
            failure(SasooError::Forbidden(
                "Only PDF upload and explicit extraction are enabled in this candidate".into(),
            ))
        }
    };
    response.headers_mut().insert(
        "x-sasoo-backend-mode",
        HeaderValue::from_static("isolated-pdf-candidate"),
    );
    response
}

fn is_native(service: &PdfCandidate, id: PaperId) -> Result<bool> {
    service.db.blocking_call(move |conn| {
        conn.query_row(
            "SELECT EXISTS(SELECT 1 FROM pdf_candidate_current WHERE paper_id=?1)",
            [id.0],
            |r| r.get(0),
        )
        .map_err(crate::storage::db::db_sql_error)
    })
}

fn encoded(result: std::result::Result<Result<Value>, tokio::task::JoinError>) -> Response {
    match result {
        Ok(Ok(v)) => Json(v).into_response(),
        Ok(Err(e)) => failure(e),
        Err(_) => failure(SasooError::Internal("PDF reader stopped".into())),
    }
}

async fn upload(service: Arc<PdfCandidate>, req: Request) -> Response {
    // Admit before buffering so simultaneous uploads cannot queue unbounded PDF bodies.
    let permit = match service.admission.clone().try_acquire_owned() {
        Ok(p) => p,
        Err(_) => {
            return failure(SasooError::StorageBusy(
                "A PDF producer is still running".into(),
            ));
        }
    };
    let id = match operation_id(&req) {
        Ok(id) => id,
        Err(e) => return failure(e),
    };
    let cancel = CancellationToken::new();
    let operation = match service.register(id, cancel.clone()) {
        Ok(op) => op,
        Err(e) => return failure(e),
    };
    let _guard = cancel.clone().drop_guard();
    let mut multipart = match Multipart::from_request(req, &()).await {
        Ok(m) => m,
        Err(e) => return e.into_response(),
    };
    let mut file = None;
    loop {
        let field = match multipart.next_field().await {
            Ok(Some(f)) => f,
            Ok(None) => break,
            Err(e) => return e.into_response(),
        };
        if field.name() != Some("file") || file.is_some() {
            return (
                StatusCode::BAD_REQUEST,
                Json(json!({"detail":"Exactly one PDF file field is required"})),
            )
                .into_response();
        }
        let Some(name) = field.file_name().map(str::to_owned) else {
            return failure(SasooError::InvalidInput("PDF filename is missing".into()));
        };
        if let Err(e) = crate::pdf::import::safe_filename(&name) {
            return (
                StatusCode::BAD_REQUEST,
                Json(json!({"detail":e.to_string()})),
            )
                .into_response();
        }
        let mut field = field;
        let mut bytes = Vec::new();
        loop {
            match field.chunk().await {
                Ok(Some(chunk)) => {
                    if bytes.len().saturating_add(chunk.len()) > MAX_PDF_BYTES {
                        return (
                            StatusCode::PAYLOAD_TOO_LARGE,
                            Json(json!({"detail":"PDF files must not exceed 100 MB."})),
                        )
                            .into_response();
                    }
                    bytes.extend_from_slice(&chunk);
                }
                Ok(None) => break,
                Err(e) => return e.into_response(),
            }
        }
        if !crate::pdf::artifacts::valid_pdf_header(&bytes) {
            return (
                StatusCode::BAD_REQUEST,
                Json(json!({"detail":"The uploaded file is not a valid PDF."})),
            )
                .into_response();
        }
        file = Some((name, bytes));
    }
    let Some((name, bytes)) = file else {
        return failure(SasooError::InvalidInput(
            "PDF file field is required".into(),
        ));
    };
    encoded(
        tokio::task::spawn_blocking(move || {
            let _permit = permit;
            let _operation = operation;
            service.import_pdf(&name, &bytes, &cancel)
        })
        .await,
    )
}

async fn paper_route(
    service: Arc<PdfCandidate>,
    id: PaperId,
    resource: Option<&str>,
    method: Method,
    req: Request,
) -> Response {
    if resource == Some("pdf") && method == Method::GET {
        let headers = req.headers().clone();
        let resolved = tokio::task::spawn_blocking(move || {
            service
                .assets()
                .resolve_legacy_snapshot_asset(super::files::AssetRequest::Pdf { paper_id: id })
        })
        .await;
        return match resolved {
            Ok(Ok(asset)) => super::files::serve_asset(asset, method, headers)
                .await
                .unwrap_or_else(failure),
            Ok(Err(e)) => failure(e),
            Err(_) => failure(SasooError::Internal("PDF asset reader stopped".into())),
        };
    }
    if resource == Some("extraction") && method == Method::POST {
        let operation = match operation_id(&req) {
            Ok(id) => id,
            Err(e) => return failure(e),
        };
        return match produce(service, operation, move |s, c| s.refresh(id, &c)).await {
            Ok(v) => Json(v).into_response(),
            Err(e) => failure(e),
        };
    }
    if resource == Some("selection-context") && method == Method::POST {
        let bytes = match axum::body::to_bytes(req.into_body(), 16384).await {
            Ok(b) => b,
            Err(_) => {
                return failure(SasooError::InvalidInput(
                    "Selection request exceeds 16 KiB".into(),
                ));
            }
        };
        let selection: Selection = match serde_json::from_slice(&bytes) {
            Ok(s) => s,
            Err(_) => {
                return failure(SasooError::InvalidInput(
                    "Invalid selected passage or physical page range".into(),
                ));
            }
        };
        return encoded(tokio::task::spawn_blocking(move || {
            let (receipt,document)=service.load(id,None)?;
            let pages=page_text(&document);
            if selection.page==0 || selection.end_page<selection.page || selection.end_page>pages.len() {return Err(SasooError::InvalidInput("Selection pages must be physical 1-based pages in this PDF".into()));}
            let mut context=match_selection(&pages[selection.page-1..selection.end_page],selection)?;
            if context.status=="matched" {
                context.source=Some(format!("native extraction {} (not independently confirmed)",receipt.version));
                context.reason="저장된 native 추출 본문에서 유일하게 일치했어. 원본 페이지의 독립 검증은 아직 없어.".into();
            }
            Ok(json!({"context":context,"extraction_version":receipt.version,"source_sha256":receipt.source_sha256,"page_evidence":"page_unverified","independent_page_verification":false}))
        }).await);
    }
    if method != Method::GET {
        return failure(SasooError::Forbidden(
            "This candidate operation is read-only".into(),
        ));
    }
    let params = match query_params(req.uri().query().unwrap_or("")) {
        Ok(p) => p,
        Err(e) => return failure(e),
    };
    let resource = resource.map(str::to_owned);
    encoded(tokio::task::spawn_blocking(move || {
        match resource.as_deref() {
            None=>if is_native(&service,id)? {service.paper(id)}else{reader(&service).paper(id)},
            Some("extraction")=>{
                let historical=params.get("version").cloned();
                let history=historical.is_some();
                let (receipt,document)=service.load(id,historical)?;
                Ok(json!({"receipt":receipt,"document":document,"historical":history,"is_current":!history}))
            },
            Some("search")=>{
                let question=params.get("q").filter(|q|!q.trim().is_empty() && q.chars().count()<=2000).ok_or_else(||SasooError::InvalidInput("Search q requires 1 to 2000 characters".into()))?;
                let (receipt,artifact)=service.load(id,None)?;
                let document=Document{parser_version:format!("{}:{}",receipt.options.profile,receipt.version),full_text:full_text(&page_text(&artifact))};
                let results=search(&document,question,8);
                Ok(json!({"results":results,"extraction_version":receipt.version,"source_sha256":receipt.source_sha256,"page_evidence":"page_unverified","independent_page_verification":false}))
            },
            _=>Err(SasooError::Unsupported("Candidate PDF resource is not connected".into()))
        }
    }).await)
}

fn operation_id(req: &Request) -> Result<uuid::Uuid> {
    match req.headers().get("x-sasoo-pdf-operation-id") {
        None => Ok(uuid::Uuid::new_v4()),
        Some(value) => uuid::Uuid::parse_str(value.to_str().unwrap_or(""))
            .map_err(|_| SasooError::InvalidInput("Invalid PDF operation ID".into())),
    }
}

fn query_params(raw: &str) -> Result<std::collections::BTreeMap<String, String>> {
    raw.split('&')
        .filter(|p| !p.is_empty())
        .map(|part| {
            let (k, v) = part.split_once('=').unwrap_or((part, ""));
            let decode = |s: &str| {
                percent_encoding::percent_decode_str(&s.replace('+', " "))
                    .decode_utf8()
                    .map(|v| v.into_owned())
                    .map_err(|_| SasooError::InvalidInput("Query must use valid UTF-8".into()))
            };
            Ok((decode(k)?, decode(v)?))
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn cancelled_consumer_keeps_producer_permit_and_cannot_publish() {
        let root = tempfile::tempdir().unwrap();
        std::fs::create_dir(root.path().join("library")).unwrap();
        std::fs::write(
            root.path().join(".sasoo-rust-isolated-fixture"),
            "synthetic-only\n",
        )
        .unwrap();
        std::fs::write(
            root.path().join(".sasoo-rust-pdf-candidate"),
            crate::pdf::import::CANDIDATE_MARKER,
        )
        .unwrap();
        let conn = rusqlite::Connection::open(root.path().join("sasoo.db")).unwrap();
        conn.execute_batch(include_str!("../../tests/fixtures/legacy/schema.sql"))
            .unwrap();
        drop(conn);
        let service = Arc::new(PdfCandidate::open(root.path()).unwrap());
        let worker = service.clone();
        let (started, ready) = tokio::sync::oneshot::channel();
        let (release, blocked) = std::sync::mpsc::channel();
        let (done, finished) = tokio::sync::oneshot::channel();
        let id = uuid::Uuid::new_v4();
        let consumer = tokio::spawn(async move {
            produce(worker, id, move |s, token| {
                started.send(()).unwrap();
                blocked.recv().unwrap();
                let result = s.import_pdf("cancel.pdf", b"%PDF-1.7\n", &token);
                done.send(matches!(result, Err(SasooError::Incomplete(_))))
                    .unwrap();
                result
            })
            .await
        });
        ready.await.unwrap();
        assert!(!service.cancel(uuid::Uuid::new_v4()).unwrap());
        assert!(service.cancel(id).unwrap());
        consumer.abort();
        let _ = consumer.await;
        assert_eq!(service.admission.available_permits(), 0);
        assert!(matches!(
            produce(service.clone(), uuid::Uuid::new_v4(), |_, _| Ok(())).await,
            Err(SasooError::StorageBusy(_))
        ));
        release.send(()).unwrap();
        assert!(finished.await.unwrap());
        let _permit = service.admission.acquire().await.unwrap();
        assert!(!service.cancel(id).unwrap());
        let count: i64 = service
            .db
            .call(|c| {
                c.query_row("SELECT COUNT(*) FROM pdf_candidate_versions", [], |r| {
                    r.get(0)
                })
                .map_err(crate::storage::db::db_sql_error)
            })
            .await
            .unwrap();
        assert_eq!(count, 0);
    }
}
