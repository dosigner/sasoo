//! Question-specific retrieval over a versioned extracted document.
use regex::Regex;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::HashSet;
use std::sync::OnceLock;
use unicode_normalization::UnicodeNormalization;

#[derive(Debug, Clone, Deserialize)]
pub struct Document {
    #[serde(default)]
    pub parser_version: String,
    pub full_text: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Chunk {
    pub text: String,
    pub page: Option<usize>,
    pub section: Option<String>,
    pub extraction_version: String,
    pub text_sha256: String,
    pub chunk_sha256: String,
    pub extraction_status: String,
    pub truncated: bool,
}

fn re(slot: &'static OnceLock<Regex>, pattern: &str) -> &'static Regex {
    slot.get_or_init(|| Regex::new(pattern).expect("valid static retrieval pattern"))
}
fn hash(s: &str) -> String {
    format!("{:x}", Sha256::digest(s.as_bytes()))
}
pub(crate) fn words(s: &str) -> Vec<String> {
    static RE: OnceLock<Regex> = OnceLock::new();
    re(&RE, r"[a-zA-Z]{3,}|[가-힣]{2,}|\d+(?:\.\d+)*")
        .find_iter(s)
        .map(|m| m.as_str().to_owned())
        .collect()
}
pub(crate) fn is_stop(s: &str) -> bool {
    matches!(
        s,
        "the"
            | "and"
            | "what"
            | "how"
            | "which"
            | "does"
            | "this"
            | "that"
            | "with"
            | "from"
            | "table"
            | "figure"
            | "section"
            | "fig"
            | "sec"
            | "논문"
            | "무엇"
            | "설명해줘"
            | "어떤"
            | "에서"
            | "있어"
    )
}

pub fn chunks(document: &Document) -> Vec<Chunk> {
    static PAGE: OnceLock<Regex> = OnceLock::new();
    static HEADING: OnceLock<Regex> = OnceLock::new();
    static BLOCK: OnceLock<Regex> = OnceLock::new();
    let text = &document.full_text;
    if text.trim().is_empty() {
        return vec![];
    }
    let page_re = re(&PAGE, r"(?m)^--- Page (\d+) ---\s*$");
    let markers: Vec<_> = page_re.captures_iter(text).collect();
    let mut pieces: Vec<(Option<usize>, &str)> = vec![];
    if markers.is_empty() {
        pieces.push((None, text));
    } else {
        let first = markers[0].get(0).unwrap();
        if !text[..first.start()].trim().is_empty() {
            pieces.push((None, &text[..first.start()]));
        }
        for (i, m) in markers.iter().enumerate() {
            let whole = m.get(0).unwrap();
            let end = markers
                .get(i + 1)
                .map_or(text.len(), |next| next.get(0).unwrap().start());
            pieces.push((m[1].parse().ok(), &text[whole.end()..end]));
        }
    }
    let signature = hash(text);
    let version = if document.parser_version.is_empty() {
        "unknown"
    } else {
        &document.parser_version
    };
    let mut section: Option<String> = None;
    let mut result = vec![];
    for (page, body) in pieces {
        for block in re(&BLOCK, r"\n\s*\n")
            .split(body)
            .map(str::trim)
            .filter(|b| !b.is_empty())
        {
            let first = block.lines().next().unwrap_or("").trim();
            if re(
                &HEADING,
                r"^(?:#{1,6}\s+)?(?:\d+(?:\.\d+)*\.?\s+)[A-Z][^\n]{2,120}$",
            )
            .is_match(first)
            {
                section = Some(first.trim_start_matches(['#', ' ']).to_owned());
            }
            let chars: Vec<char> = block.chars().collect();
            for part in chars.chunks(1800) {
                let content: String = part.iter().collect();
                result.push(Chunk {
                    chunk_sha256: hash(&content),
                    text: content,
                    page,
                    section: section.clone(),
                    extraction_version: version.into(),
                    text_sha256: signature.clone(),
                    extraction_status: if page.is_some() {
                        "page_unverified"
                    } else {
                        "page_unknown"
                    }
                    .into(),
                    truncated: chars.len() > 1800,
                });
            }
        }
    }
    result
}

pub fn search(document: &Document, question: &str, limit: usize) -> Vec<Chunk> {
    if limit == 0 {
        return vec![];
    }
    static TARGET: OnceLock<Regex> = OnceLock::new();
    static BARE: OnceLock<Regex> = OnceLock::new();
    let question = question.to_lowercase();
    let terms: HashSet<_> = words(&question)
        .into_iter()
        .filter(|s| !is_stop(s))
        .collect();
    let phrase = words(&question).join(" ");
    let mut targets: Vec<(String, String)> = re(
        &TARGET,
        r"(?i)\b(table|figure|fig\.?|section|sec\.?|표|그림|절)\s*(\d+(?:\.\d+)*)",
    )
    .captures_iter(&question)
    .map(|c| {
        let kind = &c[1];
        (
            if kind.starts_with("fig") || kind == "그림" {
                "figure"
            } else if kind.starts_with("sec") || kind == "절" {
                "section"
            } else {
                "table"
            }
            .into(),
            c[2].into(),
        )
    })
    .collect();
    for c in re(&BARE, r"\d+\.\d+(?:\.\d+)*").find_iter(&question) {
        if !targets.iter().any(|(_, n)| n == c.as_str()) {
            targets.push(("section".into(), c.as_str().into()));
        }
    }
    let patterns: Vec<Regex> = targets
        .iter()
        .map(|(kind, number)| {
            let prefix = match kind.as_str() {
                "figure" => r"\b(?:figure|fig\.?)",
                "section" => r"\b(?:section|sec\.?)",
                _ => r"\btable",
            };
            Regex::new(&format!(r"(?i){}\s*{}", prefix, regex::escape(number)))
                .expect("escaped target")
        })
        .collect();
    let all = chunks(document);
    let mut ranked = vec![];
    for (index, chunk) in all.iter().enumerate() {
        let text = chunk.text.to_lowercase();
        let text_words: HashSet<_> = words(&text).into_iter().collect();
        let mut score = terms
            .intersection(&text_words)
            .filter(|t| !t.chars().all(|c| c.is_ascii_digit() || c == '.'))
            .count();
        if phrase.chars().count() >= 8 && words(&text).join(" ").contains(&phrase) {
            score += 4;
        }
        let mut matched = false;
        for ((kind, number), target_re) in targets.iter().zip(&patterns) {
            if let Some(m) = target_re.find_iter(&text).find(|m| {
                let rest = &text[m.end()..];
                !rest.starts_with(|c: char| c.is_ascii_digit())
                    && !(rest.starts_with('.')
                        && rest[1..].starts_with(|c: char| c.is_ascii_digit()))
            }) {
                score += 15;
                matched = true;
                if text[..m.start()].trim().trim_matches('#').trim().is_empty() {
                    score += 10;
                }
            }
            if kind == "section"
                && chunk
                    .section
                    .as_ref()
                    .is_some_and(|s| s.starts_with(&format!("{number} ")))
            {
                score += 15;
                matched = true;
            }
        }
        if score > 0 && (targets.is_empty() || matched) {
            ranked.push((std::cmp::Reverse(score), index));
        }
    }
    ranked.sort();
    let mut seen = HashSet::new();
    let mut result = vec![];
    for (_, index) in ranked {
        if seen.insert(index) {
            result.push(all[index].clone());
        }
        if targets.iter().any(|(kind, _)| kind == "table") {
            for adjacent in [
                index.checked_sub(1),
                index.checked_add(1).filter(|i| *i < all.len()),
            ]
            .into_iter()
            .flatten()
            {
                if !seen.contains(&adjacent)
                    && all[adjacent].page == all[index].page
                    && all[adjacent].text.trim_start().starts_with('|')
                {
                    seen.insert(adjacent);
                    result.push(all[adjacent].clone());
                }
            }
        }
        if result.len() >= limit {
            break;
        }
    }
    result.truncate(limit);
    result
}

fn pdf_words(s: &str) -> Vec<String> {
    static WORDS: OnceLock<Regex> = OnceLock::new();
    static BREAK: OnceLock<Regex> = OnceLock::new();
    let normalized = s.nfkc().collect::<String>().to_lowercase();
    let mut joined = normalized;
    loop {
        let next = re(&BREAK, r"([a-z])-\s*\n\s*([a-z])")
            .replace_all(&joined, "$1$2")
            .into_owned();
        if next == joined {
            break;
        }
        joined = next;
    }
    re(&WORDS, r"[a-z0-9]+|[가-힣]+")
        .find_iter(&joined)
        .map(|m| m.as_str().to_owned())
        .collect()
}

/// `physical_pages` must be extracted independently from the PDF, in physical page order.
pub fn verify_pages(mut results: Vec<Chunk>, physical_pages: Option<&[String]>) -> Vec<Chunk> {
    for chunk in &mut results {
        let page_text = chunk
            .page
            .and_then(|p| p.checked_sub(1))
            .and_then(|p| physical_pages.and_then(|pages| pages.get(p)));
        let source = pdf_words(&chunk.text.chars().take(1200).collect::<String>());
        let target = page_text.map(|p| pdf_words(p)).unwrap_or_default();
        let mut positions = vec![];
        for i in 0..source.len().saturating_sub(5) {
            let slice = &source[i..i + 6];
            if slice
                .iter()
                .filter(|w| w.chars().count() >= 3 && !w.chars().all(|c| c.is_ascii_digit()))
                .count()
                >= 3
                && target.windows(6).any(|w| w == slice)
            {
                positions.push(i);
            }
        }
        let matched = if source.len() < 24 {
            !positions.is_empty()
        } else {
            positions.iter().any(|i| *i < source.len() / 2)
                && positions.iter().any(|i| *i >= source.len() / 2)
        };
        if !matched {
            chunk.page = None;
        }
        chunk.extraction_status = if matched {
            "page_confirmed"
        } else {
            "page_unknown"
        }
        .into();
    }
    results
}
