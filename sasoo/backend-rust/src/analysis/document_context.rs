//! Document context (port of services/document_context.py + section_splitter.py).
//!
//! Output must equal Python's dicts exactly. Python `re` differs from the `regex`
//! crate in three ways handled here: `\s` also covers U+001C..U+001F (`S`), `\w` is
//! letters, numbers and `_` (`W`), and `\b` uses that `\w`. Python's zero-width `\b`
//! is rewritten as a one-char guard consumed next to the match; group `m` (when
//! present) carries Python's match span.
use regex::{Captures, Regex};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{collections::BTreeSet, sync::LazyLock};

pub const CONTEXT_BUILDER_VERSION: &str = "document-context-v4";
pub const VISUAL_SOURCE_VERSION: &str = "visual-source-v3-pdf";

const S: &str = r"[\s\x1C-\x1F]";
const W: &str = r"\p{L}\p{N}_";

/// Python pattern -> regex crate pattern: `\s` and `\w` get Python's sets, and the
/// markers `<NW>` (one non-word char) and `<WC>` (one word char) are expanded.
fn rx(p: &str) -> Regex {
    let p = p
        .replace(r"\s", S)
        .replace(r"\w", &format!("[{W}]"))
        .replace("<NW>", &format!("(?-i:[^{W}])"))
        .replace("<WC>", &format!("(?-i:[{W}])"));
    Regex::new(&p).unwrap()
}

macro_rules! lazy_rx {
    ($name:ident, $p:expr) => {
        static $name: LazyLock<Regex> = LazyLock::new(|| rx($p));
    };
}

fn py_space(c: char) -> bool {
    c.is_whitespace() || ('\x1C'..='\x1F').contains(&c)
}

fn strip(s: &str) -> &str {
    s.trim_matches(py_space)
}

fn rstrip(s: &str) -> &str {
    s.trim_end_matches(py_space)
}

fn clen(s: &str) -> usize {
    s.chars().count()
}

/// Python `s[:n]` for a char count `n`.
fn head(s: &str, n: usize) -> &str {
    s.char_indices().nth(n).map_or(s, |(i, _)| &s[..i])
}

fn is_title(c: char) -> bool {
    static LT: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\p{Lt}").unwrap());
    LT.is_match(c.encode_utf8(&mut [0; 4]))
}

/// Python `str.isupper()`.
fn py_isupper(s: &str) -> bool {
    let mut cased = false;
    for c in s.chars() {
        if c.is_lowercase() || is_title(c) {
            return false;
        }
        cased |= c.is_uppercase();
    }
    cased
}

/// Python `str(int(s))` for a `\d+` match (any Unicode decimal digits).
fn py_int(s: &str) -> String {
    static ND: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^\p{Nd}$").unwrap());
    let is_nd =
        |cp: u32| char::from_u32(cp).is_some_and(|c| ND.is_match(c.encode_utf8(&mut [0; 4])));
    let digits: String = s
        .chars()
        .map(|c| {
            if c.is_ascii_digit() {
                return c;
            }
            // Nd chars come in contiguous runs of whole 0..9 sets.
            let mut start = c as u32;
            while start > 0 && is_nd(start - 1) {
                start -= 1;
            }
            char::from(b'0' + ((c as u32 - start) % 10) as u8)
        })
        .collect();
    let trimmed = digits.trim_start_matches('0');
    if trimmed.is_empty() {
        "0".into()
    } else {
        trimmed.into()
    }
}

/// Numeric order of `py_int` strings.
fn int_key(s: &str) -> (usize, &str) {
    (s.len(), s)
}

/// Python finditer for a guarded pattern; group `m` is the Python match.
fn py_iter<'h>(re: &Regex, hay: &'h str) -> Vec<Captures<'h>> {
    let mut out = Vec::new();
    let mut at = 0;
    while let Some(c) = re.captures_at(hay, at) {
        let m = c.name("m").unwrap();
        // Python's \b is zero-width, so the last char of this match may guard the next.
        let back = hay[..m.end()]
            .char_indices()
            .next_back()
            .map_or(0, |(i, _)| i);
        at = if back > at { back } else { m.end() };
        out.push(c);
    }
    out
}

fn py_search<'h>(re: &Regex, hay: &'h str) -> Option<regex::Match<'h>> {
    re.captures(hay).map(|c| c.name("m").unwrap())
}

fn truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64() != Some(0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

/// Ordered `dict[str, str]` with Python insertion semantics.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Sections(pub Vec<(String, String)>);

impl Sections {
    pub fn get(&self, key: &str) -> Option<&str> {
        self.0
            .iter()
            .find(|(k, _)| k == key)
            .map(|(_, v)| v.as_str())
    }

    fn get_or_empty(&self, key: &str) -> &str {
        self.get(key).unwrap_or("")
    }

    /// `d[key] = value`: an existing key keeps its position.
    pub fn insert(&mut self, key: &str, value: String) {
        match self.0.iter_mut().find(|(k, _)| k == key) {
            Some(slot) => slot.1 = value,
            None => self.0.push((key.into(), value)),
        }
    }

    pub fn keys(&self) -> impl Iterator<Item = &str> {
        self.0.iter().map(|(k, _)| k.as_str())
    }

    pub fn to_json(&self) -> Value {
        Value::Object(
            self.0
                .iter()
                .map(|(k, v)| (k.clone(), Value::from(v.as_str())))
                .collect(),
        )
    }

    /// Reads a stored `sections` object; non-string values are skipped.
    pub fn from_json(value: &Value) -> Self {
        let map = value.as_object().cloned().unwrap_or_default();
        Self(
            map.into_iter()
                .filter_map(|(k, v)| Some((k, v.as_str()?.to_owned())))
                .collect(),
        )
    }
}

const SECTION_PATTERNS: &[(&str, &[&str])] = &[
    ("abstract", &["ABSTRACT", "Summary"]),
    (
        "introduction",
        &["INTRODUCTION", r"Background\s+and\s+Introduction"],
    ),
    (
        "background",
        &["BACKGROUND", r"Related\s+Work", r"Literature\s+Review"],
    ),
    (
        "method",
        &[
            "METHOD(S)?",
            "METHODOLOGY",
            r"EXPERIMENTAL\s+SECTION",
            r"EXPERIMENTAL\s+PROCEDURE(S)?",
            r"MATERIALS?\s+AND\s+METHODS?",
            r"EXPERIMENTAL\s+METHODS?",
            "PROCEDURE(S)?",
        ],
    ),
    ("results", &["RESULTS?", "FINDINGS?", "OBSERVATIONS?"]),
    ("discussion", &["DISCUSSION", "ANALYSIS"]),
    (
        "results_discussion",
        &[
            r"RESULTS?\s+AND\s+DISCUSSION",
            r"DISCUSSION\s+OF\s+RESULTS?",
        ],
    ),
    (
        "conclusion",
        &[
            "CONCLUSION(S)?",
            r"SUMMARY\s+AND\s+CONCLUSION(S)?",
            r"FINAL\s+REMARKS?",
        ],
    ),
    ("references", &["REFERENCES?", "BIBLIOGRAPHY", "CITATIONS?"]),
    (
        "acknowledgments",
        &["ACKNOWLEDGMENTS?", "ACKNOWLEDGEMENTS?"],
    ),
];

/// `(type, rf'^.*\b{p}\b.*$' MULTILINE|IGNORECASE, re.search(rf'\b{p}\b'))` per pattern.
static SECTION_REGEXES: LazyLock<Vec<(&str, Regex, Regex)>> = LazyLock::new(|| {
    let nwl = format!("(?-i:[^{W}\\n])");
    SECTION_PATTERNS
        .iter()
        .flat_map(|(kind, patterns)| patterns.iter().map(move |p| (*kind, *p)))
        .map(|(kind, p)| {
            let line = rx(&format!(r"(?mi)^.*(?:^|{nwl}){p}(?:{nwl}|$).*$"));
            let word = rx(&format!(r"(?:\A|<NW>){p}(?:<NW>|\z)"));
            (kind, line, word)
        })
        .collect()
});

lazy_rx!(HEADING_ARABIC, r"^(\d+(?:\.\d+)*)\.\s+(.+)$");
lazy_rx!(HEADING_ROMAN, r"^([IVX]+)\.\s+(.+)$");
lazy_rx!(HEADING_LETTER, r"^([A-Z])\.\s+(.+)$");
lazy_rx!(HEADING_PAREN, r"^\((\d+)\)\s+(.+)$");
lazy_rx!(PAGE_MARKER, r"(?i)\n?\s*---\s*Page\s+\d+\s*---\s*\n?");
lazy_rx!(REFERENCE_START, r"^\s*(?:\[(\d+)\]|(\d+)\.)\s+(.*)$");
lazy_rx!(
    REFERENCE_TERMINATOR,
    r"(?i)^\s*(?:supplementary(?:\s+materials?)?|appendix|acknowledg(?:e)?ments?)(?:<NW>|\z)"
);
lazy_rx!(
    REFERENCE_SIGNAL,
    r"(?i)(?:\A|<NW>)(?:19|20)\d{2}(?:<NW>|\z)|doi\s*:|https?://|et\s+al\.|(?:\A|<NW>)(?:(?:Opt(?:ics)?\.?\s*(?:Express|Letters|Eng)|Nature|Science|Photonics|J\.\s*[A-Z]|Proc\.\s*SPIE|Biomed\.\s*Opt\.\s*Express)(?:<NW>|\z)|Astron\.\s*Astrophys\.<WC>)"
);
lazy_rx!(
    REFERENCES_HEADING,
    r"(?im)^[ \t]*(?:#{1,6}[ \t]*)?(?:(?:\d+(?:\.\d+)*|[IVX]+)[.)]?[ \t]+)?(?:references?|bibliography|citations?)[ \t]*$"
);
lazy_rx!(
    REFERENCES_TERMINATOR,
    r"(?im)^[ \t]*(?:#{1,6}[ \t]+)?(?:Appendix|Supplementary|Acknowledg(?:e)?ments?)(?:<NW>|\z)|^[ \t]*#{1,6}[ \t]+(?-i:[A-Z]\.?[ \t]+[A-Z])"
);
lazy_rx!(PARAGRAPH_BREAK, r"\n\s*\n");
lazy_rx!(PAGE_LABEL, r"(?i)\A\s*(?:\d+\s*)?(?:Preprint)?\s*\z");
lazy_rx!(REFERENCE_LINE, r"(?m)^\s*(?:\[\d+\]|\d+\.)\s+");
lazy_rx!(WHITESPACE_RUN, r"\s+");

/// Python `re.split(p, text, maxsplit=1)[0]`.
fn before_first<'t>(re: &Regex, text: &'t str) -> &'t str {
    re.find(text).map_or(text, |m| &text[..m.start()])
}

fn collapse_ws(text: &str) -> String {
    strip(&WHITESPACE_RUN.replace_all(text, " ")).to_owned()
}

fn is_line_break(c: char) -> bool {
    matches!(
        c,
        '\n' | '\r'
            | '\x0B'
            | '\x0C'
            | '\x1C'
            | '\x1D'
            | '\x1E'
            | '\u{85}'
            | '\u{2028}'
            | '\u{2029}'
    )
}

/// Port of `services.section_splitter.SectionSplitter`.
#[derive(Clone, Copy, Debug, Default)]
pub struct SectionSplitter;

impl SectionSplitter {
    pub fn split(&self, full_text: &str) -> Sections {
        let sections = self.detect_sections_by_patterns(full_text);
        if sections.0.len() > 1 {
            return sections;
        }
        let sections = self.detect_sections_by_headings(full_text);
        if sections.0.len() > 1 {
            return sections;
        }
        Sections(vec![("full_text".into(), full_text.into())])
    }

    fn detect_sections_by_patterns(&self, text: &str) -> Sections {
        let mut positions: Vec<(&str, usize)> = Vec::new();
        for (kind, line_re, _) in SECTION_REGEXES.iter() {
            for m in line_re.find_iter(text) {
                if clen(strip(m.as_str())) > 100 {
                    continue;
                }
                positions.push((kind, m.start()));
            }
        }
        positions.sort_by_key(|p| p.1); // stable, like list.sort
        let mut sections = Sections::default();
        for (i, (kind, start)) in positions.iter().enumerate() {
            let end = positions.get(i + 1).map_or(text.len(), |p| p.1);
            let mut body = strip(&text[*start..end]);
            if let Some((_, rest)) = body.split_once('\n') {
                body = strip(rest);
            }
            let merged = match sections.get(kind) {
                Some(prev) => format!("{prev}\n\n{body}"),
                None => body.to_owned(),
            };
            sections.insert(kind, merged);
        }
        sections
    }

    fn detect_sections_by_headings(&self, text: &str) -> Sections {
        let mut sections = Sections::default();
        // "" is falsy in Python, so an empty normalized name behaves like None.
        let mut current: String = String::new();
        let mut content: Vec<&str> = Vec::new();
        for line in text.split('\n') {
            let stripped = strip(line);
            let mut heading = [
                &*HEADING_ARABIC,
                &*HEADING_ROMAN,
                &*HEADING_LETTER,
                &*HEADING_PAREN,
            ]
            .iter()
            .find_map(|re| re.captures(stripped).map(|c| c.get(2).unwrap().as_str()));
            if heading.is_none() {
                let n = clen(stripped);
                if n > 3 && n < 60 && py_isupper(stripped) {
                    heading = Some(stripped);
                }
            }
            match heading.filter(|h| !h.is_empty()) {
                Some(h) => {
                    if !current.is_empty() {
                        sections.insert(&current, strip(&content.join("\n")).to_owned());
                    }
                    current = self.normalize_section_name(h);
                    content.clear();
                }
                None if !current.is_empty() => content.push(line),
                None => {}
            }
        }
        if !current.is_empty() && !content.is_empty() {
            sections.insert(&current, strip(&content.join("\n")).to_owned());
        }
        sections
    }

    fn normalize_section_name(&self, heading: &str) -> String {
        let upper = heading.to_uppercase();
        let upper = strip(&upper);
        for (kind, _, word_re) in SECTION_REGEXES.iter() {
            if word_re.is_match(upper) {
                return (*kind).into();
            }
        }
        lazy_rx!(NUMBERING, r"^[\dIVX]+\.?\s*");
        lazy_rx!(PAREN, r"^\([^)]+\)\s*");
        lazy_rx!(PUNCT, r"[^\w\s-]");
        lazy_rx!(SEPARATORS, r"[-\s]+");
        let cleaned = NUMBERING.replacen(heading, 1, "");
        let cleaned = PAREN.replacen(&cleaned, 1, "");
        let lower = cleaned.to_lowercase();
        let cleaned = PUNCT.replace_all(strip(&lower), "");
        SEPARATORS.replace_all(&cleaned, "_").into_owned()
    }

    fn get_section<'s>(&self, sections: &'s Sections, names: &[&str]) -> &'s str {
        names
            .iter()
            .filter_map(|n| sections.get(n))
            .find(|t| !strip(t).is_empty())
            .unwrap_or("")
    }

    pub fn get_screening_input(&self, sections: &Sections) -> String {
        let mut parts = Vec::new();
        let abstract_ = self.get_section(sections, &["abstract"]);
        if !abstract_.is_empty() {
            parts.push(format!("=== ABSTRACT ===\n{abstract_}"));
        }
        let conclusion = self.get_section(sections, &["conclusion"]);
        if !conclusion.is_empty() {
            parts.push(format!("=== CONCLUSION ===\n{conclusion}"));
        }
        if parts.is_empty() {
            let full_text = sections.get_or_empty("full_text");
            let words: Vec<&str> = full_text
                .split(py_space)
                .filter(|w| !w.is_empty())
                .collect();
            if words.len() > 1000 {
                let first = words[..500].join(" ");
                let last = words[words.len() - 500..].join(" ");
                return format!("=== BEGINNING ===\n{first}\n\n=== END ===\n{last}");
            }
            return full_text.into();
        }
        parts.join("\n\n")
    }

    pub fn get_visual_input(&self, sections: &Sections) -> Vec<String> {
        let available: Vec<String> = [
            "results",
            "results_discussion",
            "method",
            "experimental",
            "materials_methods",
            "discussion",
        ]
        .iter()
        .filter(|n| sections.get(n).is_some_and(|t| !strip(t).is_empty()))
        .map(|n| (*n).into())
        .collect();
        if available.is_empty() {
            sections.keys().map(Into::into).collect()
        } else {
            available
        }
    }

    pub fn get_recipe_input(&self, sections: &Sections) -> String {
        let mut text = self.get_section(
            sections,
            &["method", "experimental", "materials_methods", "background"],
        );
        if text.is_empty()
            && let Some((_, t)) = sections.0.iter().find(|(name, _)| {
                let lower = name.to_lowercase();
                ["method", "experimental", "procedure", "material"]
                    .iter()
                    .any(|k| lower.contains(k))
            })
        {
            text = t;
        }
        if text.is_empty() {
            text = sections.get_or_empty("full_text");
        }
        text.into()
    }

    pub fn get_deepdive_input(&self, sections: &Sections) -> String {
        let mut parts = Vec::new();
        let intro = self.get_section(sections, &["introduction", "background"]);
        if !intro.is_empty() {
            parts.push(format!("=== INTRODUCTION ===\n{intro}"));
        }
        let results = self.get_section(sections, &["results_discussion", "results", "discussion"]);
        if !results.is_empty() {
            parts.push(format!("=== RESULTS & DISCUSSION ===\n{results}"));
        }
        if parts.is_empty() {
            return sections.get_or_empty("full_text").into();
        }
        parts.join("\n\n")
    }

    pub fn get_references_text(&self, sections: &Sections) -> String {
        let composed;
        let mut source = match sections.get("full_text").filter(|t| !t.is_empty()) {
            Some(t) => t,
            None => {
                composed = self.compose_reference_source_text(sections);
                composed.as_str()
            }
        };
        let heading = REFERENCES_HEADING.find(source);
        if let Some(h) = heading {
            source = &source[h.end()..];
        }
        source = before_first(&REFERENCES_TERMINATOR, source);
        let candidates = self.extract_reference_entries(source);
        if candidates.len() >= 3 {
            return candidates
                .iter()
                .map(|(n, e)| format!("{n}. {e}"))
                .collect::<Vec<_>>()
                .join("\n");
        }
        let text = if heading.is_some() {
            source
        } else {
            self.get_section(sections, &["references"])
        };
        let text = before_first(&REFERENCES_TERMINATOR, text);
        let text = PAGE_MARKER.replace_all(text, "\n");
        let kept: Vec<&str> = PARAGRAPH_BREAK
            .split(&text)
            .filter(|p| !PAGE_LABEL.is_match(p))
            .collect();
        strip(&kept.join("\n\n")).into()
    }

    pub fn get_body_text_without_references(&self, sections: &Sections) -> String {
        let parts: Vec<&str> = sections
            .0
            .iter()
            .filter(|(k, _)| k != "references" && k != "full_text")
            .map(|(_, v)| v.as_str())
            .collect();
        if parts.is_empty() {
            let full = sections.get_or_empty("full_text");
            if !full.is_empty() {
                let lower: Vec<char> = full.to_lowercase().chars().collect();
                let n = clen(full) as f64;
                for marker in ["references", "bibliography", "citations"] {
                    let m: Vec<char> = marker.chars().collect();
                    let idx = (0..=lower.len().saturating_sub(m.len()))
                        .rev()
                        .find(|&i| lower.len() >= m.len() && lower[i..i + m.len()] == m[..]);
                    if let Some(idx) = idx.filter(|&i| i as f64 > n * 0.5) {
                        return head(full, idx).into();
                    }
                }
            }
            return self.trim_reference_tail(full);
        }
        self.trim_reference_tail(&parts.join("\n\n"))
    }

    fn compose_reference_source_text(&self, sections: &Sections) -> String {
        let parts: Vec<&str> = sections
            .0
            .iter()
            .filter(|(k, v)| k != "full_text" && !strip(v).is_empty())
            .map(|(_, v)| v.as_str())
            .collect();
        if parts.is_empty() {
            sections.get_or_empty("full_text").into()
        } else {
            parts.join("\n\n")
        }
    }

    /// `(str(int(number)), entry)` sorted by number.
    fn extract_reference_entries(&self, text: &str) -> Vec<(String, String)> {
        let cleaned = PAGE_MARKER.replace_all(text, "\n");
        if strip(&cleaned).is_empty() {
            return Vec::new();
        }
        let mut entries: Vec<(String, String)> = Vec::new();
        let mut seen: BTreeSet<String> = BTreeSet::new();
        let mut current: Option<String> = None;
        let mut lines: Vec<String> = Vec::new();
        let mut flush = |current: &mut Option<String>,
                         lines: &mut Vec<String>,
                         entries: &mut Vec<(String, String)>| {
            if let Some(num) = current.take() {
                let merged = collapse_ws(&lines.join(" "));
                if !merged.is_empty()
                    && self.looks_like_reference_entry(&merged)
                    && !seen.contains(&num)
                {
                    seen.insert(num.clone());
                    entries.push((num, merged));
                }
            }
            lines.clear();
        };
        // Empty lines are skipped, so splitting each break char alone equals splitlines().
        for raw in cleaned.split(is_line_break) {
            let line = strip(raw);
            if line.is_empty() {
                continue;
            }
            if REFERENCE_TERMINATOR.is_match(line) {
                let stop = entries.len() >= 3;
                flush(&mut current, &mut lines, &mut entries);
                if stop {
                    break;
                }
                continue;
            }
            if let Some(c) = REFERENCE_START.captures(line) {
                flush(&mut current, &mut lines, &mut entries);
                current = Some(py_int(c.get(1).or(c.get(2)).unwrap().as_str()));
                lines = vec![strip(c.get(3).unwrap().as_str()).to_owned()];
                continue;
            }
            if current.is_some() {
                lines.push(line.to_owned());
            }
        }
        flush(&mut current, &mut lines, &mut entries);
        entries.sort_by(|a, b| int_key(&a.0).cmp(&int_key(&b.0)));
        entries
    }

    fn looks_like_reference_entry(&self, text: &str) -> bool {
        let normalized = collapse_ws(text);
        if clen(&normalized) < 30 || !REFERENCE_SIGNAL.is_match(&normalized) {
            return false;
        }
        let lower = normalized.to_lowercase();
        ![
            "introduction",
            "method",
            "results",
            "discussion",
            "conclusion",
        ]
        .iter()
        .any(|p| lower.starts_with(p))
    }

    fn trim_reference_tail(&self, text: &str) -> String {
        let total = clen(text) as f64;
        let (mut chars, mut byte) = (0usize, 0usize);
        for m in REFERENCE_LINE.find_iter(text) {
            chars += clen(&text[byte..m.start()]);
            byte = m.start();
            if (chars as f64) < total * 0.15 {
                continue;
            }
            if self.extract_reference_entries(&text[m.start()..]).len() >= 3 {
                return rstrip(&text[..m.start()]).into();
            }
        }
        text.into()
    }
}

fn truncate_text(text: &str, limit: usize) -> String {
    if clen(text) <= limit {
        return text.into();
    }
    format!("{}\n\n...(중략)...", rstrip(head(text, limit)))
}

fn compose_section_context(
    sections: &Sections,
    names: &[&str],
    fallback: &str,
    limit: usize,
) -> String {
    let parts: Vec<String> = names
        .iter()
        .filter_map(|n| {
            let t = strip(sections.get_or_empty(n));
            (!t.is_empty()).then(|| format!("=== {} ===\n{t}", n.to_uppercase()))
        })
        .collect();
    let joined = parts.join("\n\n");
    truncate_text(if joined.is_empty() { fallback } else { &joined }, limit)
}

fn join_nonempty(parts: &[&str], fallback: &str) -> String {
    let joined = parts
        .iter()
        .filter(|p| !p.is_empty())
        .copied()
        .collect::<Vec<_>>()
        .join("\n\n");
    if joined.is_empty() {
        fallback.into()
    } else {
        joined
    }
}

fn build_phase_inputs(splitter: &SectionSplitter, sections: &Sections, full_text: &str) -> Value {
    let mut phase = sections.clone();
    if phase.get("full_text").is_none() {
        phase.insert("full_text", full_text.into());
    }
    let screening = truncate_text(&splitter.get_screening_input(&phase), 5000);
    let citation_body = splitter.get_body_text_without_references(&phase);
    let citation_references = splitter.get_references_text(&phase);
    let visual_parts: Vec<String> = splitter
        .get_visual_input(&phase)
        .iter()
        .take(4)
        .filter_map(|name| {
            let t = strip(phase.get_or_empty(name));
            (!t.is_empty()).then(|| format!("=== {} ===\n{t}", name.to_uppercase()))
        })
        .collect();
    let visual_joined = visual_parts.join("\n\n");
    let visual = truncate_text(
        if visual_joined.is_empty() {
            full_text
        } else {
            &visual_joined
        },
        3500,
    );
    let recipe_input = splitter.get_recipe_input(&phase);
    let deep_dive_input = splitter.get_deepdive_input(&phase);
    let recipe = truncate_text(
        &join_nonempty(
            &[&recipe_input, &truncate_text(&deep_dive_input, 3000)],
            full_text,
        ),
        14000,
    );
    let deep_dive = truncate_text(&deep_dive_input, 7000);
    let visualization = truncate_text(
        &join_nonempty(
            &[
                &screening,
                &truncate_text(&recipe_input, 2200),
                &truncate_text(&deep_dive_input, 2200),
            ],
            full_text,
        ),
        4200,
    );
    let chat = compose_section_context(
        &phase,
        &[
            "abstract",
            "introduction",
            "background",
            "method",
            "experimental",
            "materials_methods",
            "results_discussion",
            "results",
            "discussion",
            "conclusion",
        ],
        full_text,
        7000,
    );
    let figure_detail = compose_section_context(
        &phase,
        &[
            "method",
            "experimental",
            "materials_methods",
            "results_discussion",
            "results",
            "discussion",
        ],
        full_text,
        9000,
    );
    json!({
        "screening": screening,
        "citation_body": citation_body,
        "citation_references": citation_references,
        "visual": visual,
        "recipe": recipe,
        "deep_dive": deep_dive,
        "visualization": visualization,
        "chat": chat,
        "figure_detail": figure_detail,
    })
}

const QUANT_UNITS: &str = concat!(
    r"ppm|ppb|nm|um|μm|mm|cm|m|km|mg|ug|μg|g|kg|ng|mL|uL|μL|L|",
    r"M|mM|uM|μM|nM|pM|V|mV|A|mA|uA|μA|W|mW|kW|Hz|kHz|MHz|GHz|THz|",
    r"s|ms|us|μs|min|h|hr|hrs|day|days|K|C|degC|°C|Pa|kPa|MPa|bar|Torr|atm|",
    r"rpm|eV|meV|dB|mol|mmol|umol|μmol|mAh/g|A/g|W/kg|Wh/kg|mS/cm|S/cm"
);

/// Python's `(?P<unit>%|wt%|at%|ppm|...)\b`: the `%` units come first and need a
/// following word char, the rest a following non-word char or the end.
static QUANT: LazyLock<Regex> = LazyLock::new(|| {
    rx(&format!(
        r"(?i)(?P<value>\d+(?:\.\d+)?(?:\s*[x×]\s*\d+(?:\.\d+)?)?)\s*(?:(?P<u1>%|wt%|at%)<WC>|(?P<u2>{QUANT_UNITS})(?:<NW>|\z))"
    ))
});

fn split_sentences(text: &str) -> Vec<&str> {
    let stripped = strip(text);
    let mut parts = Vec::new();
    let mut start = 0;
    let mut chars = stripped.char_indices().peekable();
    while let Some((i, c)) = chars.next() {
        if matches!(c, '.' | '?' | '!') && chars.peek().is_some_and(|(_, n)| py_space(*n)) {
            parts.push(&stripped[start..i + 1]);
            while chars.peek().is_some_and(|(_, n)| py_space(*n)) {
                chars.next();
            }
            start = chars.peek().map_or(stripped.len(), |(j, _)| *j);
        }
    }
    parts.push(&stripped[start..]);
    parts.retain(|p| !p.is_empty());
    parts
}

fn guess_parameter_name(sentence: &str, match_start: usize) -> String {
    lazy_rx!(TOKEN, r"[A-Za-z][A-Za-z0-9_\-/]*");
    let prefix = strip(&sentence[..match_start]);
    let tokens: Vec<&str> = TOKEN.find_iter(prefix).map(|m| m.as_str()).collect();
    if tokens.is_empty() {
        return "unknown".into();
    }
    tokens[tokens.len().saturating_sub(4)..]
        .join(" ")
        .to_lowercase()
}

fn extract_quantitative_candidates(sections: &Sections) -> Value {
    let mut candidates = Vec::new();
    let mut seen: BTreeSet<(String, String, String, String)> = BTreeSet::new();
    for (section, text) in &sections.0 {
        if text.is_empty() || section == "references" {
            continue;
        }
        for sentence in split_sentences(text) {
            let mut at = 0;
            while let Some(c) = QUANT.captures_at(sentence, at) {
                let unit_m = c.name("u1").or(c.name("u2")).unwrap();
                at = unit_m.end(); // the guard char is not part of Python's match
                let start = c.get(0).unwrap().start();
                let value = strip(c.name("value").unwrap().as_str()).to_owned();
                let unit = strip(unit_m.as_str()).to_owned();
                let name_guess = guess_parameter_name(sentence, start);
                let key = (
                    name_guess.clone(),
                    value.clone(),
                    unit.clone(),
                    section.clone(),
                );
                if !seen.insert(key) {
                    continue;
                }
                candidates.push(json!({
                    "name_guess": name_guess,
                    "value": value,
                    "unit": unit,
                    "section": section,
                    "snippet": head(strip(sentence), 240),
                }));
            }
        }
    }
    Value::Array(candidates)
}

/// Port of `build_document_context_from_text`.
pub fn build_document_context_from_text(
    full_text: &str,
    pdf_signature: Option<Value>,
    parser_version: &str,
) -> Value {
    let splitter = SectionSplitter;
    let sections = splitter.split(full_text);
    let signature = pdf_signature
        .filter(truthy)
        .unwrap_or_else(|| json!({"pdf_mtime_ns": 0, "pdf_size": 0}));
    // sections is never empty, so Python's `sections or {"full_text": ...}` is moot.
    json!({
        "pdf_signature": signature,
        "parser_version": parser_version,
        "context_builder_version": CONTEXT_BUILDER_VERSION,
        "sections": sections.to_json(),
        "phase_inputs": build_phase_inputs(&splitter, &sections, full_text),
        "quantitative_candidates": extract_quantitative_candidates(&sections),
        "full_text": full_text,
    })
}

/// Identify the bytes and range actually supplied to the model.
pub fn source_signature(text: &str, pdf_sha256: Option<&str>, detail: &str) -> String {
    if let Some(sha) = pdf_sha256.filter(|s| !s.is_empty()) {
        return format!("pdf:{sha}:{detail}");
    }
    let digest: String = Sha256::digest(text.as_bytes())
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect();
    format!("text:{digest}:0:{}", clen(text))
}

/// Python `f"{n:,}"`.
fn commas(n: i64) -> String {
    let digits = n.unsigned_abs().to_string();
    let mut out = String::new();
    for (i, d) in digits.chars().enumerate() {
        if i > 0 && (digits.len() - i).is_multiple_of(3) {
            out.push(',');
        }
        out.push(d);
    }
    if n < 0 { format!("-{out}") } else { out }
}

/// Describe supplied source material without claiming scientific correctness.
pub fn input_coverage(text: &str, pdf_sha256: Option<&str>, text_limit: Option<i64>) -> Value {
    if let Some(sha) = pdf_sha256.filter(|s| !s.is_empty()) {
        return json!({"mode": "pdf", "status": "provided_pdf", "missing": [], "pdf_sha256": sha});
    }
    let n = clen(text) as i64;
    let mut missing = vec![
        "원본 PDF를 제공하지 못해 수식과 그림의 판독 범위를 확인하지 못했습니다".to_owned(),
        format!(
            "제공한 텍스트는 {}자이며 원문 대비 누락 범위는 확인되지 않았습니다",
            commas(n)
        ),
    ];
    if let Some(limit) = text_limit.filter(|&l| n >= l) {
        missing.push(format!(
            "{}자 입력 제한이 적용되어 원문 뒷부분의 포함 여부를 확인하지 못했습니다",
            commas(limit)
        ));
    }
    json!({"mode": "text", "status": "partial", "missing": missing, "pdf_sha256": null})
}

/// Python `f"{value}"` for a plan field.
// shortcut: floats, lists and dicts use JSON text, not Python repr; plans only carry strings.
fn py_format(v: Option<&Value>) -> String {
    match v {
        None => String::new(),
        Some(Value::String(s)) => s.clone(),
        Some(Value::Null) => "None".into(),
        Some(Value::Bool(b)) => if *b { "True" } else { "False" }.into(),
        Some(other) => other.to_string(),
    }
}

// Python's rf-string turns `[A-Z]{2}` into `[A-Z]2`; kept for parity.
fn caption_search(n: &str) -> Regex {
    rx(&format!(
        r"(?i)(?:\A|<NW>)(?P<m>Table\s+{n}\s*(?::|\.|\(continued\)|\s+(?-i:[A-Z])2))"
    ))
}

fn caption_match(n: &str) -> Regex {
    rx(&format!(
        r"(?i)\ATable\s+{n}\s*(?::|\.|\(continued\)|\s+(?-i:[A-Z])2)"
    ))
}

fn tag_re(n: &str) -> Regex {
    rx(&format!(r"\\tag\{{{n}\}}|(?m:^.*(?:\$|=).*\({n}\)\s*$)"))
}

/// Select referenced source pages, keeping formulas and their local definitions.
pub fn select_visual_source(plan: &Value, full_text: &str, limit: usize) -> Value {
    lazy_rx!(
        TABLE_REF,
        r"(?i)(?:\A|<NW>)(?P<m>Table\s+(?P<g>\d+|[IVXLCDM]+))(?:<NW>|\z)"
    );
    lazy_rx!(
        EQUATION_REF,
        r"(?i)(?:\A|<NW>)(?P<m>(?:equations?|eqs?\.?)\s*(?P<g>[\d(),\s–−-]+))"
    );
    lazy_rx!(EQUATION_NUM, r"([0-9]+)(?:\s*[-–−]\s*([0-9]+))?");
    lazy_rx!(PAGE_SPLIT, r"(?m)^--- Page (\d+) ---\s*$");
    lazy_rx!(TERM, r"[A-Za-z][A-Za-z_]{3,}");
    lazy_rx!(TABLE_ROW_END, r"(?m)^\|[^\n]*\s*$");
    lazy_rx!(STARTS_WITH_ROW, r"\A\s*\|");
    lazy_rx!(PRECEDING_ROWS, r"(?m)((?:^\|[^\n]*\n)+)\s*$");
    lazy_rx!(NEXT_TABLE, r"(?i)(?:\A|<NW>)(?P<m>Table\s+\d+\s*[:.])");
    lazy_rx!(ROW_START, r"(?m)^\|");

    let request = format!(
        "{}\n{}",
        py_format(plan.get("title")),
        py_format(plan.get("description"))
    );
    let tables: BTreeSet<String> = py_iter(&TABLE_REF, &request)
        .iter()
        .map(|c| c["g"].to_owned())
        .collect();
    let mut equations: BTreeSet<String> = BTreeSet::new();
    for refs in py_iter(&EQUATION_REF, &request) {
        for m in EQUATION_NUM.captures_iter(&refs["g"]) {
            // shortcut: numbers beyond u128 are skipped; Python ints are unbounded.
            let (Ok(start), Ok(end)) = (
                m[1].parse::<u128>(),
                m.get(2).map_or(&m[1], |e| e.as_str()).parse::<u128>(),
            ) else {
                continue;
            };
            equations.extend((start..=end.min(start.saturating_add(20))).map(|i| i.to_string()));
        }
    }
    // (page, text); page is None for paragraph chunks.
    let mut source_pages: Vec<(Option<u64>, &str)> = Vec::new();
    let marks: Vec<Captures> = PAGE_SPLIT.captures_iter(full_text).collect();
    for (k, c) in marks.iter().enumerate() {
        let end = marks
            .get(k + 1)
            .map_or(full_text.len(), |n| n.get(0).unwrap().start());
        // shortcut: page labels beyond u64 saturate.
        let page = py_int(&c[1]).parse::<u64>().unwrap_or(u64::MAX);
        source_pages.push((Some(page), &full_text[c.get(0).unwrap().end()..end]));
    }
    let chunk_store: Vec<String>;
    if source_pages.is_empty() {
        let mut chunks: Vec<String> = Vec::new();
        let mut chunk = String::new();
        let mut chunk_len = 0;
        for block in PARAGRAPH_BREAK.split(full_text) {
            let block_len = clen(block);
            if !chunk.is_empty()
                && chunk_len + block_len > 4000
                && chunk.matches("$$").count().is_multiple_of(2)
            {
                chunks.push(std::mem::take(&mut chunk));
                chunk_len = 0;
            }
            if !chunk.is_empty() {
                chunk.push_str("\n\n");
                chunk_len += 2;
            }
            chunk.push_str(block);
            chunk_len += block_len;
        }
        if !chunk.is_empty() {
            chunks.push(chunk);
        }
        chunk_store = chunks;
        source_pages = chunk_store.iter().map(|c| (None, c.as_str())).collect();
    }
    let stop = [
        "table",
        "equation",
        "equations",
        "figure",
        "section",
        "with",
        "from",
        "this",
        "that",
    ];
    let request_lower = request.to_lowercase();
    let terms: BTreeSet<&str> = TERM
        .find_iter(&request_lower)
        .map(|m| m.as_str())
        .filter(|t| !stop.contains(t))
        .collect();
    let captions: Vec<(String, Regex, Regex)> = tables
        .iter()
        .map(|n| (n.clone(), caption_search(n), caption_match(n)))
        .collect();
    let tags: Vec<(String, Regex)> = equations.iter().map(|n| (n.clone(), tag_re(n))).collect();

    let mut required: BTreeSet<usize> = BTreeSet::new();
    let mut neighbors: BTreeSet<usize> = BTreeSet::new();
    let mut ranked: Vec<(usize, usize)> = Vec::new();
    for (index, (_, text)) in source_pages.iter().enumerate() {
        let refs = captions
            .iter()
            .filter(|(_, re, _)| py_search(re, text).is_some())
            .count();
        let tag_hits = tags.iter().filter(|(_, re)| re.is_match(text)).count();
        if refs > 0 || tag_hits > 0 {
            required.insert(index);
            if refs > 0 && index > 0 && TABLE_ROW_END.is_match(source_pages[index - 1].1) {
                required.insert(index - 1);
            }
            // Keep continued rows and definitions on the next page.
            if index + 1 < source_pages.len()
                && (tag_hits > 0 || STARTS_WITH_ROW.is_match(source_pages[index + 1].1))
            {
                (if refs > 0 {
                    &mut required
                } else {
                    &mut neighbors
                })
                .insert(index + 1);
            }
        }
        let lower = text.to_lowercase();
        let score =
            refs * 100 + tag_hits * 80 + terms.iter().filter(|t| lower.contains(*t)).count();
        if score > 0 {
            ranked.push((score, index));
        }
    }
    ranked.sort_by(|a, b| b.cmp(a));
    let mut chosen: Vec<usize> = required.iter().copied().collect();
    chosen.extend(neighbors.difference(&required));
    chosen.extend(
        ranked
            .iter()
            .map(|(_, i)| *i)
            .filter(|i| !required.contains(i) && !neighbors.contains(i))
            .take(4),
    );
    if chosen.is_empty() && tables.is_empty() && equations.is_empty() {
        chosen = (0..source_pages.len().min(4)).collect();
    }
    let mut selected: Vec<String> = Vec::new();
    let mut size = 0;
    let mut omitted: Vec<Value> = Vec::new();
    for index in chosen {
        let (page, text) = source_pages[index];
        let label = match page {
            Some(p) if p != 0 => format!("PDF page {p} (extracted label; position unverified)"),
            _ => "Text excerpt (PDF page unverified)".into(),
        };
        let excerpt = format!("--- {label} ---\n{}", strip(text));
        let excerpt_len = clen(&excerpt);
        if size + excerpt_len + 2 > limit {
            if required.contains(&index) {
                omitted.push(page.map_or(Value::Null, Value::from));
            }
            continue; // Never cut a formula or a row in the middle.
        }
        selected.push(excerpt);
        size += excerpt_len + 2;
    }
    let context = selected.join("\n\n");
    let mut missing: Vec<String> = Vec::new();
    for (n, search, at_start) in &captions {
        let mut blocks: Vec<&str> = Vec::new();
        for (i, (_, text)) in source_pages.iter().enumerate() {
            let Some(m) = py_search(search, text) else {
                continue;
            };
            if !context.contains(strip(text)) {
                continue;
            }
            if let Some(rows) = PRECEDING_ROWS.captures(&text[..m.start()]) {
                blocks.push(rows.get(1).unwrap().as_str());
            } else if i > 0
                && at_start.is_match(strip(text))
                && context.contains(strip(source_pages[i - 1].1))
            {
                blocks.push(source_pages[i - 1].1);
            }
            let rest = &text[m.end()..];
            blocks.push(py_search(&NEXT_TABLE, rest).map_or(rest, |t| &rest[..t.start()]));
            if let Some((_, following)) = source_pages.get(i + 1)
                && STARTS_WITH_ROW.is_match(following)
                && context.contains(strip(following))
            {
                blocks.push(following);
            }
        }
        if blocks.is_empty() || !ROW_START.is_match(&blocks.join("\n")) {
            missing.push(n.clone());
        }
    }
    let missing_equations: Vec<String> = tags
        .iter()
        .filter(|(_, re)| !re.is_match(&context))
        .map(|(n, _)| n.clone())
        .collect();
    let signature = source_signature(&context, None, "high");
    let status = if !missing.is_empty() {
        "missing_table_evidence"
    } else if !missing_equations.is_empty() || !omitted.is_empty() {
        "incomplete_evidence"
    } else if !context.is_empty() {
        "selected_text"
    } else {
        "unverified"
    };
    json!({
        "version": VISUAL_SOURCE_VERSION,
        "text": context,
        "signature": signature,
        "missing_tables": missing,
        "missing_equations": missing_equations,
        "omitted_required_pages": omitted,
        "transcription_verified": false,
        "status": status,
    })
}
