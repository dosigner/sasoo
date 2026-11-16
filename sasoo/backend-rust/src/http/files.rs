use std::{
    collections::BTreeMap,
    fs::{self, File},
    path::{Component, Path, PathBuf},
    time::SystemTime,
};

use axum::{
    body::Body,
    http::{HeaderMap, HeaderValue, Method, Response, StatusCode},
};
use percent_encoding::{AsciiSet, CONTROLS, utf8_percent_encode};
use rusqlite::OptionalExtension;
use tokio::io::{AsyncReadExt, AsyncSeekExt};
use tokio_util::io::ReaderStream;

use super::papers::ensure_idle;
use crate::{
    error::{Result, SasooError},
    storage::db::{Db, db_sql_error},
    types::PaperId,
};

const FILENAME_ESCAPE: &AsciiSet = &CONTROLS
    .add(b' ')
    .add(b'!')
    .add(b'"')
    .add(b'#')
    .add(b'$')
    .add(b'%')
    .add(b'&')
    .add(b'\'')
    .add(b'(')
    .add(b')')
    .add(b'*')
    .add(b'+')
    .add(b',')
    .add(b'/')
    .add(b':')
    .add(b';')
    .add(b'<')
    .add(b'=')
    .add(b'>')
    .add(b'?')
    .add(b'@')
    .add(b'[')
    .add(b'\\')
    .add(b']')
    .add(b'^')
    .add(b'`')
    .add(b'{')
    .add(b'|')
    .add(b'}')
    .add(127);

#[derive(Default, Clone, Debug)]
pub struct AssetAccess {
    pub private_roots: Vec<PathBuf>,
    pub managed_roots: Vec<PathBuf>,
    pub published_paths: BTreeMap<PathBuf, String>,
}

#[derive(Clone, Debug)]
pub enum AssetRequest {
    Library { decoded_path: String },
    Pdf { paper_id: PaperId },
}

pub struct AuthorizedAsset {
    pub path: PathBuf,
    pub length: u64,
    pub mime: String,
    pub headers: BTreeMap<String, String>,
    pub publication_version: Option<String>,
    file: File,
    modified: SystemTime,
}

#[derive(Clone)]
pub struct AssetService {
    pub db: Db,
    pub search_roots: Vec<PathBuf>,
    pub access: AssetAccess,
}

fn asset_not_found() -> SasooError {
    SasooError::NotFound("Library asset not found".into())
}

fn canonical_or_original(path: &Path) -> PathBuf {
    path.canonicalize().unwrap_or_else(|_| path.to_path_buf())
}

impl AssetService {
    fn authorize_candidate(
        &self,
        root: &Path,
        candidate: &Path,
        pdf: bool,
    ) -> Result<Option<AuthorizedAsset>> {
        let root = match root.canonicalize() {
            Ok(path) => path,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(error.into()),
        };
        let path = match candidate.canonicalize() {
            Ok(path) => path,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(error.into()),
        };
        if !path.starts_with(&root) || !path.is_file() {
            return Ok(None);
        }
        if path.components().any(|part| matches!(part, Component::Normal(value) if value == ".sasoo-runtime" || value == ".sasoo-staging")) { return Ok(None); }
        if self
            .access
            .private_roots
            .iter()
            .any(|private| path.starts_with(canonical_or_original(private)))
        {
            return Ok(None);
        }
        let managed = self
            .access
            .managed_roots
            .iter()
            .any(|managed| path.starts_with(canonical_or_original(managed)));
        let publication_version =
            self.access
                .published_paths
                .iter()
                .find_map(|(published, version)| {
                    (canonical_or_original(published) == path).then(|| version.clone())
                });
        if managed && publication_version.is_none() {
            return Ok(None);
        }
        let file = File::open(&path)?;
        let metadata = file.metadata()?;
        if !metadata.is_file() {
            return Ok(None);
        }
        let mut headers = BTreeMap::new();
        let mut mime: String = if pdf {
            "application/pdf".into()
        } else {
            mime_guess::from_path(&path)
                .first_or_octet_stream()
                .essence_str()
                .into()
        };
        if mime.starts_with("text/") {
            mime.push_str("; charset=utf-8");
        }
        if pdf {
            let name = path
                .file_name()
                .and_then(|value| value.to_str())
                .ok_or_else(|| SasooError::InvalidInput("PDF filename is not UTF-8".into()))?;
            let ascii_name: String = name
                .chars()
                .map(|character| if character.is_ascii() { character } else { '?' })
                .collect();
            headers.insert(
                "content-disposition".into(),
                format!(
                    "inline; filename=\"{ascii_name}\"; filename*=UTF-8''{}",
                    utf8_percent_encode(name, FILENAME_ESCAPE)
                ),
            );
        }
        Ok(Some(AuthorizedAsset {
            path,
            length: metadata.len(),
            mime,
            headers,
            publication_version,
            file,
            modified: metadata.modified()?,
        }))
    }

    pub fn resolve_asset(&self, request: AssetRequest) -> Result<AuthorizedAsset> {
        self.db.blocking_call(|conn| ensure_idle(conn))?;
        self.resolve_legacy_snapshot_asset(request)
    }

    pub(crate) fn resolve_legacy_snapshot_asset(
        &self,
        request: AssetRequest,
    ) -> Result<AuthorizedAsset> {
        match request {
            AssetRequest::Library { decoded_path } => {
                let relative = Path::new(&decoded_path);
                if relative.is_absolute()
                    || decoded_path.contains(['\\', '\0'])
                    || relative
                        .components()
                        .any(|part| matches!(part, Component::ParentDir | Component::Prefix(_)))
                    || relative.components().any(|part| matches!(part, Component::Normal(name) if name.to_string_lossy().starts_with('.')))
                {
                    return Err(SasooError::InvalidInput(
                        "Invalid library asset path".into(),
                    ));
                }
                let Some(Component::Normal(folder)) = relative.components().next() else {
                    return Err(asset_not_found());
                };
                let folder = folder
                    .to_str()
                    .ok_or_else(|| SasooError::InvalidInput("Library path is not UTF-8".into()))?
                    .to_owned();
                let exists = self.db.blocking_call(move |conn| {
                    conn.query_row(
                        "SELECT 1 FROM papers WHERE folder_name = ?1",
                        [folder],
                        |_| Ok(()),
                    )
                    .optional()
                    .map(|row| row.is_some())
                    .map_err(db_sql_error)
                })?;
                if !exists {
                    return Err(asset_not_found());
                }
                for root in &self.search_roots {
                    if let Some(asset) =
                        self.authorize_candidate(root, &root.join(relative), false)?
                    {
                        return Ok(asset);
                    }
                }
                Err(asset_not_found())
            }
            AssetRequest::Pdf { paper_id } => {
                let folder: String = self.db.blocking_call(move |conn| {
                    let folder = conn
                        .query_row(
                            "SELECT folder_name FROM papers WHERE id = ?1",
                            [paper_id.0],
                            |row| row.get::<_, String>(0),
                        )
                        .optional()
                        .map_err(db_sql_error)?
                        .ok_or_else(|| {
                            SasooError::NotFound(format!("Paper {} not found.", paper_id.0))
                        })?;
                    Ok(folder)
                })?;
                let relative = Path::new(&folder);
                if relative.is_absolute()
                    || relative.components().count() != 1
                    || !matches!(relative.components().next(), Some(Component::Normal(_)))
                {
                    return Err(SasooError::InvalidInput("Invalid paper folder path".into()));
                }
                for root in &self.search_roots {
                    let dir = root.join(&folder);
                    if !dir.is_dir() {
                        continue;
                    }
                    let resolved_root = root.canonicalize()?;
                    let resolved_dir = dir.canonicalize()?;
                    if !resolved_dir.starts_with(&resolved_root) {
                        return Err(SasooError::NotFound("PDF path is not a valid file.".into()));
                    }
                    let mut entries = fs::read_dir(&resolved_dir)?
                        .map(|e| e.map(|e| e.path()))
                        .collect::<std::io::Result<Vec<_>>>()?;
                    entries.sort();
                    for path in entries {
                        if path.extension().is_some_and(|extension| extension == "pdf") {
                            return self.authorize_candidate(root, &path, true)?.ok_or_else(|| {
                                SasooError::NotFound("PDF path is not a valid file.".into())
                            });
                        }
                    }
                    return Err(SasooError::NotFound("PDF file not found on disk.".into()));
                }
                let directory = self
                    .search_roots
                    .first()
                    .map(|root| root.join(folder))
                    .unwrap_or_default();
                Err(SasooError::NotFound(format!(
                    "Paper directory not found: {}",
                    directory.display()
                )))
            }
        }
    }
}

fn header(headers: &mut HeaderMap, name: &'static str, value: impl AsRef<str>) -> Result<()> {
    headers.insert(
        name,
        HeaderValue::from_str(value.as_ref())
            .map_err(|_| SasooError::InvalidInput(format!("Invalid {name} header")))?,
    );
    Ok(())
}

fn empty_response(status: StatusCode, headers: HeaderMap) -> Response<Body> {
    let mut response = Response::new(Body::empty());
    *response.status_mut() = status;
    *response.headers_mut() = headers;
    response
}

fn byte_range(value: &str, length: u64) -> Result<Option<(u64, u64)>> {
    let Some(value) = value.strip_prefix("bytes=") else {
        return Err(SasooError::InvalidInput(
            "Only byte ranges are supported".into(),
        ));
    };
    if value.contains(',') {
        return Err(SasooError::Unsupported(
            "Multipart byte-range parity is not captured yet".into(),
        ));
    }
    let Some((start, end)) = value.split_once('-') else {
        return Err(SasooError::InvalidInput("Malformed byte range".into()));
    };
    if length == 0 {
        return Ok(None);
    }
    if start.is_empty() {
        let suffix = end
            .parse::<u64>()
            .map_err(|_| SasooError::InvalidInput("Malformed byte range".into()))?;
        if suffix == 0 {
            return Ok(None);
        }
        return Ok(Some((length.saturating_sub(suffix), length - 1)));
    }
    let start = start
        .parse::<u64>()
        .map_err(|_| SasooError::InvalidInput("Malformed byte range".into()))?;
    let end = if end.is_empty() {
        length - 1
    } else {
        end.parse::<u64>()
            .map_err(|_| SasooError::InvalidInput("Malformed byte range".into()))?
            .min(length - 1)
    };
    Ok((start < length && end >= start).then_some((start, end)))
}

/// Use only after the isolated resolver has checked DB membership and scope.
pub async fn serve_asset(
    asset: AuthorizedAsset,
    method: Method,
    request_headers: HeaderMap,
) -> Result<Response<Body>> {
    if method != Method::GET {
        let mut headers = HeaderMap::new();
        headers.insert("allow", HeaderValue::from_static("GET"));
        headers.insert("content-type", HeaderValue::from_static("application/json"));
        headers.insert("content-length", HeaderValue::from_static("31"));
        let body = if method == Method::HEAD {
            Body::empty()
        } else {
            Body::from("{\"detail\":\"Method Not Allowed\"}")
        };
        let mut response = Response::new(body);
        *response.status_mut() = StatusCode::METHOD_NOT_ALLOWED;
        *response.headers_mut() = headers;
        return Ok(response);
    }
    let modified = asset
        .modified
        .duration_since(SystemTime::UNIX_EPOCH)
        .map_err(|_| {
            SasooError::Unsupported("Pre-epoch file timestamp compatibility is not captured".into())
        })?;
    let seconds = modified.as_secs_f64();
    let mtime = if seconds.fract() == 0.0 {
        format!("{seconds:.1}")
    } else {
        seconds.to_string()
    };
    let etag = format!(
        "\"{:x}\"",
        md5::compute(format!("{mtime}-{}", asset.length))
    );
    let last_modified = httpdate::fmt_http_date(asset.modified);
    let mut headers = HeaderMap::new();
    for (name, value) in &asset.headers {
        headers.insert(
            axum::http::header::HeaderName::from_bytes(name.as_bytes())
                .map_err(|_| SasooError::InvalidInput("Invalid asset header name".into()))?,
            HeaderValue::from_str(value)
                .map_err(|_| SasooError::InvalidInput("Invalid asset header value".into()))?,
        );
    }
    header(&mut headers, "content-type", &asset.mime)?;
    header(&mut headers, "accept-ranges", "bytes")?;
    header(&mut headers, "etag", &etag)?;
    header(&mut headers, "last-modified", &last_modified)?;
    let if_range_matches = request_headers
        .get("if-range")
        .map(|value| {
            value
                .to_str()
                .is_ok_and(|value| value == etag || value == last_modified)
        })
        .unwrap_or(true);
    let range = if if_range_matches {
        request_headers
            .get("range")
            .map(|value| {
                value
                    .to_str()
                    .map_err(|_| SasooError::InvalidInput("Invalid Range header".into()))
                    .and_then(|value| byte_range(value, asset.length))
            })
            .transpose()?
    } else {
        None
    };
    let (status, start, count) = match range {
        None => (StatusCode::OK, 0, asset.length),
        Some(None) => {
            let mut error_headers = HeaderMap::new();
            header(
                &mut error_headers,
                "content-range",
                format!("bytes */{}", asset.length),
            )?;
            header(&mut error_headers, "content-length", "0")?;
            header(
                &mut error_headers,
                "content-type",
                "text/plain; charset=utf-8",
            )?;
            return Ok(empty_response(
                StatusCode::RANGE_NOT_SATISFIABLE,
                error_headers,
            ));
        }
        Some(Some((start, end))) => {
            header(
                &mut headers,
                "content-range",
                format!("bytes {start}-{end}/{}", asset.length),
            )?;
            (StatusCode::PARTIAL_CONTENT, start, end - start + 1)
        }
    };
    header(&mut headers, "content-length", count.to_string())?;
    let mut file = tokio::fs::File::from_std(asset.file);
    if start > 0 {
        file.seek(std::io::SeekFrom::Start(start)).await?;
    }
    let body = Body::from_stream(ReaderStream::new(file.take(count)));
    let mut response = Response::new(body);
    *response.status_mut() = status;
    *response.headers_mut() = headers;
    Ok(response)
}
