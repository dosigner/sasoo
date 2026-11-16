//! Read-only HTTP integration over a deliberately isolated legacy library.
use std::{
    collections::BTreeMap,
    path::{Component, Path, PathBuf},
};

use percent_encoding::{NON_ALPHANUMERIC, utf8_percent_encode};
use rusqlite::OptionalExtension;
use serde_json::{Map, Value, json};

use super::{
    files::{AssetAccess, AssetService},
    papers::{PaperDto, PaperListDto, PaperObservation, PaperQuery, PaperService},
    settings::{SecretDisplay, mask_api_key, settings_from_rows},
};
use crate::{
    error::{Result, SasooError},
    pdf::legacy_context::{load_legacy_document, read_json},
    storage::{
        db::{Db, DbAccess, db_sql_error, open_db},
        discussion,
        legacy::{read_paper, row_json},
        paths::RuntimePaths,
        settings::read_settings,
    },
    types::PaperId,
};

#[derive(Clone)]
pub struct LibraryReader {
    pub(crate) db: Db,
    pub(crate) root: PathBuf,
    pub assets: AssetService,
}

impl LibraryReader {
    pub fn open(root: &Path) -> Result<Self> {
        if !root.is_absolute() || !root.is_dir() {
            return Err(SasooError::InvalidInput(
                "Isolated root must be an existing absolute directory".into(),
            ));
        }
        let root = root.canonicalize()?;
        let marker = root.join(".sasoo-rust-isolated-fixture");
        if marker.symlink_metadata()?.file_type().is_symlink()
            || std::fs::read_to_string(marker)? != "synthetic-only\n"
        {
            return Err(SasooError::Forbidden(
                "A synthetic-only isolated root marker is required".into(),
            ));
        }
        let library = root.join("library");
        if !library.canonicalize()?.starts_with(&root) {
            return Err(SasooError::Forbidden(
                "Isolated library must remain inside its root".into(),
            ));
        }
        let paths = RuntimePaths {
            app_data_root: root.clone(),
            db_path: root.join("sasoo.db"),
            config_path: root.join("config.json"),
            default_library_root: library.clone(),
            library_root: library.clone(),
            library_search_roots: vec![library.clone()],
            owner_lock_path: root.join("sasoo.db.runtime-owner.lock"),
        };
        let db = open_db(&paths, DbAccess::ReadOnly)?;
        let assets = AssetService {
            db: db.clone(),
            search_roots: vec![library],
            access: AssetAccess::default(),
        };
        Ok(Self { db, root, assets })
    }

    pub(crate) fn paper_row(&self, id: PaperId) -> Result<Map<String, Value>> {
        read_paper(&self.db, id)?
            .map(|p| p.fields)
            .ok_or_else(|| SasooError::NotFound(format!("Paper {} not found.", id.0)))
    }

    pub(crate) fn paper_dir(&self, row: &Map<String, Value>) -> Result<PathBuf> {
        let folder = row
            .get("folder_name")
            .and_then(Value::as_str)
            .ok_or_else(|| SasooError::Incomplete("Paper folder is missing".into()))?;
        let path = Path::new(folder);
        if folder.contains(['\\', '\0'])
            || path.components().count() != 1
            || !matches!(path.components().next(), Some(Component::Normal(name)) if !name.to_string_lossy().starts_with('.'))
        {
            return Err(SasooError::InvalidInput("Invalid paper folder".into()));
        }
        let library = self.root.join("library").canonicalize()?;
        let dir = library.join(folder);
        if dir.exists() && !dir.canonicalize()?.starts_with(&library) {
            return Err(SasooError::Forbidden(
                "Paper folder leaves the isolated library".into(),
            ));
        }
        Ok(dir)
    }

    fn service(&self) -> PaperService {
        PaperService {
            db: self.db.clone(),
            observations: BTreeMap::new(),
            domain_agents: BTreeMap::new(),
            filesystem_root: None,
        }
    }

    fn observation(&self, row: &Map<String, Value>) -> Result<PaperObservation> {
        let dir = self.paper_dir(row)?;
        let extraction = load_legacy_document(&dir)?;
        let manifest_path = dir.join(".odl_manifest.json");
        let manifest = if manifest_path.exists() {
            read_json(&dir, &manifest_path).ok()
        } else {
            None
        };
        // Saved visuals remain accessible; parser freshness is not a new quality verdict.
        let visual_ready = extraction.state == "usable"
            && extraction.extraction_file.as_deref() == Some(".odl_manifest.json")
            && manifest
                .as_ref()
                .is_some_and(|m| m["visual_artifacts_ready"] == true)
            && manifest.as_ref().is_some_and(|m| {
                ["figures", "tables"].iter().all(|key| {
                    m[*key].as_array().is_some_and(|items| {
                        items.iter().all(|item| {
                            ["file_path", "csv_path", "html_path"].iter().all(|field| {
                                item[*field].as_str().is_none_or(|p| {
                                    let path = dir.join(p);
                                    path.canonicalize().is_ok_and(|p| {
                                        p.starts_with(dir.canonicalize().unwrap_or_default())
                                            && p.is_file()
                                    })
                                })
                            })
                        })
                    })
                })
            });
        Ok(PaperObservation {
            resolved_title: None,
            text_ready: extraction.document.is_some(),
            visual_ready,
            visual_state: if visual_ready { "ready" } else { "partial" }.into(),
            visual_error: if visual_ready {
                None
            } else {
                Some(
                    "읽기 전용 모드로 저장된 그림과 표를 보여줘요. 새 추출과 동기화는 실행하지 않아요.".into(),
                )
            },
            openalex_field: None,
        })
    }

    fn present(&self, row: Map<String, Value>) -> Result<PaperDto> {
        let id = row["id"]
            .as_i64()
            .ok_or_else(|| SasooError::Incomplete("Paper ID is missing".into()))?;
        let mut service = self.service();
        service.observations.insert(id, self.observation(&row)?);
        let mut dto = service.present(row)?;
        dto.fields.insert("read_only".into(), json!(true));
        if dto.fields["status"] == "analyzing" {
            dto.fields.insert("saved_status".into(), json!("analyzing"));
            dto.fields.insert("status".into(), json!("pending"));
        }
        Ok(dto)
    }

    pub fn papers(&self, query: PaperQuery) -> Result<Value> {
        let (rows, total, completed, page, page_size) =
            super::papers::legacy_snapshot_rows(&self.db, query)?;
        let papers = rows
            .into_iter()
            .map(|row| self.present(row))
            .collect::<Result<Vec<_>>>()?;
        Ok(serde_json::to_value(PaperListDto {
            papers,
            total,
            page,
            page_size,
            completed_count: Some(completed),
        })
        .map_err(|_| SasooError::Internal("Cannot encode papers".into()))?)
    }

    pub fn paper(&self, id: PaperId) -> Result<Value> {
        serde_json::to_value(self.present(self.paper_row(id)?)?)
            .map_err(|_| SasooError::Internal("Cannot encode paper".into()))
    }

    pub fn settings(&self) -> Result<Value> {
        let rows = read_settings(&self.db)?;
        let mut secrets = SecretDisplay::default();
        for (name, masked, unreadable) in [
            (
                "openai_api_key",
                &mut secrets.openai_masked,
                &mut secrets.openai_unreadable,
            ),
            (
                "gemini_api_key",
                &mut secrets.gemini_masked,
                &mut secrets.gemini_unreadable,
            ),
        ] {
            let stored = rows.get(name).map(String::as_str).unwrap_or("");
            *unreadable = stored.starts_with("enc:v1:");
            if !stored.is_empty() && !stored.starts_with("enc:v1:") {
                *masked = mask_api_key(stored);
            }
        }
        // No key-store lookup, fallback key-file read, or decryption in preview mode.
        let library = self.root.join("library").to_string_lossy().into_owned();
        let dto = settings_from_rows(&rows, &library, secrets)?;
        let mut value = serde_json::to_value(dto)
            .map_err(|_| SasooError::Internal("Cannot encode settings".into()))?;
        value["credentials_access"] = json!("disabled_read_only");
        Ok(value)
    }

    fn rows(
        &self,
        id: PaperId,
        table: &'static str,
        order: &'static str,
    ) -> Result<Vec<Map<String, Value>>> {
        self.db.blocking_call(move |conn| {
            let exists = conn
                .query_row(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?1",
                    [table],
                    |_| Ok(()),
                )
                .optional()
                .map_err(db_sql_error)?
                .is_some();
            if !exists {
                return Ok(vec![]);
            }
            let mut stmt = conn
                .prepare(&format!(
                    "SELECT * FROM \"{table}\" WHERE paper_id=?1 ORDER BY {order}"
                ))
                .map_err(db_sql_error)?;
            stmt.query_map([id.0], row_json)
                .map_err(db_sql_error)?
                .collect::<rusqlite::Result<Vec<_>>>()
                .map_err(db_sql_error)
        })
    }

    fn results(&self, id: PaperId) -> Result<BTreeMap<String, Value>> {
        let mut results = BTreeMap::new();
        for mut row in self.rows(id, "analysis_results", "created_at DESC, id DESC")? {
            let phase = row["phase"].as_str().unwrap_or("").to_owned();
            if results.contains_key(&phase) {
                continue;
            }
            let parsed = row
                .get("result")
                .and_then(Value::as_str)
                .and_then(|s| serde_json::from_str::<Value>(s).ok());
            row.insert("parsed_result".into(), parsed.unwrap_or(Value::Null));
            results.insert(phase, Value::Object(row));
        }
        Ok(results)
    }

    fn asset_url(&self, value: &Value) -> Result<Value> {
        let Some(path) = value.as_str().filter(|s| !s.is_empty()) else {
            return Ok(Value::Null);
        };
        let relative = if let Some(relative) = path.strip_prefix("/static/library/") {
            percent_encoding::percent_decode_str(relative)
                .decode_utf8()
                .map_err(|_| SasooError::InvalidInput("Invalid asset URL".into()))?
                .into_owned()
        } else if Path::new(path).is_absolute() {
            let library = self.root.join("library");
            let mut roots = vec![library];
            let settings = read_settings(&self.db)?;
            for key in [
                "library_path",
                "library_path_darwin",
                "library_path_win32",
                "library_path_linux",
            ] {
                if let Some(root) = settings.get(key).filter(|s| !s.trim().is_empty()) {
                    roots.push(PathBuf::from(root));
                }
            }
            let Some(relative) = roots
                .iter()
                .find_map(|root| Path::new(path).strip_prefix(root).ok())
            else {
                return Ok(Value::Null);
            };
            relative.to_string_lossy().into_owned()
        } else {
            path.into()
        };
        let path = Path::new(&relative);
        if relative.contains(['\\', '\0']) || path.components().any(|p| !matches!(p, Component::Normal(name) if !name.to_string_lossy().starts_with('.'))) {
            return Ok(Value::Null);
        }
        let encoded = relative
            .split('/')
            .map(|part| utf8_percent_encode(part, NON_ALPHANUMERIC).to_string())
            .collect::<Vec<_>>()
            .join("/");
        Ok(Value::String(format!("/static/library/{encoded}")))
    }

    pub fn analysis(&self, id: PaperId, resource: &str) -> Result<Value> {
        let paper = self.paper_row(id)?;
        if resource == "discussion" {
            let messages = discussion::list_messages(&self.db, id)?;
            let reset = messages
                .iter()
                .rfind(|m| m.kind == "reset")
                .map_or(0, |m| m.id);
            let latest = messages.iter().rfind(|m| {
                m.id > reset && m.kind == "sasoo" && m.status == "complete" && m.tokens_in.is_some()
            });
            let tokens = latest.and_then(|m| m.tokens_in);
            let mut sources = latest
                .and_then(|m| m.context.as_ref())
                .and_then(|c| c["sources"].as_array())
                .cloned()
                .unwrap_or_default();
            let chars: f64 = sources
                .iter()
                .filter_map(|s| s["chars"].as_u64())
                .map(|n| n as f64)
                .sum::<f64>()
                .max(1.0);
            for source in &mut sources {
                if let Some(object) = source.as_object_mut() {
                    let count = object.get("chars").and_then(Value::as_u64).unwrap_or(0);
                    object.insert(
                        "estimated_tokens".into(),
                        tokens
                            .map(|n| {
                                json!((n as f64 * count as f64 / chars).round_ties_even() as i64)
                            })
                            .unwrap_or(Value::Null),
                    );
                }
            }
            return Ok(
                json!({"messages":messages,"context":{"budget":260000,"context_tokens":tokens,"sources":sources}}),
            );
        }
        if matches!(resource, "figures" | "tables") {
            let mut rows = self.rows(
                id,
                if resource == "figures" {
                    "figures"
                } else {
                    "tables"
                },
                if resource == "figures" {
                    "COALESCE(page_number,999999), figure_num, id"
                } else {
                    "COALESCE(page_number,999999), table_num, id"
                },
            )?;
            for row in &mut rows {
                let bbox = row
                    .remove("bbox_json")
                    .and_then(|v| {
                        v.as_str()
                            .and_then(|s| serde_json::from_str::<Value>(s).ok())
                    })
                    .filter(|v| {
                        v.as_array()
                            .is_some_and(|a| a.len() == 4 && a.iter().all(Value::is_number))
                    })
                    .unwrap_or(Value::Null);
                row.insert("bbox".into(), bbox);
                for name in ["file_path", "csv_path", "html_path"] {
                    if let Some(value) = row.get(name).cloned() {
                        row.insert(name.into(), self.asset_url(&value)?);
                    }
                }
                for name in ["is_composite", "repair_attempted", "review_required"] {
                    if let Some(value) = row.get(name) {
                        row.insert(
                            name.into(),
                            json!(value == true || value.as_i64().is_some_and(|n| n != 0)),
                        );
                    }
                }
            }
            let observation = self.observation(&paper)?;
            let mut response = json!({"total":rows.len(),"visual_state":observation.visual_state,"visual_error":observation.visual_error,"artifacts_ready":observation.text_ready && observation.visual_ready,"artifacts_error":observation.visual_error});
            response[resource] = serde_json::to_value(rows)
                .map_err(|_| SasooError::Internal("Cannot encode artifacts".into()))?;
            return Ok(response);
        }
        let results = self.results(id)?;
        if matches!(resource, "results" | "status") {
            let checks: Vec<Value> = ["screening", "citation", "visual", "recipe", "deep_dive", "synthesis", "visualization", "review_map"].into_iter().map(|phase| {
                let r = results.get(phase);
                json!({"stage":phase,"label":phase,"status":if r.is_some(){"partial"}else{"missing"},"result_id":r.and_then(|r| r.get("id")),"required":[],"reason":if r.is_some(){"저장된 결과임. Rust에서 완료 여부를 재검증하지 않았음."}else{"저장된 결과가 없음."}})
            }).collect();
            let phases: Vec<Value> = ["screening", "citation", "visual", "recipe", "deep_dive"].into_iter().map(|phase| {
                let r = results.get(phase);
                json!({"phase":phase,"status":"pending","started_at":null,"stale_model":null,"model_used":r.and_then(|r| r.get("model_used")),"tokens_in":r.and_then(|r| r.get("tokens_in")),"tokens_out":r.and_then(|r| r.get("tokens_out")),"cost_usd":r.and_then(|r| r.get("cost_usd")),"completed_at":r.and_then(|r| r.get("created_at")),"error_message":if r.is_some(){Some("Saved result has not been revalidated by the Rust completion checker")}else{None}})
            }).collect();
            let status = json!({"paper_id":id.0,"overall_status":"pending","saved_status":paper.get("status"),"phases":phases,"completion_checks":checks,"progress_pct":0,"current_phase":null,"total_cost_usd":null,"total_tokens_in":null,"total_tokens_out":null,"validation_state":"legacy_unverified","read_only":true});
            if resource == "status" {
                return Ok(status);
            }
            let mut response = json!({"paper_id":id.0,"status":status});
            for phase in [
                "screening",
                "citation",
                "visual",
                "recipe",
                "deep_dive",
                "review_map",
            ] {
                response[phase] = results
                    .get(phase)
                    .map(|r| r["parsed_result"].clone())
                    .unwrap_or(Value::Null);
            }
            return Ok(response);
        }
        if resource == "recipe" {
            let row = results
                .get("recipe")
                .filter(|r| r["parsed_result"].is_object())
                .ok_or_else(|| SasooError::NotFound("No saved recipe found".into()))?;
            return Ok(
                json!({"paper_id":id.0,"recipe":row["parsed_result"],"model_used":row["model_used"],"created_at":row["created_at"],"evidence":null,"reproduction_check":{"status":"unverified","items":[]}}),
            );
        }
        if resource == "synthesis" {
            let row = results
                .get("synthesis")
                .filter(|r| r["parsed_result"].is_object())
                .ok_or_else(|| SasooError::NotFound("No saved synthesis found".into()))?;
            let mut data = row["parsed_result"].clone();
            data["paper_id"] = json!(id.0);
            for key in ["model_used", "cost_usd", "created_at"] {
                data[key] = row[key].clone();
            }
            return Ok(data);
        }
        if resource == "visualizations" {
            let row = results.get("visualization");
            let data = row.map(|r| &r["parsed_result"]);
            let mut items = data
                .and_then(|d| d["items"].as_array())
                .cloned()
                .unwrap_or_default();
            for item in &mut items {
                if let Some(path) = item.get("image_path").cloned() {
                    item["image_path"] = self.asset_url(&path)?;
                }
            }
            return Ok(
                json!({"paper_id":id.0,"total_count":data.and_then(|d| d.get("total_count")).cloned().unwrap_or(json!(items.len())),"items":items,"run_id":row.and_then(|r| r.get("id")),"run_token":data.and_then(|d| d.get("run_token")),"model_used":data.and_then(|d| d.get("model_used")).cloned().unwrap_or(json!("")),"planned_at":data.and_then(|d| d.get("planned_at"))}),
            );
        }
        if resource == "experiment-plan" {
            let mut row = self
                .rows(id, "experiment_plans", "created_at DESC, id DESC")?
                .into_iter()
                .next()
                .ok_or_else(|| SasooError::NotFound("No saved experiment plan found".into()))?;
            let content = row
                .get("content")
                .and_then(Value::as_str)
                .and_then(|s| serde_json::from_str::<Value>(s).ok())
                .unwrap_or_else(|| json!({"raw":row.get("content")}));
            row.insert("content".into(), content);
            return Ok(Value::Object(row));
        }
        Err(SasooError::Unsupported(
            "This read-only resource is not connected".into(),
        ))
    }
}

pub(crate) fn paper_query(raw: &str) -> Result<PaperQuery> {
    let mut query = PaperQuery::default();
    for pair in raw.split('&').filter(|p| !p.is_empty()) {
        let (key, value) = pair.split_once('=').unwrap_or((pair, ""));
        let decode = |s: &str| {
            percent_encoding::percent_decode_str(&s.replace('+', " "))
                .decode_utf8()
                .map(|v| v.into_owned())
                .map_err(|_| SasooError::InvalidInput("Query must use valid UTF-8".into()))
        };
        let key = decode(key)?;
        let value = decode(value)?;
        match key.as_str() {
            "page" | "page_size" => {
                let n = value.trim().parse::<i64>().map_err(|_| {
                    SasooError::InvalidInput("Pagination must use integer values".into())
                })?;
                if key == "page" {
                    query.page = n
                        .try_into()
                        .map_err(|_| SasooError::InvalidInput("page must be at least 1".into()))?;
                } else {
                    query.page_size = n;
                }
            }
            "status" => query.status = Some(value),
            "domain" => query.domain = Some(value),
            "search" => query.search = Some(value),
            "sort_by" => query.sort_by = value,
            "sort_order" => query.sort_order = value,
            _ => {}
        }
    }
    Ok(query)
}

fn error_response(error: SasooError) -> axum::response::Response {
    use axum::{Json, http::StatusCode, response::IntoResponse};
    let (status, message) = match error {
        SasooError::NotFound(_) => (StatusCode::NOT_FOUND, "Saved resource not found".to_owned()),
        SasooError::InvalidInput(message) => (StatusCode::UNPROCESSABLE_ENTITY, message),
        SasooError::Forbidden(_) => (
            StatusCode::FORBIDDEN,
            "Resource is outside the permitted library".into(),
        ),
        SasooError::StorageBusy(_) => (
            StatusCode::SERVICE_UNAVAILABLE,
            "Library is busy; retry the read".into(),
        ),
        SasooError::Unsupported(message) => (StatusCode::NOT_IMPLEMENTED, message),
        _ => (
            StatusCode::INTERNAL_SERVER_ERROR,
            "Unable to read saved library data".into(),
        ),
    };
    (status, Json(json!({"detail":message}))).into_response()
}

pub(crate) async fn dispatch(
    reader: std::sync::Arc<LibraryReader>,
    path: &str,
    method: &axum::http::Method,
    query: &str,
    headers: &axum::http::HeaderMap,
) -> Option<axum::response::Response> {
    use axum::{
        Json,
        http::{HeaderValue, Method, StatusCode},
        response::IntoResponse,
    };
    if !(path.starts_with("/api/") || path.starts_with("/static/library/")) {
        return None;
    }
    if method != Method::GET {
        return Some((StatusCode::FORBIDDEN, Json(json!({"detail":"읽기 전용 모드에서는 분석, 질문, 업로드와 수정을 실행할 수 없어."}))).into_response());
    }
    let parts: Vec<_> = path.trim_start_matches('/').split('/').collect();
    let id = if matches!(parts.get(1), Some(&"papers" | &"analysis"))
        && parts.len() >= 3
        && parts[2] != "upload"
    {
        match parts[2].parse::<i64>().ok().filter(|id| *id > 0) {
            Some(id) => Some(PaperId(id)),
            None => {
                return Some(error_response(SasooError::InvalidInput(
                    "Paper ID must be a positive integer".into(),
                )));
            }
        }
    } else {
        None
    };
    let asset = if let Some(relative) = path.strip_prefix("/static/library/") {
        Some(super::files::AssetRequest::Library {
            decoded_path: relative.into(),
        })
    } else if parts.len() == 4 && parts[1] == "papers" && parts[3] == "pdf" {
        Some(super::files::AssetRequest::Pdf { paper_id: id? })
    } else {
        None
    };
    if let Some(asset) = asset {
        let resolved =
            tokio::task::spawn_blocking(move || reader.assets.resolve_legacy_snapshot_asset(asset))
                .await;
        return Some(match resolved {
            Ok(Ok(asset)) => super::files::serve_asset(asset, method.clone(), headers.clone())
                .await
                .unwrap_or_else(error_response),
            Ok(Err(error)) => error_response(error),
            Err(_) => error_response(SasooError::Internal("Asset reader stopped".into())),
        });
    }
    let path = path.to_owned();
    let query = query.to_owned();
    let response = tokio::task::spawn_blocking(move || {
        if path == "/api/papers" {
            return reader.papers(paper_query(&query)?);
        }
        if path == "/api/settings" {
            return reader.settings();
        }
        let parts: Vec<_> = path.trim_start_matches('/').split('/').collect();
        if parts.len() == 3 && parts[1] == "papers" {
            return reader.paper(id.expect("validated paper ID"));
        }
        if parts.len() == 4 && parts[1] == "analysis" {
            return reader.analysis(id.expect("validated analysis paper ID"), parts[3]);
        }
        Err(SasooError::Unsupported(
            "This read-only resource is not connected".into(),
        ))
    })
    .await;
    let mut response = match response {
        Ok(Ok(value)) => Json(value).into_response(),
        Ok(Err(error)) => error_response(error),
        Err(_) => error_response(SasooError::Internal("Library reader stopped".into())),
    };
    response.headers_mut().insert(
        "x-sasoo-backend-mode",
        HeaderValue::from_static("read-only"),
    );
    Some(response)
}
