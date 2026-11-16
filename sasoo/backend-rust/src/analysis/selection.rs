//! F05 agent selection after screening (port of `get_agent_for_domain`,
//! services/agents/__init__.py), restricted to the catalog frozen in the run snapshot.
use crate::analysis::{
    agents::{AgentProfile, parse_agent_md},
    config::FrozenAgent,
};
use std::collections::HashMap;

/// `load_all_agents` + `get_agent_for_domain`. The catalog order is `list_all_agents`
/// order (bundled by file name, user overrides in place). Unparseable profiles are skipped.
pub fn agent_for_domain(catalog: &[FrozenAgent], domain: &str) -> AgentProfile {
    let mut keys: Vec<String> = Vec::new();
    let mut cache: HashMap<String, AgentProfile> = HashMap::new();
    for frozen in catalog.iter().filter(|a| a.enabled) {
        let Ok(profile) = parse_agent_md(&frozen.raw_md) else { continue };
        if !profile.enabled {
            continue;
        }
        for key in [profile.domain.clone(), profile.agent_name.clone()] {
            if !cache.contains_key(&key) {
                keys.push(key.clone());
            }
            cache.insert(key, profile.clone());
        }
    }
    if let Some(agent) = cache.get(domain).or_else(|| cache.get("optics")) {
        return agent.clone();
    }
    keys.sort();
    keys.first().and_then(|k| cache.get(k)).cloned().unwrap_or(AgentProfile {
        agent_name: "unknown".into(),
        domain: "unknown".into(),
        personality: String::new(),
        enabled: true,
        prompts: HashMap::new(),
    })
}

/// `screening_data.get("domain") or paper.get("domain") or "general"`.
pub fn screening_domain(screening_text: &str, paper_domain: Option<&str>) -> String {
    use crate::analysis::screening::stage::{clean_llm_json, python_loads, python_str, truthy};
    let text = if screening_text.is_empty() { "{}" } else { screening_text };
    python_loads(&clean_llm_json(text))
        .and_then(|v| v.get("domain").filter(|d| truthy(d)).map(python_str))
        .or_else(|| paper_domain.filter(|d| !d.is_empty()).map(str::to_owned))
        .unwrap_or_else(|| "general".into())
}
