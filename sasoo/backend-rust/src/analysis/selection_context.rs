//! Resolve a selected passage only against independently extracted PDF pages.
use crate::error::{Result, SasooError};
use serde::{Deserialize, Serialize};
use std::collections::HashSet;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Selection {
    pub text: String,
    pub page: usize,
    pub end_page: usize,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SelectionContext {
    pub selection: Selection,
    pub status: String,
    pub reason: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub match_start: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub match_end: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub excerpt: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub excerpt_start: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub partial_before: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub partial_after: Option<bool>,
}

fn normalize(chars: &[char], dehyphenate: bool, selection: bool) -> (Vec<char>, Vec<usize>) {
    let mut out = vec![];
    let mut offsets = vec![];
    let mut i = 0;
    while i < chars.len() {
        if dehyphenate
            && (chars[i] == '-' || chars[i] == '\u{ad}')
            && i >= 2
            && chars[i - 1].is_ascii_alphabetic()
            && chars[i - 2].is_ascii_alphabetic()
        {
            let mut j = i + 1;
            let mut newline = false;
            while j < chars.len() && chars[j].is_whitespace() {
                newline |= chars[j] == '\n';
                j += 1;
            }
            let valid_separator = if chars[i] == '\u{ad}' {
                true
            } else if selection {
                j > i + 1
            } else {
                newline
            };
            if valid_separator
                && j + 1 < chars.len()
                && chars[j].is_ascii_alphabetic()
                && chars[j + 1].is_ascii_alphabetic()
            {
                i = j;
                continue;
            }
        }
        let ch = if chars[i].is_whitespace() {
            ' '
        } else {
            chars[i]
        };
        if ch != ' ' || (!out.is_empty() && out.last() != Some(&' ')) {
            out.push(ch);
            offsets.push(i);
        }
        i += 1;
    }
    (out, offsets)
}

pub fn match_selection(pages: &[String], selection: Selection) -> Result<SelectionContext> {
    let len = selection.text.chars().count();
    if selection.page == 0
        || selection.end_page < selection.page
        || selection.text.trim().is_empty()
        || len > 2000
    {
        return Err(SasooError::InvalidInput(
            "Check the selected passage and physical PDF pages (maximum 2,000 characters)".into(),
        ));
    }
    let mut result = SelectionContext {
        selection,
        status: "unverified".into(),
        reason: "주변 문맥을 확인하지 못했습니다.".into(),
        source: None,
        match_start: None,
        match_end: None,
        excerpt: None,
        excerpt_start: None,
        partial_before: None,
        partial_after: None,
    };
    let span = result.selection.end_page - result.selection.page;
    if span > 1 || pages.len() != span + 1 {
        return Ok(result);
    }
    let span = span + 1;
    let text = pages.join("\n");
    let chars: Vec<char> = text.chars().collect();
    let selected: Vec<char> = result.selection.text.chars().collect();
    let mut matches = HashSet::new();
    for dehyphenate in [false, true] {
        let (haystack, offsets) = normalize(&chars, dehyphenate, false);
        let (mut needle, _) = normalize(&selected, dehyphenate, true);
        let (raw_needle, _) = normalize(&selected, false, true);
        while needle.first() == Some(&' ') {
            needle.remove(0);
        }
        while needle.last() == Some(&' ') {
            needle.pop();
        }
        if needle.iter().filter(|&&c| c != ' ').count() < 4 || needle.len() > haystack.len() {
            continue;
        }
        for (index, window) in haystack.windows(needle.len()).enumerate() {
            if window != needle {
                continue;
            }
            let start = offsets[index];
            let end = offsets[index + needle.len() - 1] + 1;
            let raw_trimmed: Vec<char> = raw_needle
                .iter()
                .copied()
                .skip_while(|c| *c == ' ')
                .collect();
            let raw_trimmed: Vec<char> = raw_trimmed
                .into_iter()
                .rev()
                .skip_while(|c| *c == ' ')
                .collect::<Vec<_>>()
                .into_iter()
                .rev()
                .collect();
            if needle != raw_trimmed
                && !chars[start..end].iter().any(|c| *c == '\u{ad}')
                && !chars[start..end]
                    .windows(2)
                    .any(|w| w[0] == '-' && w[1] == '\n')
            {
                continue;
            }
            if span == 1 || (start < pages[0].chars().count() && pages[0].chars().count() < end) {
                matches.insert((start, end));
            }
        }
    }
    if matches.len() != 1 {
        if matches.len() > 1 {
            result.reason = "같은 구절이 여러 번 있어 위치를 확정하지 못했습니다.".into();
        }
        return Ok(result);
    }
    let (start, end) = matches.into_iter().next().unwrap();
    if end - start > 5000 {
        return Ok(result);
    }
    let mut left = start.saturating_sub(800);
    let mut right = (end + 800).min(chars.len());
    if let Some(i) = (left..start.saturating_sub(1))
        .rev()
        .find(|&i| chars[i] == '\n' && chars[i + 1] == '\n')
    {
        left = i + 2;
    }
    if let Some(i) =
        (end..right.saturating_sub(1)).find(|&i| chars[i] == '\n' && chars[i + 1] == '\n')
    {
        right = i;
    }
    if right - left > 5000 {
        left = start;
        right = end;
    }
    result.status = "matched".into();
    result.reason = "PDF 원문에서 유일하게 일치한 위치입니다.".into();
    result.source = Some("PDF text extraction (physical page, 1-based)".into());
    result.match_start = Some(start);
    result.match_end = Some(end);
    result.excerpt = Some(chars[left..right].iter().collect());
    result.excerpt_start = Some(left);
    result.partial_before = Some(left > 0);
    result.partial_after = Some(right < chars.len());
    Ok(result)
}
