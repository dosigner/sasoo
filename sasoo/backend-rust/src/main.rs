use sasoo_backend::{
    cli::{Mode, parse_cli},
    error::{Result, SasooError},
    http::{ApiState, build_router},
};
use std::{env, ffi::OsString, path::PathBuf, sync::Arc};

fn main() {
    #[cfg(feature = "pdf-xberg-native")]
    if env::args_os().skip(1).collect::<Vec<_>>() == [OsString::from("--pdf-operation")] {
        if let Err(error) = sasoo_backend::pdf::process::child_main() {
            eprintln!("{error}");
            std::process::exit(1);
        }
        return;
    }
    tokio::runtime::Runtime::new()
        .unwrap()
        .block_on(async_main());
}

async fn async_main() {
    if let Err(error) = run().await {
        eprintln!("{error}");
        std::process::exit(1);
    }
}
async fn run() -> Result<()> {
    let args: Vec<OsString> = env::args_os().skip(1).collect();
    match parse_cli(&args)? {
        Mode::Worker { .. } => Err(SasooError::Unsupported(
            "Worker execution is not connected before the runtime acceptance gate".into(),
        )),
        Mode::Server { host, port } => {
            if !host.is_loopback() {
                return Err(SasooError::Forbidden(
                    "Isolated library preview must bind to loopback".into(),
                ));
            }
            let root=env::var_os("SASOO_RUST_ISOLATED_ROOT").map(PathBuf::from).ok_or_else(||SasooError::Unsupported("This milestone requires SASOO_RUST_ISOLATED_ROOT; production selection is disabled".into()))?;
            let root = sasoo_backend::http::papers::validate_isolated_root(&root)?;
            let (shutdown_tx, mut shutdown_rx) = tokio::sync::watch::channel(false);
            #[cfg(feature = "pdf-xberg-native")]
            let pdf_candidate = match env::var("SASOO_RUST_PDF_CANDIDATE").ok().as_deref() {
                Some("1") => {
                    if env::var("SASOO_API_TOKEN")
                        .ok()
                        .is_none_or(|t| t.is_empty())
                    {
                        return Err(SasooError::Forbidden(
                            "PDF candidate requires SASOO_API_TOKEN".into(),
                        ));
                    }
                    Some(Arc::new(sasoo_backend::pdf::import::PdfCandidate::open(
                        &root,
                    )?.with_execution(sasoo_backend::pdf::process::Policy::new(
                        env::current_exe()?,
                        std::time::Duration::from_millis(env::var("SASOO_RUST_PDF_TIMEOUT_MS").ok().and_then(|v|v.parse::<u64>().ok()).filter(|v| *v > 0).ok_or_else(||SasooError::InvalidInput("Candidate requires explicit positive SASOO_RUST_PDF_TIMEOUT_MS (milliseconds, not an operating budget)".into()))?)
                    ))))
                }
                None | Some("0") => None,
                _ => {
                    return Err(SasooError::InvalidInput(
                        "SASOO_RUST_PDF_CANDIDATE must be 0 or 1".into(),
                    ));
                }
            };
            #[cfg(not(feature = "pdf-xberg-native"))]
            if env::var("SASOO_RUST_PDF_CANDIDATE").is_ok_and(|s| s != "0") {
                return Err(SasooError::Unsupported(
                    "PDF candidate requires --features pdf-xberg-native".into(),
                ));
            }
            #[cfg(feature = "pdf-xberg-native")]
            let candidate_enabled = pdf_candidate.is_some();
            #[cfg(not(feature = "pdf-xberg-native"))]
            let candidate_enabled = false;
            let paper_service = if !candidate_enabled && root.join("sasoo.db").is_file() {
                Some(Arc::new(
                    sasoo_backend::http::papers::PaperService::open_isolated(&root)?,
                ))
            } else {
                None
            };
            let app = build_router(ApiState {
                api_token: env::var("SASOO_API_TOKEN").ok(),
                shutdown_token: env::var("SASOO_SHUTDOWN_TOKEN").ok(),
                production: env::var("SASOO_ENV").is_ok_and(|s| s == "production"),
                library_path: root.join("library"),
                shutdown_signal: Some(shutdown_tx),
                library: None,
                paper_service,
                #[cfg(feature = "pdf-xberg-native")]
                pdf_candidate,
            });
            let listener = tokio::net::TcpListener::bind((host, port)).await?;
            axum::serve(listener, app)
                .with_graceful_shutdown(async move {
                    let _ = shutdown_rx.changed().await;
                })
                .await
                .map_err(SasooError::Io)
        }
    }
}
