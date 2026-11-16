//! F04 agent .md profiles (port of services/agents/md_loader.py `parse_agent_md`) and
//! the stage persona (`_build_persona_prompt`, analysis_execution.py).
//!
//! shortcut: the frontmatter reader handles the forms the bundled agents use (plain,
//! "double"- and 'single'-quoted scalars, `[]`/`[a, b]` and `- item` lists, booleans).
//! Other YAML (block scalars `|`/`>`, anchors, nested maps) makes the profile invalid
//! instead of guessing; extend it if a user agent needs more.
use crate::error::{Result, SasooError};
use std::collections::HashMap;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AgentProfile {
    pub agent_name: String,
    pub domain: String,
    pub personality: String,
    pub enabled: bool,
    /// Body sections keyed like Python: screening, visual, recipe, deepdive, ...
    pub prompts: HashMap<String, String>,
}

/// YAML that PyYAML itself rejects; Python then keeps an empty frontmatter.
const INVALID_YAML: &str = "invalid yaml";

#[derive(Debug, Clone, PartialEq)]
enum Yaml {
    Scalar(String),
    Bool(bool),
    Null,
    List(Vec<String>),
}

fn unquote(raw: &str) -> Result<Yaml> {
    let bad = || SasooError::InvalidInput(format!("Unsupported agent frontmatter value: {raw}"));
    let v = raw.trim();
    if let Some(inner) = v.strip_prefix('"').and_then(|r| r.strip_suffix('"')) {
        let mut out = String::new();
        let mut chars = inner.chars();
        while let Some(c) = chars.next() {
            if c != '\\' {
                out.push(c);
                continue;
            }
            match chars.next().ok_or_else(bad)? {
                'n' => out.push('\n'),
                't' => out.push('\t'),
                '"' => out.push('"'),
                '\\' => out.push('\\'),
                '/' => out.push('/'),
                _ => return Err(bad()),
            }
        }
        return Ok(Yaml::Scalar(out));
    }
    if let Some(inner) = v.strip_prefix('\'').and_then(|r| r.strip_suffix('\'')) {
        return Ok(Yaml::Scalar(inner.replace("''", "'")));
    }
    if v.starts_with(['|', '>', '&', '*', '{', '!']) {
        return Err(bad());
    }
    if let Some(inner) = v.strip_prefix('[').and_then(|r| r.strip_suffix(']')) {
        let items = inner
            .split(',')
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(|s| match unquote(s)? {
                Yaml::Scalar(s) => Ok(s),
                _ => Err(bad()),
            })
            .collect::<Result<_>>()?;
        return Ok(Yaml::List(items));
    }
    // Plain scalar: a trailing " #" starts a comment; ": " inside is a YAML error.
    let plain = v.split(" #").next().unwrap_or("").trim_end();
    if plain.contains(": ") || plain.ends_with(':') {
        return Err(SasooError::InvalidInput(INVALID_YAML.into()));
    }
    Ok(match plain {
        "" | "~" | "null" | "Null" | "NULL" => Yaml::Null,
        "true" | "True" | "TRUE" => Yaml::Bool(true),
        "false" | "False" | "FALSE" => Yaml::Bool(false),
        s => Yaml::Scalar(s.to_owned()),
    })
}

fn frontmatter(text: &str) -> Result<HashMap<String, Yaml>> {
    let mut out = HashMap::new();
    let mut list_key: Option<String> = None;
    for line in text.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') {
            continue;
        }
        if let Some(item) = trimmed.strip_prefix("- ").or_else(|| (trimmed == "-").then_some("")) {
            let key = list_key.clone().ok_or_else(|| SasooError::InvalidInput("List item without a key".into()))?;
            let value = match unquote(item)? {
                Yaml::Scalar(s) => s,
                Yaml::Bool(b) => if b { "True".into() } else { "False".into() },
                _ => return Err(SasooError::InvalidInput("Unsupported list item".into())),
            };
            match out.entry(key).or_insert(Yaml::List(Vec::new())) {
                Yaml::List(items) => items.push(value),
                slot => *slot = Yaml::List(vec![value]),
            }
            continue;
        }
        if line.starts_with([' ', '\t']) {
            return Err(SasooError::InvalidInput("Nested agent frontmatter is not supported".into()));
        }
        let (key, value) = trimmed.split_once(':').ok_or_else(|| SasooError::InvalidInput("Frontmatter line has no key".into()))?;
        let key = key.trim().to_owned();
        let parsed = unquote(value)?;
        list_key = (parsed == Yaml::Null).then(|| key.clone());
        out.insert(key, parsed);
    }
    Ok(out)
}

fn section_key(heading: &str) -> String {
    match heading {
        "screening" | "visual" | "recipe" => heading.to_owned(),
        "deep dive" | "deep_dive" | "deepdive" => "deepdive".to_owned(),
        other => other.replace(' ', "_"),
    }
}

/// Python `str.strip()` set.
fn strip(s: &str) -> &str {
    s.trim_matches(|c: char| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c))
}

/// Python str(): None -> "None", booleans -> "True"/"False".
fn as_text(value: Option<&Yaml>, default: &str) -> String {
    match value {
        None => default.to_owned(),
        Some(Yaml::Scalar(s)) => s.clone(),
        Some(Yaml::Bool(b)) => if *b { "True".into() } else { "False".into() },
        Some(Yaml::Null) => "None".into(),
        Some(Yaml::List(items)) => format!("[{}]", items.iter().map(|s| format!("'{s}'")).collect::<Vec<_>>().join(", ")),
    }
}

pub fn parse_agent_md(text: &str) -> Result<AgentProfile> {
    let mut meta = HashMap::new();
    let mut body = text;
    if text.starts_with("---") {
        let parts: Vec<&str> = text.splitn(3, "---").collect();
        if parts.len() >= 3 {
            meta = match frontmatter(parts[1]) {
                Ok(meta) => meta,
                Err(SasooError::InvalidInput(m)) if m == INVALID_YAML => HashMap::new(),
                Err(e) => return Err(e),
            };
            body = strip(parts[2]);
        }
    }
    let mut prompts = HashMap::new();
    let mut current: Option<String> = None;
    let mut lines: Vec<&str> = Vec::new();
    // Python str.splitlines() also splits on \r, \x0b, \x0c, \x1c-\x1e, \x85,  ,  .
    let splits = |c: char| matches!(c, '\n' | '\r' | '\x0b' | '\x0c' | '\x1c' | '\x1d' | '\x1e' | '\u{85}' | '\u{2028}' | '\u{2029}');
    let normalized = body.replace("\r\n", "\n");
    for line in normalized.split(splits) {
        if line.starts_with("# ") && !line.starts_with("## ") {
            if let Some(key) = current.take() {
                prompts.insert(key, strip(&lines.join("\n")).to_owned());
            }
            current = Some(section_key(&strip(&line[2..]).to_lowercase()));
            lines.clear();
        } else {
            lines.push(line);
        }
    }
    if let Some(key) = current {
        prompts.insert(key, strip(&lines.join("\n")).to_owned());
    }
    let enabled = match meta.get("enabled") {
        None => true,
        Some(Yaml::Bool(b)) => *b,
        Some(Yaml::Null) => false,
        Some(Yaml::Scalar(s)) => !s.is_empty(),
        Some(Yaml::List(items)) => !items.is_empty(),
    };
    Ok(AgentProfile {
        agent_name: as_text(meta.get("name"), ""),
        domain: as_text(meta.get("domain"), ""),
        personality: as_text(meta.get("personality"), ""),
        enabled,
        prompts,
    })
}

/// `_build_persona_prompt(agent, stage)`: personality plus the stage overlay section.
pub fn persona_prompt(agent: &AgentProfile, stage: Option<&str>) -> String {
    let overlay = match stage {
        Some("visual") => agent.prompts.get("visual"),
        Some("recipe") => agent.prompts.get("recipe"),
        Some("deep_dive") => agent.prompts.get("deepdive"),
        _ => None,
    }
    .map(String::as_str)
    .unwrap_or("");
    [agent.personality.as_str(), overlay]
        .into_iter()
        .filter(|p| !strip(p).is_empty())
        .map(strip)
        .collect::<Vec<_>>()
        .join("\n\n")
}
