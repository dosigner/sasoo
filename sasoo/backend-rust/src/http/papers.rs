use std::collections::BTreeMap;

use rusqlite::{OptionalExtension, TransactionBehavior, params_from_iter};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

use crate::{
    error::{Result, SasooError},
    storage::{
        db::{Db, DbAccess, db_sql_error},
        legacy::row_json,
    },
    types::PaperId,
};

pub fn validate_isolated_root(root: &std::path::Path) -> Result<std::path::PathBuf> {
    if !root.is_absolute() || !root.is_dir() {
        return Err(SasooError::InvalidInput(
            "An existing absolute isolated root is required".into(),
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
    Ok(root)
}

#[derive(Clone, Debug, Deserialize)]
#[serde(default)]
pub struct PaperQuery {
    pub page: u64,
    pub page_size: i64,
    pub status: Option<String>,
    pub domain: Option<String>,
    pub search: Option<String>,
    pub sort_by: String,
    pub sort_order: String,
}

impl Default for PaperQuery {
    fn default() -> Self {
        Self {
            page: 1,
            page_size: 20,
            status: None,
            domain: None,
            search: None,
            sort_by: "created_at".into(),
            sort_order: "desc".into(),
        }
    }
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct PaperPatch {
    pub title: Option<String>,
    pub authors: Option<String>,
    pub year: Option<i64>,
    pub journal: Option<String>,
    pub doi: Option<String>,
    pub domain: Option<String>,
    pub agent_used: Option<String>,
    pub tags: Option<String>,
    pub notes: Option<String>,
    pub status: Option<String>,
    pub explanation_level: Option<String>,
    pub analysis_focus: Option<Map<String, Value>>,
}

#[derive(Clone, Debug, Serialize)]
pub struct PaperDto {
    #[serde(flatten)]
    pub fields: Map<String, Value>,
}

#[derive(Clone, Debug, Serialize)]
pub struct PaperListDto {
    pub papers: Vec<PaperDto>,
    pub completed_count: Option<i64>,
    pub total: i64,
    pub page: u64,
    pub page_size: i64,
}

/// Observations come from the artifact/title adapters, never from row defaults.
#[derive(Clone, Debug)]
pub struct PaperObservation {
    pub resolved_title: Option<String>,
    pub text_ready: bool,
    pub visual_ready: bool,
    pub visual_state: String,
    pub visual_error: Option<String>,
    pub openalex_field: Option<String>,
}

/// This isolated milestone does not schedule refresh or run analysis.
#[derive(Clone)]
pub struct PaperService {
    pub db: Db,
    pub observations: BTreeMap<i64, PaperObservation>,
    pub domain_agents: BTreeMap<String, String>,
    pub filesystem_root: Option<std::path::PathBuf>,
}

pub(crate) fn ensure_idle(conn: &rusqlite::Connection) -> Result<()> {
    let analyzing: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM papers WHERE status = 'analyzing'",
            [],
            |row| row.get(0),
        )
        .map_err(db_sql_error)?;
    if analyzing > 0 {
        return Err(SasooError::Unsupported(
            "Active papers require the W10 runtime integration".into(),
        ));
    }
    let has_runs: bool = conn.query_row("SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type='table' AND name='analysis_runs')", [], |row| row.get(0)).map_err(db_sql_error)?;
    if has_runs {
        let active: i64 = conn.query_row("SELECT COUNT(*) FROM analysis_runs WHERE status NOT IN ('completed','error','cancelled')", [], |row| row.get(0)).map_err(db_sql_error)?;
        if active > 0 {
            return Err(SasooError::Unsupported(
                "Queued or active executions require the W10 runtime integration".into(),
            ));
        }
    }
    let has_runtime: bool = conn.query_row("SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type='table' AND name='runtime_executions')", [], |row| row.get(0)).map_err(db_sql_error)?;
    if has_runtime {
        let executions: i64 = conn
            .query_row("SELECT COUNT(*) FROM runtime_executions", [], |row| {
                row.get(0)
            })
            .map_err(db_sql_error)?;
        // This milestone has no execution-state adapter yet.
        if executions > 0 {
            return Err(SasooError::Unsupported(
                "Runtime execution history requires the W10 state adapter".into(),
            ));
        }
    }
    Ok(())
}

fn paper_not_found(id: PaperId) -> SasooError {
    SasooError::NotFound(format!("Paper {} not found.", id.0))
}

fn load_row(conn: &rusqlite::Connection, id: PaperId) -> Result<Map<String, Value>> {
    conn.query_row("SELECT * FROM papers WHERE id = ?1", [id.0], row_json)
        .optional()
        .map_err(db_sql_error)?
        .ok_or_else(|| paper_not_found(id))
}

impl PaperService {
    pub fn open_isolated(root: &std::path::Path) -> Result<Self> {
        let paths = super::paper_files::isolated_paths(root)?;
        let db = crate::storage::db::open_db(&paths, DbAccess::ReadOnly)?;
        Ok(Self {
            db,
            observations: BTreeMap::new(),
            domain_agents: BTreeMap::new(),
            filesystem_root: Some(paths.library_root),
        })
    }
    pub(crate) fn present(&self, row: Map<String, Value>) -> Result<PaperDto> {
        let id = row
            .get("id")
            .and_then(Value::as_i64)
            .ok_or_else(|| SasooError::Incomplete("Paper row has no integer ID".into()))?;
        let observed = self
            .filesystem_root
            .as_ref()
            .map(|root| super::paper_files::observe(root, &row))
            .transpose()?;
        let observation = observed.as_ref().or_else(||self.observations.get(&id)).ok_or_else(|| SasooError::Unsupported(format!("Paper {id} requires an observed artifact/title state; refresh adapter is not connected")))?;
        if !["ready", "running", "error", "partial"].contains(&observation.visual_state.as_str()) {
            return Err(SasooError::InvalidInput(
                "Unknown visual_state observation".into(),
            ));
        }
        let mut fields = Map::new();
        for name in [
            "id",
            "title",
            "authors",
            "year",
            "journal",
            "doi",
            "domain",
            "agent_used",
            "folder_name",
            "tags",
            "status",
            "analyzed_at",
            "notes",
            "created_at",
        ] {
            let default = match name {
                "domain" => Value::from("optics"),
                "agent_used" => Value::from("photon"),
                "status" => Value::from("pending"),
                _ => Value::Null,
            };
            fields.insert(name.into(), row.get(name).cloned().unwrap_or(default));
        }
        if let Some(title) = &observation.resolved_title {
            fields.insert("title".into(), Value::from(title.clone()));
        }
        for name in [
            "id",
            "title",
            "folder_name",
            "domain",
            "agent_used",
            "status",
        ] {
            if fields[name].is_null() {
                return Err(SasooError::Incomplete(format!(
                    "Paper row has null required field {name}"
                )));
            }
        }
        fields.insert("text_ready".into(), observation.text_ready.into());
        fields.insert("visual_ready".into(), observation.visual_ready.into());
        fields.insert(
            "visual_state".into(),
            observation.visual_state.clone().into(),
        );
        fields.insert(
            "visual_error".into(),
            observation
                .visual_error
                .clone()
                .map(Value::from)
                .unwrap_or(Value::Null),
        );
        fields.insert(
            "artifacts_ready".into(),
            (observation.text_ready && observation.visual_ready).into(),
        );
        for name in [
            "explanation_level",
            "analysis_focus",
            "pdf_file_uri",
            "pdf_file_expires_at",
            "openalex_subfield_id",
        ] {
            fields.insert(name.into(), row.get(name).cloned().unwrap_or(Value::Null));
        }
        fields.insert(
            "openalex_field".into(),
            observation
                .openalex_field
                .clone()
                .map(Value::from)
                .unwrap_or(Value::Null),
        );
        Ok(PaperDto { fields })
    }

    pub fn list_papers(&self, query: PaperQuery) -> Result<PaperListDto> {
        let (rows, total, completed_count, page, page_size) = self.list_rows(query)?;
        let papers = rows
            .into_iter()
            .map(|row| self.present(row))
            .collect::<Result<_>>()?;
        Ok(PaperListDto {
            papers,
            completed_count: Some(completed_count),
            total,
            page,
            page_size,
        })
    }

    pub(crate) fn list_rows(&self, query: PaperQuery) -> Result<PaperPageRows> {
        self.db.blocking_call(move |conn| {
            let tx = conn.transaction().map_err(db_sql_error)?;
            ensure_idle(&tx)?;
            let page = read_page(&tx, query)?;
            tx.commit().map_err(db_sql_error)?;
            Ok(page)
        })
    }

    pub fn get_paper(&self, id: PaperId) -> Result<PaperDto> {
        let row = self.db.blocking_call(move |conn| {
            let row = load_row(conn, id)?;
            ensure_idle(conn)?;
            Ok(row)
        })?;
        self.present(row)
    }

    pub fn patch_paper(&self, id: PaperId, patch: PaperPatch) -> Result<PaperDto> {
        if self.db.access() != DbAccess::ServerOwner {
            return Err(SasooError::Forbidden(
                "Only the server owner may update papers".into(),
            ));
        }
        if let Some(domain) = &patch.domain {
            if !["optics", "bio", "ai_ml", "ee", "general"].contains(&domain.as_str()) {
                return Err(SasooError::InvalidInput("Invalid domain".into()));
            }
        }
        if let Some(agent) = &patch.agent_used {
            if !["photon", "cell", "neural", "circuit"].contains(&agent.as_str()) {
                return Err(SasooError::InvalidInput("Invalid agent_used".into()));
            }
        }
        if let Some(status) = &patch.status {
            if !["pending", "analyzing", "completed", "error"].contains(&status.as_str()) {
                return Err(SasooError::InvalidInput("Invalid paper status".into()));
            }
            if status == "analyzing" {
                return Err(SasooError::Unsupported(
                    "Starting analysis requires W10".into(),
                ));
            }
        }
        let default_agent = if patch.agent_used.is_none() {
            patch
                .domain
                .as_ref()
                .map(|domain| {
                    self.domain_agents.get(domain).cloned().ok_or_else(|| {
                        SasooError::Unsupported(
                            "The frozen agent catalog has no domain mapping".into(),
                        )
                    })
                })
                .transpose()?
        } else {
            None
        };
        let Value::Object(mut fields) =
            serde_json::to_value(patch).map_err(|error| SasooError::Internal(error.to_string()))?
        else {
            unreachable!()
        };
        fields.retain(|_, value| !value.is_null());
        if fields.is_empty() {
            return Err(SasooError::InvalidInput("No fields to update.".into()));
        }
        if let Some(agent) = default_agent {
            fields.insert("agent_used".into(), agent.into());
        }
        let observation = self.observations.get(&id.0).cloned();
        let row = self.db.blocking_call(move |conn| {
            let tx = conn
                .transaction_with_behavior(TransactionBehavior::Immediate)
                .map_err(db_sql_error)?;
            load_row(&tx, id)?;
            ensure_idle(&tx)?;
            if observation.is_none() {
                return Err(SasooError::Unsupported(
                    "Artifact/title observations are required before updating a paper".into(),
                ));
            }
            let mut assignments = Vec::new();
            let mut values = Vec::<rusqlite::types::Value>::new();
            for (name, value) in fields {
                assignments.push(format!("{name} = ?"));
                values.push(match value {
                    Value::String(text) => text.into(),
                    Value::Number(number) => number
                        .as_i64()
                        .ok_or_else(|| SasooError::InvalidInput("year must be an integer".into()))?
                        .into(),
                    Value::Object(_) if name == "analysis_focus" => python_json(&value)?.into(),
                    _ => {
                        return Err(SasooError::InvalidInput(format!(
                            "Invalid patch field {name}"
                        )));
                    }
                });
            }
            values.push(id.0.into());
            let changed = tx
                .execute(
                    &format!("UPDATE papers SET {} WHERE id = ?", assignments.join(", ")),
                    params_from_iter(values.iter()),
                )
                .map_err(db_sql_error)?;
            if changed != 1 {
                return Err(paper_not_found(id));
            }
            let row = load_row(&tx, id)?;
            tx.commit().map_err(db_sql_error)?;
            Ok(row)
        })?;
        self.present(row)
    }
}

fn python_json(value: &Value) -> Result<String> {
    match value {
        Value::Array(values) => Ok(format!(
            "[{}]",
            values
                .iter()
                .map(python_json)
                .collect::<Result<Vec<_>>>()?
                .join(", ")
        )),
        Value::Object(fields) => {
            let entries = fields
                .iter()
                .map(|(key, value)| {
                    Ok(format!(
                        "{}: {}",
                        serde_json::to_string(key)
                            .map_err(|error| SasooError::Internal(error.to_string()))?,
                        python_json(value)?
                    ))
                })
                .collect::<Result<Vec<_>>>()?;
            Ok(format!("{{{}}}", entries.join(", ")))
        }
        _ => serde_json::to_string(value).map_err(|error| SasooError::Internal(error.to_string())),
    }
}

pub(crate) type PaperPageRows = (Vec<Map<String, Value>>, i64, i64, u64, i64);

// Legacy preview is explicitly injected and remains disconnected from main.
pub(crate) fn legacy_snapshot_rows(db: &Db, query: PaperQuery) -> Result<PaperPageRows> {
    db.blocking_call(move |conn| {
        let tx = conn.transaction().map_err(db_sql_error)?;
        let rows = read_page(&tx, query)?;
        tx.commit().map_err(db_sql_error)?;
        Ok(rows)
    })
}
fn read_page(conn: &rusqlite::Connection, query: PaperQuery) -> Result<PaperPageRows> {
    if query.page < 1 || !(1..=100).contains(&query.page_size) {
        return Err(SasooError::InvalidInput(
            "page must be at least 1; page_size must be between 1 and 100".into(),
        ));
    }
    let offset = (query.page - 1)
        .checked_mul(query.page_size as u64)
        .and_then(|offset| i64::try_from(offset).ok())
        .ok_or_else(|| SasooError::InvalidInput("Pagination offset is too large".into()))?;
    let page = query.page;
    let page_size = query.page_size;
    let sort_by = if [
        "created_at",
        "title",
        "year",
        "status",
        "domain",
        "analyzed_at",
    ]
    .contains(&query.sort_by.as_str())
    {
        query.sort_by.as_str()
    } else {
        "created_at"
    };
    let sort_order = if query.sort_order.eq_ignore_ascii_case("asc") {
        "asc"
    } else {
        "desc"
    };
    let mut clauses = Vec::new();
    let mut values = Vec::<rusqlite::types::Value>::new();
    for (column, filter) in [("status", query.status), ("domain", query.domain)] {
        if let Some(value) = filter.filter(|text| !text.is_empty()) {
            clauses.push(format!("{column} = ?"));
            values.push(value.into());
        }
    }
    if let Some(search) = query.search.filter(|text| !text.is_empty()) {
        clauses.push("(title LIKE ? OR authors LIKE ? OR tags LIKE ? OR notes LIKE ?)".into());
        values.extend((0..4).map(|_| rusqlite::types::Value::from(format!("%{search}%"))));
    }
    let where_clause = if clauses.is_empty() {
        String::new()
    } else {
        format!("WHERE {}", clauses.join(" AND "))
    };
    let count_sql = format!(
        "SELECT COUNT(*), COALESCE(SUM(status = 'completed'), 0) FROM papers {where_clause}"
    );
    let page_sql = format!(
        "SELECT * FROM papers {where_clause} ORDER BY {sort_by} {sort_order} LIMIT ? OFFSET ?"
    );
    let (total, completed): (i64, i64) = conn
        .query_row(&count_sql, params_from_iter(values.iter()), |row| {
            Ok((row.get(0)?, row.get(1)?))
        })
        .map_err(db_sql_error)?;
    values.push(page_size.into());
    values.push(offset.into());
    let rows = {
        let mut stmt = conn.prepare(&page_sql).map_err(db_sql_error)?;
        stmt.query_map(params_from_iter(values.iter()), row_json)
            .map_err(db_sql_error)?
            .collect::<rusqlite::Result<Vec<_>>>()
            .map_err(db_sql_error)?
    };

    let mut rows = rows;
    if !rows.is_empty() {
        let ids = rows
            .iter()
            .map(|r| {
                r["id"]
                    .as_i64()
                    .ok_or_else(|| SasooError::Incomplete("Paper ID is missing".into()))
            })
            .collect::<Result<Vec<_>>>()?;
        let placeholders = vec!["?"; ids.len()].join(",");
        let mut counts = BTreeMap::<i64, i64>::new();
        for table in ["figures", "tables"] {
            let sql = format!(
                "SELECT paper_id,COUNT(*) FROM {table} WHERE paper_id IN ({placeholders}) AND COALESCE(extraction_status,'resolved')!='rejected' GROUP BY paper_id"
            );
            let mut stmt = conn.prepare(&sql).map_err(db_sql_error)?;
            for row in stmt
                .query_map(params_from_iter(ids.iter()), |r| {
                    Ok((r.get::<_, i64>(0)?, r.get::<_, i64>(1)?))
                })
                .map_err(db_sql_error)?
            {
                let (id, count) = row.map_err(db_sql_error)?;
                *counts.entry(id).or_default() += count;
            }
        }
        for row in &mut rows {
            row.insert(
                "__visual_row_count".into(),
                counts
                    .get(&row["id"].as_i64().unwrap())
                    .copied()
                    .unwrap_or(0)
                    .into(),
            );
        }
    }
    Ok((rows, total, completed, page, page_size))
}

pub(crate) async fn list_http(
    service: std::sync::Arc<PaperService>,
    raw: &str,
) -> axum::response::Response {
    use axum::{Json, http::StatusCode, response::IntoResponse};
    if service.db.access() != DbAccess::ReadOnly || service.filesystem_root.is_none() {
        return (StatusCode::NOT_IMPLEMENTED,Json(serde_json::json!({"detail":"Paper HTTP requires a prepared read-only filesystem service"}))).into_response();
    }
    let mut params = BTreeMap::<String, String>::new();
    for pair in raw.split('&').filter(|p| !p.is_empty()) {
        let (key, value) = pair.split_once('=').unwrap_or((pair, ""));
        let decode = |s: &str| {
            percent_encoding::percent_decode_str(&s.replace('+', " "))
                .decode_utf8_lossy()
                .into_owned()
        };
        params.insert(decode(key), decode(value));
    }
    let mut query = PaperQuery::default();
    let mut errors = vec![];
    let mut overflow = false;
    let integer = regex::Regex::new(r"^[+-]?[0-9](?:_?[0-9])*(?:\.0+)?$")
        .expect("Static query integer pattern");
    for (name, max) in [("page", None), ("page_size", Some(100))] {
        let Some(raw) = params.get(name) else {
            continue;
        };
        let text = raw.trim();
        let mut error = None;
        if !integer.is_match(text) {
            error = Some(
                serde_json::json!({"type":"int_parsing","loc":["query",name],"msg":"Input should be a valid integer, unable to parse string as an integer","input":raw}),
            );
        } else {
            let whole = text.split('.').next().unwrap().replace('_', "");
            let digits = whole.trim_start_matches(['+', '-']).trim_start_matches('0');
            if digits.len() > 4300 {
                error = Some(
                    serde_json::json!({"type":"int_parsing_size","loc":["query",name],"msg":"Unable to parse input string as an integer, exceeded maximum size","input":raw}),
                );
            } else if whole.starts_with('-') || digits.is_empty() {
                error = Some(
                    serde_json::json!({"type":"greater_than_equal","loc":["query",name],"msg":"Input should be greater than or equal to 1","input":raw,"ctx":{"ge":1}}),
                );
            } else if max.is_some()
                && (digits.len() > 3 || digits.parse::<u64>().is_ok_and(|n| n > 100))
            {
                error = Some(
                    serde_json::json!({"type":"less_than_equal","loc":["query",name],"msg":"Input should be less than or equal to 100","input":raw,"ctx":{"le":100}}),
                );
            } else {
                match digits.parse::<u64>() {
                    Ok(value) => {
                        if name == "page" {
                            query.page = value;
                        } else {
                            query.page_size = value as i64;
                        }
                    }
                    Err(_) => overflow = true,
                }
            }
        }
        if let Some(error) = error {
            errors.push(error);
        }
    }
    if !errors.is_empty() {
        return (
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(serde_json::json!({"detail":errors})),
        )
            .into_response();
    }
    if overflow
        || (query.page - 1)
            .checked_mul(query.page_size as u64)
            .is_none_or(|offset| offset > i64::MAX as u64)
    {
        return (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response();
    }
    query.status = params.remove("status");
    query.domain = params.remove("domain");
    query.search = params.remove("search");
    if let Some(value) = params.remove("sort_by") {
        query.sort_by = value;
    }
    if let Some(value) = params.remove("sort_order") {
        query.sort_order = value;
    }
    match tokio::task::spawn_blocking(move || service.list_papers(query)).await {
        Ok(Ok(page)) => Json(page).into_response(),
        Ok(Err(error)) => {
            let (status, message) = match error {
                SasooError::Unsupported(message) => (StatusCode::NOT_IMPLEMENTED, message),
                SasooError::Forbidden(message) => (StatusCode::FORBIDDEN, message),
                SasooError::StorageBusy(message) => (StatusCode::SERVICE_UNAVAILABLE, message),
                SasooError::InvalidInput(message) => (StatusCode::UNPROCESSABLE_ENTITY, message),
                _ => {
                    return (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error")
                        .into_response();
                }
            };
            (status, Json(serde_json::json!({"detail":message}))).into_response()
        }
        Err(_) => (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response(),
    }
}
