use crate::{
    error::{Result, SasooError},
    types::{Hash256, ProviderId, SecretRef},
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct FrozenAgent {
    pub name: String,
    pub enabled: bool,
    pub keywords: Vec<String>,
    pub raw_md: String,
    pub sha256: Hash256,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct PdfIdentity {
    pub source_sha256: Hash256,
    pub engine: String,
    pub engine_revision: String,
    pub options_hash: Hash256,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct ConfigInput {
    pub schema_version: u32,
    pub provider_roles: BTreeMap<String, ProviderId>,
    pub models: BTreeMap<String, String>,
    pub efforts: BTreeMap<String, Option<String>>,
    pub prompt_schema_hashes: BTreeMap<String, Hash256>,
    pub raw_agent_hash: Option<Hash256>,
    pub frozen_agent_catalog: Vec<FrozenAgent>,
    pub agent_selection_policy_version: String,
    pub profile: Value,
    pub focus: Value,
    pub pdf_identity: PdfIdentity,
    pub limits: BTreeMap<String, u64>,
    pub cache_version: String,
    pub secret_refs: Vec<SecretRef>,
}

// Only resolve_config constructs snapshots, so callers cannot mutate frozen bytes.
#[derive(Clone, Debug)]
pub struct ConfigSnapshot {
    snapshot: ConfigInput,
    canonical_bytes: Vec<u8>,
    sha256: Hash256,
}

impl ConfigSnapshot {
    pub fn snapshot(&self) -> &ConfigInput {
        &self.snapshot
    }
    pub fn canonical_bytes(&self) -> &[u8] {
        &self.canonical_bytes
    }
    pub fn sha256(&self) -> Hash256 {
        self.sha256
    }
}

fn invalid(message: &str) -> SasooError {
    SasooError::InvalidInput(message.into())
}

fn forbid_secret_fields(value: &Value) -> Result<()> {
    match value {
        Value::Object(fields) => {
            for (key, value) in fields {
                let key = key
                    .chars()
                    .filter(char::is_ascii_alphanumeric)
                    .collect::<String>()
                    .to_ascii_lowercase();
                if [
                    "apikey",
                    "openaiapikey",
                    "geminiapikey",
                    "secret",
                    "password",
                    "token",
                    "accesstoken",
                    "refreshtoken",
                    "authorization",
                    "credentials",
                ]
                .contains(&key.as_str())
                {
                    return Err(invalid(
                        "Configuration contains a credential field; use SecretRef only",
                    ));
                }
                forbid_secret_fields(value)?;
            }
        }
        Value::Array(items) => {
            for item in items {
                forbid_secret_fields(item)?;
            }
        }
        _ => {}
    }
    Ok(())
}

fn sort_json(value: Value) -> Value {
    match value {
        Value::Object(fields) => Value::Object(
            fields
                .into_iter()
                .collect::<BTreeMap<_, _>>()
                .into_iter()
                .map(|(key, value)| (key, sort_json(value)))
                .collect(),
        ),
        Value::Array(items) => Value::Array(items.into_iter().map(sort_json).collect()),
        value => value,
    }
}

pub fn resolve_config(input: &ConfigInput) -> Result<ConfigSnapshot> {
    if input.schema_version != 1 {
        return Err(invalid("Unsupported configuration schema version"));
    }
    if input.provider_roles.is_empty()
        || input.models.keys().ne(input.provider_roles.keys())
        || input.efforts.keys().ne(input.provider_roles.keys())
    {
        return Err(invalid(
            "Every provider role requires a frozen model and explicit effort value",
        ));
    }
    if input
        .models
        .iter()
        .any(|(role, model)| role.trim().is_empty() || model.trim().is_empty())
        || input
            .efforts
            .values()
            .flatten()
            .any(|value| value.trim().is_empty())
    {
        return Err(invalid(
            "Configuration role, model and effort names cannot be empty",
        ));
    }
    if input.prompt_schema_hashes.is_empty()
        || input
            .prompt_schema_hashes
            .keys()
            .any(|name| name.trim().is_empty())
        || input.frozen_agent_catalog.is_empty()
        || input.agent_selection_policy_version.trim().is_empty()
        || input.cache_version.trim().is_empty()
        || input.limits.is_empty()
    {
        return Err(invalid(
            "Configuration is missing hashes, agent catalog, policy, limits or cache version",
        ));
    }
    if input.pdf_identity.engine.trim().is_empty()
        || input.pdf_identity.engine_revision.trim().is_empty()
    {
        return Err(invalid("PDF engine identity and revision must be frozen"));
    }
    let mut names = BTreeSet::new();
    for agent in &input.frozen_agent_catalog {
        if agent.name.trim().is_empty()
            || !names.insert(agent.name.as_str())
            || Sha256::digest(agent.raw_md.as_bytes()).as_slice() != agent.sha256
        {
            return Err(invalid("Frozen agent names or source hashes are invalid"));
        }
    }
    if input.raw_agent_hash.is_some_and(|hash| {
        !input
            .frozen_agent_catalog
            .iter()
            .any(|agent| agent.sha256 == hash)
    }) {
        return Err(invalid(
            "Selected agent hash is outside the frozen candidate catalog",
        ));
    }
    let mut providers = BTreeSet::new();
    for reference in &input.secret_refs {
        if reference.epoch.0 < 0 || !providers.insert(format!("{:?}", reference.provider)) {
            return Err(invalid(
                "Secret references require unique providers and valid epochs",
            ));
        }
    }
    for provider in input.provider_roles.values() {
        if !input
            .secret_refs
            .iter()
            .any(|reference| reference.provider == *provider)
        {
            return Err(invalid(
                "A provider role has no frozen credential reference",
            ));
        }
    }
    forbid_secret_fields(&input.profile)?;
    forbid_secret_fields(&input.focus)?;
    let value =
        serde_json::to_value(input).map_err(|_| invalid("Configuration cannot be serialized"))?;
    let canonical_bytes = serde_json::to_vec(&sort_json(value))
        .map_err(|_| invalid("Configuration cannot be serialized"))?;
    let sha256 = Sha256::digest(&canonical_bytes).into();
    Ok(ConfigSnapshot {
        snapshot: input.clone(),
        canonical_bytes,
        sha256,
    })
}
