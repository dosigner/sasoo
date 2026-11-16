//! Numeric evidence helpers of services/evidence_verifier.py: `normalize_text`,
//! `_NUMBER_TOKEN`, `_token_number` and `_numeric_tokens`.
//! shortcut: `\d` is ASCII only after NFKC (Python also matches other Nd digits such as
//! Arabic-Indic); casefold is Unicode lowercase plus the common full foldings. Both only
//! matter for non-Latin digits; extend if a paper shows one.
use unicode_normalization::{UnicodeNormalization, char::is_combining_mark};

/// Python `str.isspace()`.
pub fn is_py_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// Python `str.casefold()` (see the module shortcut).
pub fn casefold(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars().flat_map(char::to_lowercase) {
        match c {
            'ß' => out.push_str("ss"),
            'ς' => out.push('σ'),
            'ſ' => out.push('s'),
            c => out.push(c),
        }
    }
    out
}

fn is_dash(c: char) -> bool {
    matches!(c, '\u{2010}'..='\u{2015}' | '\u{2212}')
}

fn fold_single(c: char) -> Option<String> {
    Some(match c {
        '\u{ad}' | '\u{200b}' | '\u{200c}' | '\u{200d}' | '\u{feff}' => return None,
        c if is_dash(c) => "-".into(),
        '\u{2018}' | '\u{2019}' | '\u{201a}' | '\u{201b}' | '\u{2032}' => "'".into(),
        '\u{201c}' | '\u{201d}' | '\u{201e}' | '\u{201f}' | '\u{2033}' => "\"".into(),
        '\u{fb00}' => "ff".into(),
        '\u{fb01}' => "fi".into(),
        '\u{fb02}' => "fl".into(),
        '\u{fb03}' => "ffi".into(),
        '\u{fb04}' => "ffl".into(),
        c => casefold(&std::iter::once(c).nfkc().collect::<String>()),
    })
}

/// `normalize_text` (`normalize_with_map(text)[0]`).
pub fn normalize_text(text: &str) -> String {
    let chars: Vec<char> = text.chars().collect();
    let mut pairs = Vec::with_capacity(chars.len());
    let mut i = 0;
    while i < chars.len() {
        let start = i;
        i += 1;
        while i < chars.len() && is_combining_mark(chars[i]) {
            i += 1;
        }
        let folded = if i - start == 1 {
            match fold_single(chars[start]) {
                Some(f) => f,
                None => continue,
            }
        } else {
            casefold(&chars[start..i].iter().copied().nfkc().collect::<String>())
        };
        pairs.extend(folded.chars().map(|c| if is_dash(c) { '-' } else { c }));
    }
    // Line-break hyphen join: '-' [ \t\r]* '\n' whitespace* is removed.
    let mut joined = Vec::with_capacity(pairs.len());
    let mut cursor = 0;
    while cursor < pairs.len() {
        if pairs[cursor] == '-' {
            let mut probe = cursor + 1;
            while probe < pairs.len() && matches!(pairs[probe], ' ' | '\t' | '\r') {
                probe += 1;
            }
            if pairs.get(probe) == Some(&'\n') {
                probe += 1;
                while probe < pairs.len() && is_py_space(pairs[probe]) {
                    probe += 1;
                }
                cursor = probe;
                continue;
            }
        }
        joined.push(pairs[cursor]);
        cursor += 1;
    }
    let mut out = String::with_capacity(joined.len());
    let mut previous_was_space = true;
    for c in joined {
        if is_py_space(c) {
            if !previous_was_space {
                out.push(' ');
            }
            previous_was_space = true;
        } else {
            out.push(c);
            previous_was_space = false;
        }
    }
    out.truncate(out.trim_end_matches(' ').len());
    out
}

/// A `Decimal` reduced to (sign, coefficient without leading/trailing zeros, exponent);
/// two values are `==` in Python exactly when these are equal (zero is unsigned).
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct Number {
    pub negative: bool,
    pub digits: String,
    pub exponent: i128,
}

impl Number {
    fn new(mantissa: &str, exponent: Option<&str>) -> Self {
        let (negative, body) = mantissa.strip_prefix('-').map_or((false, mantissa), |b| (true, b));
        let (int, frac) = body.split_once('.').unwrap_or((body, ""));
        // shortcut: exponents beyond i128 saturate; Python keeps them exact.
        let exp: i128 = exponent.map_or(0, |e| e.parse().unwrap_or(if e.starts_with('-') { i128::MIN / 2 } else { i128::MAX / 2 }));
        let mut digits: String = format!("{int}{frac}").trim_start_matches('0').to_owned();
        let mut exponent = exp - frac.len() as i128;
        if digits.is_empty() {
            return Self { negative: false, digits: "0".into(), exponent: 0 };
        }
        while digits.ends_with('0') {
            digits.pop();
            exponent += 1;
        }
        Self { negative, digits, exponent }
    }
}

fn is_digit(c: Option<&char>) -> bool {
    c.is_some_and(char::is_ascii_digit)
}

fn digits_from(s: &[char], i: usize) -> usize {
    s[i.min(s.len())..].iter().take_while(|c| c.is_ascii_digit()).count()
}

fn spaces_from(s: &[char], i: usize) -> usize {
    s[i.min(s.len())..].iter().take_while(|c| is_py_space(**c)).count()
}

/// `(?!\.?\d)` at `i`.
fn lookahead_ok(s: &[char], i: usize) -> bool {
    !(is_digit(s.get(i)) || (s.get(i) == Some(&'.') && is_digit(s.get(i + 1))))
}

/// `-?\d+` at `i`: end and text.
fn signed_digits(s: &[char], i: usize) -> Option<usize> {
    let start = if s.get(i) == Some(&'-') { i + 1 } else { i };
    let n = digits_from(s, start);
    (n > 0).then_some(start + n)
}

/// Exponent alternatives after the mantissa, in regex priority: (end, exponent digits).
fn exponents(s: &[char], m: usize) -> Vec<(usize, Option<String>)> {
    let mut out = Vec::new();
    let text = |a: usize, b: usize| s[a..b].iter().collect::<String>();
    if s.get(m) == Some(&'e') {
        if let Some(end) = signed_digits(s, m + 1) {
            out.push((end, Some(text(m + 1, end))));
        }
    }
    let mut k = m + spaces_from(s, m);
    if s.get(k).is_some_and(|c| matches!(c, '×' | 'x' | '*' | '·' | '⋅')) {
        k += 1;
        k += spaces_from(s, k);
        if s.get(k) == Some(&'1') && s.get(k + 1) == Some(&'0') {
            k += 2;
            if s.get(k) == Some(&'^') {
                k += 1;
            }
            if let Some(end) = signed_digits(s, k) {
                out.push((end, Some(text(k, end))));
            }
        }
    }
    out.push((m, None));
    out
}

/// One `_NUMBER_TOKEN` match at `p`: (end, value or None for the discarded branch).
fn match_at(s: &[char], p: usize) -> Option<(usize, Option<Number>)> {
    // (?P<discarded>10\s*[-+]\d+)
    if s.get(p) == Some(&'1') && s.get(p + 1) == Some(&'0') {
        let q = p + 2 + spaces_from(s, p + 2);
        if s.get(q).is_some_and(|c| matches!(c, '-' | '+')) {
            let n = digits_from(s, q + 1);
            if n > 0 && lookahead_ok(s, q + 1 + n) {
                return Some((q + 1 + n, None));
            }
        }
    }
    let q = if s.get(p) == Some(&'-') { p + 1 } else { p };
    let int = digits_from(s, q);
    if int == 0 {
        return None;
    }
    let mut groups = vec![q + int];
    loop {
        let r = *groups.last().unwrap_or(&0);
        if s.get(r) == Some(&',') && digits_from(s, r + 1) >= 3 {
            groups.push(r + 4);
        } else {
            break;
        }
    }
    for &m in groups.iter().rev() {
        let mut decimals = Vec::new();
        if s.get(m) == Some(&'.') && is_digit(s.get(m + 1)) {
            decimals.push(m + 1 + digits_from(s, m + 1));
        }
        decimals.push(m);
        for e in decimals {
            for (end, exp) in exponents(s, e) {
                if lookahead_ok(s, end) {
                    let mantissa: String = s[p..e].iter().filter(|c| **c != ',').collect();
                    return Some((end, Some(Number::new(&mantissa, exp.as_deref()))));
                }
            }
        }
    }
    None
}

/// `_numeric_tokens`: (number, matched text) for each `_NUMBER_TOKEN.finditer` hit.
pub fn numeric_tokens(text: &str) -> Vec<(Number, String)> {
    let s: Vec<char> = text.chars().collect();
    let mut out = Vec::new();
    let mut p = 0;
    while p < s.len() {
        let behind_ok = p == 0 || !(s[p - 1].is_ascii_digit() || s[p - 1] == '.');
        match match_at(&s, p).filter(|_| behind_ok) {
            Some((end, value)) => {
                if let Some(number) = value {
                    out.push((number, s[p..end].iter().collect()));
                }
                p = end;
            }
            None => p += 1,
        }
    }
    out
}
