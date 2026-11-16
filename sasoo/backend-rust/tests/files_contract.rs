use axum::http::{HeaderMap, HeaderValue, Method};
use http_body_util::BodyExt;
use rusqlite::Connection;
use sasoo_backend::{
    error::SasooError,
    http::files::{AssetAccess, AssetRequest, AssetService, serve_asset},
    storage::{
        db::{DbAccess, open_db},
        paths::RuntimePaths,
    },
    types::PaperId,
};
use std::{
    collections::BTreeMap,
    fs::{self, File, FileTimes},
    time::{Duration, UNIX_EPOCH},
};
use tempfile::TempDir;

const PDF: &[u8] = b"%PDF-1.4\nsynthetic-contract-bytes\n%%EOF\n";
fn fixture() -> (TempDir, AssetService) {
    let dir = TempDir::new().unwrap();
    let root = dir.path().to_path_buf();
    let current = root.join("current");
    let fallback = root.join("fallback");
    fs::create_dir_all(current.join("one")).unwrap();
    fs::create_dir_all(fallback.join("old")).unwrap();
    let pdf = current.join("one/한글 %.pdf");
    fs::write(&pdf, PDF).unwrap();
    File::options()
        .write(true)
        .open(&pdf)
        .unwrap()
        .set_times(FileTimes::new().set_modified(UNIX_EPOCH + Duration::from_secs(1_700_000_000)))
        .unwrap();
    fs::write(fallback.join("old/existing.txt"), b"legacy").unwrap();
    let paths = RuntimePaths {
        app_data_root: root.clone(),
        db_path: root.join("sasoo.db"),
        config_path: root.join("config.json"),
        default_library_root: fallback.clone(),
        library_root: current.clone(),
        library_search_roots: vec![current.clone(), fallback.clone()],
        owner_lock_path: root.join("owner.lock"),
    };
    let conn = Connection::open(&paths.db_path).unwrap();
    conn.execute_batch(include_str!("fixtures/legacy/schema.sql"))
        .unwrap();
    conn.execute_batch(
        "INSERT INTO papers(id,title,folder_name) VALUES(1,'one','one'),(2,'old','old');",
    )
    .unwrap();
    let db = open_db(&paths, DbAccess::ServerOwner).unwrap();
    (
        dir,
        AssetService {
            db,
            search_roots: paths.library_search_roots,
            access: AssetAccess::default(),
        },
    )
}

fn assert_observed_headers(reply: &axum::http::Response<axum::body::Body>, id: &str) {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../contract-fixtures/rust-backend-v2/http.json"
    ))
    .unwrap();
    let expected = &fixture["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|case| case["id"] == id)
        .unwrap()["response"];
    assert_eq!(
        reply.status().as_u16(),
        expected["status"].as_u64().unwrap() as u16
    );
    let actual: BTreeMap<_, _> = reply
        .headers()
        .iter()
        .map(|(key, value)| (key.as_str().to_owned(), value.to_str().unwrap().to_owned()))
        .collect();
    let expected: BTreeMap<_, _> = expected["headers"]
        .as_object()
        .unwrap()
        .iter()
        .map(|(key, value)| (key.clone(), value.as_str().unwrap().to_owned()))
        .collect();
    assert_eq!(actual, expected, "captured Python headers for {id}");
}

#[tokio::test]
async fn pdf_unicode_headers_and_range_match_observed_python_file_response() {
    let (_dir, service) = fixture();
    let asset = service
        .resolve_asset(AssetRequest::Pdf {
            paper_id: PaperId(1),
        })
        .unwrap();
    let reply = serve_asset(asset, Method::GET, HeaderMap::new())
        .await
        .unwrap();
    assert_observed_headers(&reply, "pdf_unicode");
    assert_eq!(reply.status(), 200);
    assert_eq!(
        reply.headers()["content-disposition"],
        "inline; filename=\"?? %.pdf\"; filename*=UTF-8''%ED%95%9C%EA%B8%80%20%25.pdf"
    );
    assert_eq!(reply.headers()["content-type"], "application/pdf");
    assert_eq!(reply.headers()["accept-ranges"], "bytes");
    assert_eq!(
        reply.headers()["etag"],
        "\"80030412b82d9893d432e28d84e38be9\""
    );
    assert_eq!(
        reply.headers()["last-modified"],
        "Tue, 14 Nov 2023 22:13:20 GMT"
    );
    assert_eq!(reply.into_body().collect().await.unwrap().to_bytes(), PDF);
    let mut headers = HeaderMap::new();
    headers.insert("range", HeaderValue::from_static("bytes=0-4"));
    let reply = serve_asset(
        service
            .resolve_asset(AssetRequest::Pdf {
                paper_id: PaperId(1),
            })
            .unwrap(),
        Method::GET,
        headers,
    )
    .await
    .unwrap();
    assert_observed_headers(&reply, "pdf_range");
    assert_eq!(reply.status(), 206);
    assert_eq!(reply.headers()["content-range"], "bytes 0-4/40");
    assert_eq!(reply.headers()["content-length"], "5");
    assert_eq!(
        reply.into_body().collect().await.unwrap().to_bytes(),
        b"%PDF-".as_slice()
    );
}

#[tokio::test]
async fn unsatisfiable_range_invalid_if_range_and_pdf_head_preserve_observed_statuses() {
    let (_dir, service) = fixture();
    let mut headers = HeaderMap::new();
    headers.insert("range", HeaderValue::from_static("bytes=999999-"));
    let reply = serve_asset(
        service
            .resolve_asset(AssetRequest::Pdf {
                paper_id: PaperId(1),
            })
            .unwrap(),
        Method::GET,
        headers,
    )
    .await
    .unwrap();
    assert_observed_headers(&reply, "pdf_unsatisfiable_range");
    assert_eq!(reply.status(), 416);
    assert_eq!(reply.headers()["content-range"], "bytes */40");
    assert!(
        reply
            .into_body()
            .collect()
            .await
            .unwrap()
            .to_bytes()
            .is_empty()
    );
    let mut headers = HeaderMap::new();
    headers.insert("range", HeaderValue::from_static("bytes=0-4"));
    headers.insert("if-range", HeaderValue::from_static("not-the-etag"));
    let reply = serve_asset(
        service
            .resolve_asset(AssetRequest::Pdf {
                paper_id: PaperId(1),
            })
            .unwrap(),
        Method::GET,
        headers,
    )
    .await
    .unwrap();
    assert_eq!(reply.status(), 200);
    assert_eq!(reply.into_body().collect().await.unwrap().to_bytes(), PDF);
    let reply = serve_asset(
        service
            .resolve_asset(AssetRequest::Pdf {
                paper_id: PaperId(1),
            })
            .unwrap(),
        Method::HEAD,
        HeaderMap::new(),
    )
    .await
    .unwrap();
    assert_observed_headers(&reply, "pdf_head");
    assert_eq!(reply.status(), 405);
    assert_eq!(reply.headers()["allow"], "GET");
}

#[test]
fn assets_require_database_folder_and_stay_within_configured_or_legacy_roots() {
    let (dir, service) = fixture();
    assert!(matches!(
        service.resolve_asset(AssetRequest::Library {
            decoded_path: "../outside".into()
        }),
        Err(SasooError::InvalidInput(_))
    ));
    assert!(matches!(
        service.resolve_asset(AssetRequest::Library {
            decoded_path: "/etc/passwd".into()
        }),
        Err(SasooError::InvalidInput(_))
    ));
    fs::create_dir_all(dir.path().join("current/unlisted")).unwrap();
    fs::write(dir.path().join("current/unlisted/private.txt"), b"private").unwrap();
    assert!(matches!(
        service.resolve_asset(AssetRequest::Library {
            decoded_path: "unlisted/private.txt".into()
        }),
        Err(SasooError::NotFound(_))
    ));
    let asset = service
        .resolve_asset(AssetRequest::Library {
            decoded_path: "old/existing.txt".into(),
        })
        .unwrap();
    assert_eq!(fs::read(asset.path).unwrap(), b"legacy");
    assert!(!dir.path().join("current/old").exists());
    assert!(
        matches!(service.resolve_asset(AssetRequest::Pdf{paper_id:PaperId(999)}),Err(SasooError::NotFound(message)) if message=="Paper 999 not found.")
    );
}

#[cfg(unix)]
#[test]
fn resolved_symlink_cannot_escape_a_library_root() {
    let (dir, service) = fixture();
    fs::write(dir.path().join("outside.txt"), b"outside").unwrap();
    std::os::unix::fs::symlink(
        dir.path().join("outside.txt"),
        dir.path().join("current/one/link.txt"),
    )
    .unwrap();
    assert!(matches!(
        service.resolve_asset(AssetRequest::Library {
            decoded_path: "one/link.txt".into()
        }),
        Err(SasooError::NotFound(_))
    ));
}

#[test]
fn private_and_unreferenced_artifacts_are_not_exposed_by_legacy_static_route() {
    let (dir, mut service) = fixture();
    let managed = dir.path().join("current/one/versions");
    let private = dir.path().join("current/one/staging");
    fs::create_dir_all(&managed).unwrap();
    fs::create_dir_all(&private).unwrap();
    fs::write(managed.join("unreferenced.html"), b"paid-unreferenced").unwrap();
    fs::write(managed.join("published.html"), b"published").unwrap();
    fs::write(private.join("partial.html"), b"partial").unwrap();
    service.access = AssetAccess {
        private_roots: vec![private],
        managed_roots: vec![managed.clone()],
        published_paths: BTreeMap::from([(managed.join("published.html"), "version-one".into())]),
    };
    assert!(matches!(
        service.resolve_asset(AssetRequest::Library {
            decoded_path: "one/staging/partial.html".into()
        }),
        Err(SasooError::NotFound(_))
    ));
    assert!(matches!(
        service.resolve_asset(AssetRequest::Library {
            decoded_path: "one/versions/unreferenced.html".into()
        }),
        Err(SasooError::NotFound(_))
    ));
    let published = service
        .resolve_asset(AssetRequest::Library {
            decoded_path: "one/versions/published.html".into(),
        })
        .unwrap();
    assert_eq!(
        published.publication_version.as_deref(),
        Some("version-one")
    );
    assert_eq!(
        fs::read(managed.join("unreferenced.html")).unwrap(),
        b"paid-unreferenced"
    );
}

#[tokio::test]
async fn static_unicode_headers_match_the_captured_python_charset_and_etag() {
    let (dir, service) = fixture();
    let path = dir.path().join("current/one/한글 %.txt");
    let content = "synthetic 한글 % bytes\n";
    fs::write(&path, content.as_bytes()).unwrap();
    File::options()
        .write(true)
        .open(path)
        .unwrap()
        .set_times(FileTimes::new().set_modified(UNIX_EPOCH + Duration::from_secs(1_700_000_000)))
        .unwrap();
    let asset = service
        .resolve_asset(AssetRequest::Library {
            decoded_path: "one/한글 %.txt".into(),
        })
        .unwrap();
    let reply = serve_asset(asset, Method::GET, HeaderMap::new())
        .await
        .unwrap();
    assert_observed_headers(&reply, "static_unicode");
    assert_eq!(
        reply.into_body().collect().await.unwrap().to_bytes(),
        content.as_bytes()
    );
}

#[cfg(unix)]
#[test]
fn a_pdf_folder_symlink_is_rejected_before_enumerating_an_outside_directory() {
    let (dir, service) = fixture();
    let outside = dir.path().join("outside-pdf");
    fs::create_dir(&outside).unwrap();
    fs::write(outside.join("secret.pdf"), PDF).unwrap();
    std::os::unix::fs::symlink(&outside, dir.path().join("current/linked")).unwrap();
    service
        .db
        .blocking_call(|conn| {
            conn.execute(
                "INSERT INTO papers(id,title,folder_name) VALUES(3,'linked','linked')",
                [],
            )
            .map_err(sasoo_backend::storage::db::db_sql_error)?;
            Ok(())
        })
        .unwrap();
    assert!(matches!(
        service.resolve_asset(AssetRequest::Pdf {
            paper_id: PaperId(3)
        }),
        Err(SasooError::NotFound(_))
    ));
}
