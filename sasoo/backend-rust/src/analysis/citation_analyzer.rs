//! Port of `services/citation_analyzer.py`: local reference parsing and citation counts.
//! Positions are byte offsets; Python slices by code point, so `[:n]` uses `chars().take(n)`.
//! Python `\s` (str.isspace) also matches U+001C..U+001F, so patterns spell it `[\s\x1c-\x1f]`.
use crate::types::Json;
use regex::Regex;
use serde_json::{Map, Value, json};
use std::{
    collections::{HashMap, HashSet},
    sync::LazyLock,
};

fn re(pattern: &str) -> Regex {
    Regex::new(pattern).expect("static citation pattern")
}

static JOURNAL: LazyLock<Regex> = LazyLock::new(|| {
    re(r"(?i)\b(?:Nature|Science|Cell|Phys\.[\s\x1c-\x1f]*Rev(?:[\s\x1c-\x1f]+\w+)?|Adv\.[\s\x1c-\x1f]*Mater|ACS[\s\x1c-\x1f]+\w+|IEEE(?:[\s\x1c-\x1f]+\w+)?|Opt\.[\s\x1c-\x1f]*Express|Biomed\.[\s\x1c-\x1f]*Opt\.[\s\x1c-\x1f]*Express|Biomedical[\s\x1c-\x1f]+optics[\s\x1c-\x1f]+express|Opt\.[\s\x1c-\x1f]*Eng\.?|Astron\.[\s\x1c-\x1f]*Astrophys\.?|J\.[\s\x1c-\x1f]*Biophotonics|J\.[\s\x1c-\x1f]*Opt\.[\s\x1c-\x1f]*Soc\.[\s\x1c-\x1f]*Am\.[\s\x1c-\x1f]*[AB]?|J\.[\s\x1c-\x1f]*Astron\.[\s\x1c-\x1f]*Telesc\.[\s\x1c-\x1f]*Instrum\.[\s\x1c-\x1f]*Syst\.?|Appl\.[\s\x1c-\x1f]*\w+|Proc\.[\s\x1c-\x1f]*SPIE|Ann\.[\s\x1c-\x1f]*\w+|Light:[\s\x1c-\x1f]*\w+|Optica|Photonics|Laser|Chem\.[\s\x1c-\x1f]*\w+|Angew\.[\s\x1c-\x1f]*\w+|PNAS|PLoS|BMC[\s\x1c-\x1f]+\w+|Nat\.[\s\x1c-\x1f]*\w+)\b[^,;.]*")
});
static BRACKET_CITE: LazyLock<Regex> = LazyLock::new(|| re(r"\[\d+(?:[,\s\x1c-\x1f\-\x{2013}]+\d+)*\]"));
static AUTHOR_YEAR_CITE: LazyLock<Regex> = LazyLock::new(|| {
    re(r"\([A-Z][a-z]+(?:[\s\x1c-\x1f]+(?:et[\s\x1c-\x1f]+al\.|and[\s\x1c-\x1f]+[A-Z][a-z]+))?,?[\s\x1c-\x1f]*\d{4}\)")
});
static BRACKET_NUM: LazyLock<Regex> = LazyLock::new(|| re(r"\[(\d+)\]"));
static CITE_GROUP: LazyLock<Regex> = LazyLock::new(|| re(r"\[([\d,\s\x1c-\x1f\-\x{2013}]+)\]"));
static COMMA_SPACE: LazyLock<Regex> = LazyLock::new(|| re(r"[,\s\x1c-\x1f]+"));
static RANGE: LazyLock<Regex> = LazyLock::new(|| re(r"^(\d+)[\-\x{2013}](\d+)"));
static DIGITS: LazyLock<Regex> = LazyLock::new(|| re(r"^\d+$"));
static SPACES: LazyLock<Regex> = LazyLock::new(|| re(r"[\s\x1c-\x1f]+"));
static YEAR: LazyLock<Regex> = LazyLock::new(|| re(r"\b((?:19|20)\d{2})\b"));
static QUOTED: LazyLock<Regex> = LazyLock::new(|| re("[\"\u{201c}](.+?)[\"\u{201d}]"));
static INITIAL_DOT: LazyLock<Regex> = LazyLock::new(|| re(r"\b[A-Z]\."));
static ET_AL: LazyLock<Regex> = LazyLock::new(|| re(r"(?i)\bet[\s\x1c-\x1f]+al\b"));
static ET_AL_TAIL: LazyLock<Regex> = LazyLock::new(|| re(r"(?i)[\s\x1c-\x1f]*et[\s\x1c-\x1f]+al\.?[\s\x1c-\x1f]*$"));
static AUTHOR_SPLIT: LazyLock<Regex> = LazyLock::new(|| {
    re(r"[\s\x1c-\x1f]+and[\s\x1c-\x1f]+|[\s\x1c-\x1f]*&[\s\x1c-\x1f]*|[\s\x1c-\x1f]*;[\s\x1c-\x1f]*")
});
static INITIAL_TOKEN: LazyLock<Regex> = LazyLock::new(|| re(r"^[A-Z]\.?$"));
static NAME_TOKEN: LazyLock<Regex> =
    LazyLock::new(|| re(r"^[A-Za-z\x{C0}-\x{24F}][A-Za-z\x{C0}-\x{24F}'\x{2019}\-]+$"));
static BLANK_LINES: LazyLock<Regex> = LazyLock::new(|| re(r"\n{2,}"));
static PAPER_AUTHOR_SPLIT: LazyLock<Regex> = LazyLock::new(|| re(r"[,;&]+"));
static ND: LazyLock<Regex> = LazyLock::new(|| re(r"^\d$"));

const NOT_A_CITATION_WORD: &[&str] = &[
    "table", "fig", "figs", "figure", "eq", "eqs", "equation", "section", "sec", "ref", "refs", "chapter",
    "appendix", "algorithm", "step", "phase", "level", "type", "class", "group", "case", "mode", "model",
    "method", "sample", "test", "exp", "part", "panel", "note", "line", "row", "col", "column", "item", "task",
    "stage", "round", "run", "set", "version",
];
const SUPERSCRIPT_BRACKET_MAX: usize = 5;

/// `str.isspace()`.
pub fn is_py_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

pub fn py_strip(text: &str) -> &str {
    text.trim_matches(is_py_space)
}

fn strip_chars<'a>(text: &'a str, chars: &str) -> &'a str {
    text.trim_matches(|c| chars.contains(c))
}

fn prefix(text: &str, count: usize) -> String {
    text.chars().take(count).collect()
}

fn word_count(text: &str) -> usize {
    text.split(is_py_space).filter(|w| !w.is_empty()).count()
}

/// Python `\d` (Unicode Nd).
fn is_d(c: char) -> bool {
    c.is_ascii_digit() || (!c.is_ascii() && ND.is_match(c.encode_utf8(&mut [0; 4])))
}

/// `int(s)` for a digit string. shortcut: non-ASCII Nd digits return None (Python converts
/// them) and values past u64 saturate (Python ints are unbounded); PDF reference numbers are ASCII.
fn py_int(text: &str) -> Option<u64> {
    if text.is_empty() || !text.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    Some(text.parse().unwrap_or(u64::MAX))
}

#[derive(Clone, Default)]
struct ParsedRef {
    ref_id: String,
    ref_num: u64,
    authors: String,
    title: String,
    journal: String,
    year: Option<u64>,
    raw_text: String,
}

#[derive(Clone)]
struct Context {
    sentence: String,
    section: String,
}

struct Entry {
    reference: ParsedRef,
    count: usize,
    contexts: Vec<Context>,
}

pub fn detect_citation_style(body: &str) -> &'static str {
    if BRACKET_CITE.find_iter(body).count() >= AUTHOR_YEAR_CITE.find_iter(body).count() {
        "numbered"
    } else {
        "author_year"
    }
}

/// `re.findall(r'\[(\d+)\]\s*(.+?)(?=\[\d+\]|\Z)', text, re.DOTALL)`.
fn bracket_matches(text: &str) -> Vec<(String, String)> {
    let marks: Vec<(usize, usize, String)> =
        BRACKET_NUM.captures_iter(text).map(|c| (c.get(0).unwrap().start(), c.get(0).unwrap().end(), c[1].to_owned())).collect();
    let mut out = Vec::new();
    let mut pos = 0;
    for (i, (start, end, num)) in marks.iter().enumerate() {
        if *start < pos {
            continue;
        }
        let ws_end = end + text[*end..].find(|c| !is_py_space(c)).unwrap_or(text.len() - end);
        let content = if ws_end < text.len() {
            ws_end
        } else if ws_end > *end {
            text[..ws_end].char_indices().next_back().map_or(ws_end, |(i, _)| i)
        } else {
            continue; // `[n]` at the very end: `.+?` has nothing to take.
        };
        let stop = marks[i + 1..].iter().find(|m| m.0 > content).map_or(text.len(), |m| m.0);
        out.push((num.clone(), text[content..stop].to_owned()));
        pos = stop;
    }
    out
}

/// `re.findall(r'(?:^|\n)\s*(\d+)\.\s+(.+?)(?=\n\s*\d+\.|\Z)', text, re.DOTALL)`.
fn dot_matches(text: &str) -> Vec<(String, String)> {
    let chars: Vec<char> = text.chars().collect();
    let n = chars.len();
    let skip_ws = |mut i: usize| {
        while i < n && is_py_space(chars[i]) {
            i += 1;
        }
        i
    };
    let digits_end = |mut i: usize| {
        while i < n && is_d(chars[i]) {
            i += 1;
        }
        i
    };
    let lookahead = |e: usize| {
        if chars.get(e) != Some(&'\n') {
            return false;
        }
        let d = skip_ws(e + 1);
        let de = digits_end(d);
        de > d && chars.get(de) == Some(&'.')
    };
    let attempt = |p: usize, from_start: bool| -> Option<(String, String, usize)> {
        let after = if from_start { p } else if chars.get(p) == Some(&'\n') { p + 1 } else { return None };
        let d = skip_ws(after);
        let de = digits_end(d);
        if de == d || chars.get(de) != Some(&'.') {
            return None;
        }
        let ws = de + 1;
        let ws_end = skip_ws(ws);
        if ws_end == ws {
            return None;
        }
        let content = if ws_end < n { ws_end } else if ws_end - ws >= 2 { ws_end - 1 } else { return None };
        let stop = (content + 1..n).find(|&e| lookahead(e)).unwrap_or(n);
        Some((chars[d..de].iter().collect(), chars[content..stop].iter().collect(), stop))
    };
    let mut out = Vec::new();
    let mut p = 0;
    while p <= n {
        match attempt(p, p == 0).or_else(|| if p == 0 { attempt(0, false) } else { None }) {
            Some((num, body, stop)) => {
                out.push((num, body));
                p = if stop == p { p + 1 } else { stop };
            }
            None => p += 1,
        }
    }
    out
}

fn duplicate_ratio(matches: &[(String, String)]) -> f64 {
    let nums: Vec<Option<u64>> = matches.iter().map(|(n, _)| py_int(n)).collect();
    let unique: HashSet<&Option<u64>> = nums.iter().collect();
    1.0 - unique.len() as f64 / nums.len() as f64
}

fn parse_references(text: &str) -> Vec<ParsedRef> {
    if py_strip(text).is_empty() {
        return Vec::new();
    }
    let candidates: Vec<Vec<(String, String)>> =
        [bracket_matches(text), dot_matches(text)].into_iter().filter(|m| m.len() >= 3).collect();
    if !candidates.is_empty() {
        let mut best = &candidates[0];
        for candidate in &candidates[1..] {
            if duplicate_ratio(candidate) < duplicate_ratio(best) {
                best = candidate;
            }
        }
        return best
            .iter()
            .map(|(num, body)| {
                let mut r = parse_single_reference(py_strip(body), py_int(num).unwrap_or(0));
                r.ref_id = format!("[{num}]");
                r
            })
            .collect();
    }
    let stripped = py_strip(text);
    let mut lines: Vec<&str> = BLANK_LINES.split(stripped).collect();
    if lines.len() < 3 {
        lines = stripped.split('\n').collect();
    }
    let mut refs = Vec::new();
    for (i, line) in lines.iter().enumerate() {
        let line = py_strip(line);
        if line.chars().count() < 10 {
            continue;
        }
        let mut r = parse_single_reference(line, i as u64 + 1);
        r.ref_id = format!("[{}]", i + 1);
        refs.push(r);
    }
    refs
}

fn parse_single_reference(raw: &str, num: u64) -> ParsedRef {
    let mut r = ParsedRef { ref_num: num, raw_text: raw.to_owned(), ..ParsedRef::default() };
    let normalized = SPACES.replace_all(raw, " ");
    let text = py_strip(&normalized);
    let journal = JOURNAL.find(text);
    let year = YEAR.captures(text);
    if let Some(y) = &year {
        r.year = py_int(&y[1]);
    }
    let prefix_end = journal.map(|m| m.start()).or_else(|| year.as_ref().map(|y| y.get(0).unwrap().start())).unwrap_or(text.len());
    let (authors, title) = split_reference_prefix(strip_chars(&text[..prefix_end], " ,.;"));
    r.authors = authors;
    r.title = title;
    if r.title.is_empty()
        && let Some(q) = QUOTED.captures(text)
    {
        r.title = q[1].to_owned();
    }
    if let Some(m) = journal {
        r.journal = py_strip(m.as_str()).trim_end_matches(['.', ',', ';']).to_owned();
    }
    r
}

/// `re.finditer(r'\.\s+(?=[A-Z][a-z]{2,})', prefix)` as (start, end) byte spans.
fn sentence_boundaries(text: &str) -> Vec<(usize, usize)> {
    let mut out = Vec::new();
    let mut iter = text.char_indices().peekable();
    while let Some((i, c)) = iter.next() {
        if c != '.' {
            continue;
        }
        let rest = &text[i + 1..];
        let ws = rest.find(|c| !is_py_space(c)).unwrap_or(rest.len());
        let mut next = rest[ws..].chars();
        let ok = ws > 0
            && next.next().is_some_and(|c| c.is_ascii_uppercase())
            && next.next().is_some_and(|c| c.is_ascii_lowercase())
            && next.next().is_some_and(|c| c.is_ascii_lowercase());
        if ok {
            out.push((i, i + 1 + ws));
            while iter.peek().is_some_and(|(j, _)| *j < i + 1 + ws) {
                iter.next();
            }
        }
    }
    out
}

fn split_reference_prefix(prefix: &str) -> (String, String) {
    let prefix = strip_chars(prefix, " ,.;");
    if prefix.is_empty() {
        return (String::new(), String::new());
    }
    if let Some(q) = QUOTED.captures(prefix) {
        let authors = strip_chars(&prefix[..q.get(0).unwrap().start()], " ,.;");
        return (authors.to_owned(), strip_chars(&q[1], " ,.;").to_owned());
    }
    if let Some(comma) = prefix.find(',').filter(|&i| i > 0) {
        let authors = py_strip(&prefix[..comma]);
        let title = strip_chars(&prefix[comma + 1..], " ,.;");
        if looks_like_author_prefix(authors) && word_count(title) >= 3 {
            return (authors.to_owned(), title.to_owned());
        }
    }
    for (start, end) in sentence_boundaries(prefix).into_iter().rev() {
        let authors = strip_chars(&prefix[..start + 1], " ,.;");
        let title = strip_chars(&prefix[end..], " ,.;");
        if looks_like_author_prefix(authors) && word_count(title) >= 3 {
            return (authors.to_owned(), title.to_owned());
        }
    }
    if let Some((head, tail)) = prefix.split_once(". ")
        && looks_like_author_prefix(head)
    {
        return (strip_chars(head, " ,.;").to_owned(), strip_chars(tail, " ,.;").to_owned());
    }
    (String::new(), prefix.to_owned())
}

fn looks_like_author_prefix(text: &str) -> bool {
    let normalized = py_strip(text);
    if normalized.is_empty() {
        return false;
    }
    let lower = normalized.to_lowercase();
    if ["introduction", "method", "results", "discussion", "conclusion"].iter().any(|p| lower.starts_with(p)) {
        return false;
    }
    INITIAL_DOT.is_match(normalized)
        || ET_AL.is_match(normalized)
        || normalized.contains('&')
        || lower.contains(" and ")
        || normalized.matches(',').count() >= 2
}

/// `_SUPERSCRIPT_CITE.findall`: `(?<![\d.])([A-Za-z]{3,})(\d{1,3}(?:[,–\-]\d{1,3})*)(?!\d)(?!\.\d)`.
fn superscript_matches(sentence: &str) -> Vec<(String, String)> {
    let chars: Vec<char> = sentence.chars().collect();
    let n = chars.len();
    let digit_run = |p: usize| (p..n.min(p + 3)).take_while(|&i| is_d(chars[i])).count();
    let tail_ok = |p: usize| !(p < n && is_d(chars[p]) || p + 1 < n && chars[p] == '.' && is_d(chars[p + 1]));
    // Greedy `(?:[,–-]\d{1,3})*` followed by the lookaheads, with backtracking.
    fn star(p: usize, chars: &[char], run: &dyn Fn(usize) -> usize, ok: &dyn Fn(usize) -> bool) -> Option<usize> {
        if p < chars.len() && matches!(chars[p], ',' | '\u{2013}' | '-') {
            for k in (1..=run(p + 1)).rev() {
                if let Some(end) = star(p + 1 + k, chars, run, ok) {
                    return Some(end);
                }
            }
        }
        ok(p).then_some(p)
    }
    let mut out = Vec::new();
    let mut s = 0;
    while s < n {
        let behind_ok = s == 0 || !(is_d(chars[s - 1]) || chars[s - 1] == '.');
        let word_end = s + chars[s..].iter().take_while(|c| c.is_ascii_alphabetic()).count();
        let found = (behind_ok && word_end - s >= 3)
            .then(|| (1..=digit_run(word_end)).rev().find_map(|k| star(word_end + k, &chars, &digit_run, &tail_ok)))
            .flatten();
        match found {
            Some(end) => {
                out.push((chars[s..word_end].iter().collect(), chars[word_end..end].iter().collect()));
                s = end;
            }
            None => s += 1,
        }
    }
    out
}

fn extract_citation_numbers(sentence: &str, max_ref: u64, superscript: bool) -> HashSet<u64> {
    let mut nums = HashSet::new();
    for group in CITE_GROUP.captures_iter(sentence) {
        for part in COMMA_SPACE.split(&group[1]) {
            let part = py_strip(part);
            if part.is_empty() {
                continue;
            }
            if let Some(range) = RANGE.captures(part) {
                let (Some(start), Some(end)) = (py_int(&range[1]), py_int(&range[2])) else { continue };
                nums.extend(start..end.saturating_add(1).min(max_ref.saturating_add(1)));
            } else if DIGITS.is_match(part)
                && let Some(n) = py_int(part).filter(|n| (1..=max_ref).contains(n))
            {
                nums.insert(n);
            }
        }
    }
    if superscript {
        for (word, digits) in superscript_matches(sentence) {
            if NOT_A_CITATION_WORD.contains(&word.to_ascii_lowercase().as_str()) {
                continue;
            }
            for part in digits.split([',', '\u{2013}', '-']) {
                if let Some(n) = py_int(part).filter(|n| (1..=max_ref).contains(n)) {
                    nums.insert(n);
                }
            }
        }
    }
    nums
}

fn extract_first_surname(authors: &str) -> String {
    let stripped = py_strip(authors);
    let text = ET_AL_TAIL.replace(stripped, "");
    if text.is_empty() {
        return String::new();
    }
    let first = AUTHOR_SPLIT.find(&text).map_or(&text[..], |m| &text[..m.start()]);
    let first = first.split(',').next().unwrap_or("");
    first
        .split(is_py_space)
        .rfind(|t| !t.is_empty() && !INITIAL_TOKEN.is_match(t) && NAME_TOKEN.is_match(t))
        .unwrap_or("")
        .to_owned()
}

/// `re.split(r'(?<=[.!?])\s+(?=[A-Z\[\(])', text)` keeping pieces longer than 10 chars.
fn split_sentences(text: &str) -> Vec<String> {
    let chars: Vec<char> = text.chars().collect();
    let mut pieces = Vec::new();
    let (mut last, mut i) = (0, 1);
    while i < chars.len() {
        if matches!(chars[i - 1], '.' | '!' | '?') && is_py_space(chars[i]) {
            let j = i + chars[i..].iter().take_while(|c| is_py_space(**c)).count();
            if j < chars.len() && (chars[j].is_ascii_uppercase() || chars[j] == '[' || chars[j] == '(') {
                pieces.push(chars[last..i].iter().collect::<String>());
                last = j;
                i = j + 1;
                continue;
            }
        }
        i += 1;
    }
    pieces.push(chars[last..].iter().collect());
    pieces.into_iter().filter(|s| s.chars().count() > 10).collect()
}

fn section_spans(body: &str, sections: &[(String, String)]) -> Vec<(usize, String)> {
    let mut spans = Vec::new();
    let mut cursor = 0;
    for (name, text) in sections {
        if name == "full_text" || name == "references" || py_strip(text).is_empty() {
            continue;
        }
        let probe_src = prefix(text, 200);
        let probe = py_strip(&probe_src);
        if probe.is_empty() {
            continue;
        }
        let Some(offset) = body.get(cursor..).and_then(|b| b.find(probe)).map(|o| o + cursor).or_else(|| body.find(probe)) else {
            continue;
        };
        spans.push((offset, name.clone()));
        cursor = offset + probe.len();
    }
    spans.sort();
    spans
}

fn sentences_with_section(body: &str, sections: &[(String, String)]) -> Vec<(String, String)> {
    let spans = section_spans(body, sections);
    let mut cursor = 0;
    split_sentences(body)
        .into_iter()
        .map(|sentence| {
            let offset = body.get(cursor..).and_then(|b| b.find(&sentence)).map(|o| o + cursor);
            let mut section = String::new();
            if let Some(offset) = offset {
                cursor = offset + sentence.len();
                let index = spans.partition_point(|(start, _)| *start <= offset);
                if index > 0 {
                    section = spans[index - 1].1.clone();
                }
            }
            (sentence, section)
        })
        .collect()
}

fn context(sentence: &str, section: &str) -> Context {
    Context { sentence: prefix(py_strip(sentence), 300), section: section.to_owned() }
}

fn count_numbered(body: &str, refs: &[ParsedRef], sections: &[(String, String)]) -> Vec<Entry> {
    let max_ref = refs.iter().map(|r| r.ref_num).max().unwrap_or(0);
    let mut hits: HashMap<u64, (usize, Vec<Context>)> = refs.iter().map(|r| (r.ref_num, (0, Vec::new()))).collect();
    let superscript = BRACKET_CITE.find_iter(body).count() < SUPERSCRIPT_BRACKET_MAX;
    for (sentence, section) in sentences_with_section(body, sections) {
        for num in extract_citation_numbers(&sentence, max_ref, superscript) {
            if let Some((count, contexts)) = hits.get_mut(&num) {
                *count += 1;
                contexts.push(context(&sentence, &section));
            }
        }
    }
    refs.iter()
        .map(|r| {
            let (count, contexts) = hits[&r.ref_num].clone();
            Entry { reference: r.clone(), count, contexts }
        })
        .collect()
}

fn count_author_year(body: &str, refs: &[ParsedRef], sections: &[(String, String)]) -> Vec<Entry> {
    let sentences = sentences_with_section(body, sections);
    refs.iter()
        .map(|r| {
            let surname = if r.authors.is_empty() { String::new() } else { extract_first_surname(&r.authors) };
            let mut contexts = Vec::new();
            if !surname.is_empty() {
                let surname = surname.to_lowercase();
                let year = r.year.map(|y| y.to_string()).unwrap_or_default();
                for (sentence, section) in &sentences {
                    if sentence.to_lowercase().contains(&surname) && (year.is_empty() || sentence.contains(&year)) {
                        contexts.push(context(sentence, section));
                    }
                }
            }
            Entry { reference: r.clone(), count: contexts.len(), contexts }
        })
        .collect()
}

/// Python `round(x, 3)`: correctly rounded, ties to even on the exact binary value.
fn py_round3(x: f64) -> f64 {
    format!("{x:.3}").parse().unwrap_or(x)
}

fn self_citations(entries: &[Entry], paper_authors: &str) -> (usize, f64) {
    if paper_authors.is_empty() {
        return (0, 0.0);
    }
    let surnames: HashSet<String> = PAPER_AUTHOR_SPLIT
        .split(paper_authors)
        .map(|name| extract_first_surname(py_strip(name)))
        .filter(|s| s.chars().count() > 2)
        .map(|s| s.to_lowercase())
        .collect();
    if surnames.is_empty() {
        return (0, 0.0);
    }
    let count = entries
        .iter()
        .filter(|e| {
            let authors = e.reference.authors.to_lowercase();
            surnames.iter().any(|s| authors.contains(s.as_str()))
        })
        .count();
    let ratio = if entries.is_empty() { 0.0 } else { count as f64 / entries.len() as f64 };
    (count, py_round3(ratio))
}

fn contexts_json(contexts: &[Context]) -> (Json, Json) {
    let first: Vec<Json> = contexts.iter().take(5).map(|c| json!({"sentence": c.sentence, "section": c.section})).collect();
    let mut counts = Map::new();
    for c in contexts {
        let n = counts.get(&c.section).and_then(Json::as_u64).unwrap_or(0);
        counts.insert(c.section.clone(), json!(n + 1));
    }
    (Value::Array(first), Value::Object(counts))
}

/// `analyze_citations(...).to_dict()`.
pub fn analyze_citations(references: &str, body: &str, sections: &[(String, String)], paper_authors: &str) -> Json {
    let refs = if references.is_empty() { Vec::new() } else { parse_references(references) };
    let (style, entries) = if refs.is_empty() {
        ("numbered", Vec::new())
    } else {
        let style = detect_citation_style(body);
        let mut entries = if style == "numbered" {
            count_numbered(body, &refs, sections)
        } else {
            count_author_year(body, &refs, sections)
        };
        entries.sort_by(|a, b| b.count.cmp(&a.count));
        (style, entries)
    };
    let mut distribution = Map::new();
    for c in entries.iter().flat_map(|e| &e.contexts) {
        let key = if c.section.is_empty() { "unknown" } else { &c.section };
        let n = distribution.get(key).and_then(Json::as_u64).unwrap_or(0);
        distribution.insert(key.to_owned(), json!(n + 1));
    }
    let (self_count, self_ratio) = self_citations(&entries, paper_authors);
    let top_cited: Vec<Json> = entries
        .iter()
        .map(|e| {
            let r = &e.reference;
            let (contexts, counts) = contexts_json(&e.contexts);
            json!({
                "ref_id": r.ref_id, "ref_num": r.ref_num, "authors": r.authors, "title": r.title,
                "journal": r.journal, "year": r.year, "cite_count": e.count, "cite_contexts": contexts,
                "section_counts": counts, "raw_text": prefix(&r.raw_text, 300),
            })
        })
        .collect();
    json!({
        "total_references": refs.len(),
        "citation_style": style,
        "top_cited": top_cited,
        "self_citation_count": self_count,
        "self_citation_ratio": self_ratio,
        "citation_distribution": distribution,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn python_round_ties_to_even() {
        assert_eq!(py_round3(0.0625), 0.062);
        assert_eq!(py_round3(3.0 / 14.0), 0.214);
    }

    #[test]
    fn superscript_backtracks_like_sre() {
        let got = superscript_matches("links1,2. abc12,34.5 x1abcd23 version1.2 Cn2 interval26.");
        let want = [("links", "1,2"), ("abc", "12"), ("bcd", "23"), ("interval", "26")];
        assert_eq!(got, want.map(|(a, b)| (a.to_owned(), b.to_owned())));
    }
}
