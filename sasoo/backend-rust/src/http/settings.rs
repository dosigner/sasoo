//! Legacy settings DTO mapping. Persistence and credential access are injected by the owner.
use crate::error::{Result, SasooError};
use crate::{
    storage::{
        credentials::{CredentialManager, SecretState, SecretUpdate},
        db::Db,
        paths::{Platform, usable_library_path},
    },
    types::{KeyEpoch, ProviderId},
};
use secrecy::{ExposeSecret, SecretString};
use serde::{Deserialize, Serialize};
use std::{collections::BTreeMap, fmt, sync::Arc};

pub struct SettingsService {
    pub db: Db,
    pub credentials: Arc<CredentialManager>,
    pub library_setting_key: String,
    pub default_library: String,
    pub home: std::path::PathBuf,
    pub platform: Platform,
}

impl SettingsService {
    pub fn get_settings(&self) -> Result<SettingsDto> {
        let rows=self.db.blocking_call(|connection| {
            let mut query=connection.prepare("SELECT key,value FROM settings ORDER BY key").map_err(crate::storage::db::db_sql_error)?;
            let mut rows=BTreeMap::new();
            let values=query.query_map([],|row|Ok((row.get::<_,String>(0)?,row.get::<_,Option<String>>(1)?))).map_err(crate::storage::db::db_sql_error)?;
            for value in values {
                let (key,value)=value.map_err(crate::storage::db::db_sql_error)?;
                if let Some(value)=value {rows.insert(key,value);} else if matches!(key.as_str(),"openai_api_key"|"gemini_api_key") {
                    rows.insert(key,String::new());
                } else if matches!(key.as_str(),"ai_provider"|"image_provider"|"image_quality"|"default_domain"|"auto_analyze"|"language"|"theme"|"max_concurrent_analyses"|"pdf_parser_mode"|"extraction_pipeline_version"|"pdf_visual_engine"|"research_context"|"default_explanation_level"|"research_areas"|"field_expertise"|"reading_experience"|"research_role") {
                    return Err(SasooError::InvalidInput("A stored setting is null and cannot be represented by the legacy response contract.".into()));
                }
            }
            Ok(rows)
        })?;
        let openai = self.credentials.read_secret_state(ProviderId::OpenAi)?;
        let gemini = self.credentials.read_secret_state(ProviderId::Gemini)?;
        let describe = |state: SecretState| -> (String, bool, bool) {
            match state {
                SecretState::Missing => (String::new(), false, false),
                SecretState::Unreadable => (String::new(), true, false),
                SecretState::Readable(secret) => (
                    mask_api_key(secret.expose_secret()),
                    false,
                    !secret.expose_secret().trim().is_empty(),
                ),
            }
        };
        let (openai_masked, openai_unreadable, openai_available) = describe(openai);
        let (gemini_masked, gemini_unreadable, gemini_available) = describe(gemini);
        let display = SecretDisplay {
            openai_masked,
            openai_unreadable,
            openai_available,
            gemini_masked,
            gemini_unreadable,
            gemini_available,
        };
        let library = rows
            .get(&self.library_setting_key)
            .and_then(|raw| usable_library_path(raw, &self.home, self.platform))
            .or_else(|| {
                rows.get("library_path")
                    .and_then(|raw| usable_library_path(raw, &self.home, self.platform))
            })
            .map(|path| path.to_string_lossy().into_owned())
            .unwrap_or_else(|| self.default_library.clone());
        settings_from_rows(&rows, &library, display)
    }

    pub fn update_settings(
        &self,
        patch: SettingsPatch,
        expected_epochs: &[(ProviderId, KeyEpoch)],
        validate_library: impl FnOnce(&str) -> Result<String>,
    ) -> Result<SettingsDto> {
        let mut prepared =
            prepare_settings_patch(patch, &self.library_setting_key, validate_library)?;
        let mut secrets = Vec::new();
        for (key, value) in prepared.secret_updates {
            prepared.stored_updates.remove(&key);
            let provider = if key == "openai_api_key" {
                ProviderId::OpenAi
            } else {
                ProviderId::Gemini
            };
            let expected = expected_epochs
                .iter()
                .find_map(|(candidate, epoch)| (*candidate == provider).then_some(*epoch))
                .ok_or_else(|| {
                    SasooError::Conflict(
                        "A credential epoch is required before updating an API key.".into(),
                    )
                })?;
            let update = match value {
                Some(value) => SecretUpdate::Set {
                    provider,
                    value: SecretString::from(value),
                },
                None => SecretUpdate::Clear { provider },
            };
            secrets.push((update, expected));
        }
        self.credentials
            .apply_settings_update(secrets, prepared.stored_updates)?;
        self.get_settings()
    }
}

#[derive(Default, Deserialize)]
pub struct SettingsPatch {
    pub gemini_api_key: Option<String>,
    pub openai_api_key: Option<String>,
    pub ai_provider: Option<String>,
    pub image_provider: Option<String>,
    pub image_quality: Option<String>,
    pub library_path: Option<String>,
    pub default_domain: Option<String>,
    pub auto_analyze: Option<bool>,
    pub language: Option<String>,
    pub theme: Option<String>,
    pub max_concurrent_analyses: Option<i64>,
    pub pdf_parser_mode: Option<String>,
    pub extraction_pipeline_version: Option<String>,
    pub pdf_visual_engine: Option<String>,
    pub research_context: Option<String>,
    pub default_explanation_level: Option<String>,
    pub research_areas: Option<Vec<String>>,
    pub field_expertise: Option<String>,
    pub reading_experience: Option<String>,
    pub research_role: Option<String>,
}

// This value may hold secrets. Debug output contains only counts.
pub struct PreparedSettingsPatch {
    pub stored_updates: BTreeMap<String, String>,
    pub secret_updates: BTreeMap<String, Option<String>>,
    pub library_path: Option<String>,
}
impl fmt::Debug for PreparedSettingsPatch {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("PreparedSettingsPatch")
            .field("stored_count", &self.stored_updates.len())
            .field("secret_count", &self.secret_updates.len())
            .finish_non_exhaustive()
    }
}

#[derive(Default)]
pub struct SecretDisplay {
    pub openai_masked: String,
    pub gemini_masked: String,
    pub openai_unreadable: bool,
    pub gemini_unreadable: bool,
    pub openai_available: bool,
    pub gemini_available: bool,
}

#[derive(Serialize)]
pub struct SettingsDto {
    pub gemini_api_key: String,
    pub gemini_key_unreadable: bool,
    pub openai_api_key: String,
    pub openai_key_unreadable: bool,
    pub ai_provider: String,
    pub active_provider: Option<String>,
    pub switched_to: Option<String>,
    pub image_provider: String,
    pub image_quality: String,
    pub library_path: String,
    pub default_domain: String,
    pub auto_analyze: bool,
    pub language: String,
    pub theme: String,
    pub max_concurrent_analyses: i64,
    pub pdf_parser_mode: String,
    pub extraction_pipeline_version: String,
    pub pdf_visual_engine: String,
    pub research_context: String,
    pub default_explanation_level: String,
    pub research_areas: Vec<String>,
    pub field_expertise: String,
    pub reading_experience: String,
    pub research_role: String,
}

pub fn mask_api_key(key: &str) -> String {
    let length = key.chars().count();
    if length == 0 {
        String::new()
    } else if length < 16 {
        "***".into()
    } else {
        let start: String = key.chars().take(8).collect();
        let end: String = key.chars().skip(length - 4).collect();
        format!("{start}...{end}")
    }
}

pub fn parse_research_areas(raw: &str) -> Vec<String> {
    match serde_json::from_str::<serde_json::Value>(raw) {
        Ok(serde_json::Value::Array(items)) => items
            .into_iter()
            .filter_map(|item| item.as_str().map(str::to_owned))
            .take(3)
            .collect(),
        _ => Vec::new(),
    }
}

pub fn effective_provider(
    stored: Option<&str>,
    has_openai: bool,
    has_gemini: bool,
) -> Option<&'static str> {
    match stored {
        Some("openai") if has_openai => Some("openai"),
        Some("gemini") if has_gemini => Some("gemini"),
        _ if has_openai => Some("openai"),
        _ if has_gemini => Some("gemini"),
        _ => None,
    }
}

fn allowed(value: &str, values: &[&str], message: &str) -> Result<()> {
    if values.contains(&value) {
        Ok(())
    } else {
        Err(SasooError::InvalidInput(message.into()))
    }
}

fn legacy_json_areas(values: &[String]) -> String {
    let encoded = values
        .iter()
        .take(3)
        .map(|value| {
            let quoted = serde_json::to_string(value).expect("a string can be JSON encoded");
            let mut output = String::new();
            for ch in quoted.chars() {
                if ch <= '\u{7e}' {
                    output.push(ch)
                } else {
                    let mut units = [0u16; 2];
                    for unit in ch.encode_utf16(&mut units) {
                        output.push_str(&format!("\\u{unit:04x}"));
                    }
                }
            }
            output
        })
        .collect::<Vec<_>>();
    format!("[{}]", encoded.join(", "))
}

/// Prepare all changes before writing. The caller encrypts secrets and commits once.
pub fn prepare_settings_patch(
    patch: SettingsPatch,
    library_setting_key: &str,
    validate_library: impl FnOnce(&str) -> Result<String>,
) -> Result<PreparedSettingsPatch> {
    let mut values = BTreeMap::new();
    macro_rules! put {
        ($field:ident) => {
            if let Some(value) = patch.$field {
                values.insert(stringify!($field).to_owned(), value);
            }
        };
    }
    put!(gemini_api_key);
    put!(openai_api_key);
    put!(ai_provider);
    put!(image_provider);
    put!(image_quality);
    put!(default_domain);
    put!(language);
    put!(theme);
    put!(pdf_parser_mode);
    put!(extraction_pipeline_version);
    put!(pdf_visual_engine);
    put!(research_context);
    put!(default_explanation_level);
    put!(field_expertise);
    put!(reading_experience);
    put!(research_role);
    if let Some(value) = patch.auto_analyze {
        values.insert("auto_analyze".into(), value.to_string());
    }
    if let Some(value) = patch.max_concurrent_analyses {
        values.insert("max_concurrent_analyses".into(), value.to_string());
    }
    if let Some(value) = patch.research_areas {
        values.insert("research_areas".into(), legacy_json_areas(&value));
    }
    if values.is_empty() && patch.library_path.is_none() {
        return Err(SasooError::InvalidInput("No settings to update.".into()));
    }
    let library_path = patch
        .library_path
        .as_deref()
        .map(validate_library)
        .transpose()?;
    for key in ["ai_provider", "image_provider"] {
        if let Some(value) = values.get(key) {
            allowed(
                value,
                &["openai", "gemini"],
                "provider must be 'openai' or 'gemini'.",
            )?;
        }
    }
    if let Some(value) = values.get("image_quality") {
        allowed(
            value,
            &["low", "medium", "high"],
            "image_quality is invalid.",
        )?;
    }
    if let Some(value) = values.get("default_domain") {
        allowed(
            value,
            &["optics", "bio", "ai_ml", "ee", "general"],
            "default_domain is invalid.",
        )?;
    }
    if let Some(value) = values.get("pdf_parser_mode") {
        allowed(
            value,
            &["java"],
            "Slim build supports only 'java' for pdf_parser_mode.",
        )?;
    }
    if let Some(value) = values.get("extraction_pipeline_version") {
        allowed(
            value,
            &["resolver_v1"],
            "extraction_pipeline_version must be 'resolver_v1'.",
        )?;
    }
    if let Some(value) = values.get("pdf_visual_engine") {
        allowed(
            value,
            &["gemini", "odl"],
            "pdf_visual_engine must be 'gemini' or 'odl'.",
        )?;
    }
    if let Some(provider) = values.get("ai_provider").cloned() {
        values.insert("image_provider".into(), provider);
    }
    let mut secret_updates = BTreeMap::new();
    for key in ["gemini_api_key", "openai_api_key"] {
        if let Some(value) = values.remove(key) {
            if !value.contains("...") {
                secret_updates.insert(
                    key.to_owned(),
                    if value.is_empty() { None } else { Some(value) },
                );
            }
        }
    }
    for (key, value) in &secret_updates {
        if value.is_none() {
            values.insert(key.clone(), String::new());
        }
    }
    if let Some(path) = &library_path {
        values.insert(library_setting_key.into(), path.clone());
    }
    Ok(PreparedSettingsPatch {
        stored_updates: values,
        secret_updates,
        library_path,
    })
}

/// Map stored metadata and already-masked credential state to the legacy response.
pub fn settings_from_rows(
    rows: &BTreeMap<String, String>,
    resolved_library: &str,
    secrets: SecretDisplay,
) -> Result<SettingsDto> {
    let get =
        |key: &str, default: &str| rows.get(key).cloned().unwrap_or_else(|| default.to_owned());
    let stored = get("ai_provider", "openai");
    let active = effective_provider(
        Some(&stored),
        secrets.openai_available,
        secrets.gemini_available,
    )
    .map(str::to_owned);
    let switched = if ["openai", "gemini"].contains(&stored.as_str())
        && active.as_deref().is_some_and(|value| value != stored)
    {
        active.clone()
    } else {
        None
    };
    let concurrent = get("max_concurrent_analyses", "3")
        .trim()
        .parse::<i64>()
        .map_err(|_| {
            SasooError::InvalidInput("Stored max_concurrent_analyses is invalid.".into())
        })?;
    let pipeline = get("extraction_pipeline_version", "resolver_v1");
    Ok(SettingsDto {
        gemini_api_key: secrets.gemini_masked,
        gemini_key_unreadable: secrets.gemini_unreadable,
        openai_api_key: secrets.openai_masked,
        openai_key_unreadable: secrets.openai_unreadable,
        ai_provider: if ["openai", "gemini"].contains(&stored.as_str()) {
            stored
        } else {
            "openai".into()
        },
        active_provider: active,
        switched_to: switched,
        image_provider: get("image_provider", "openai"),
        image_quality: get("image_quality", "high"),
        library_path: resolved_library.into(),
        default_domain: get("default_domain", "optics"),
        auto_analyze: get("auto_analyze", "true").to_lowercase() == "true",
        language: get("language", "ko"),
        theme: get("theme", "light"),
        max_concurrent_analyses: concurrent,
        pdf_parser_mode: "java".into(),
        extraction_pipeline_version: if pipeline == "legacy" {
            "resolver_v1".into()
        } else {
            pipeline
        },
        pdf_visual_engine: get("pdf_visual_engine", "gemini"),
        research_context: get("research_context", ""),
        default_explanation_level: get("default_explanation_level", "masters"),
        research_areas: parse_research_areas(&get("research_areas", "[]")),
        field_expertise: get("field_expertise", "major"),
        reading_experience: get("reading_experience", "regular"),
        research_role: get("research_role", "grad_student"),
    })
}
