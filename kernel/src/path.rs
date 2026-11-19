use crate::{
    canonical,
    json::{self, Value},
    unicode,
};
pub fn one(v: &Value) -> Value {
    let bytes = canonical::unhex(v.get("hex").str()).expect("hex is not hexadecimal bytes");
    match check(&bytes) {
        Some(r) => json::object(vec![("refused", json::string(r))]),
        None => json::object(vec![("accepted", Value::Bool(true))]),
    }
}
/// The first rule of the path check a path breaks, if it breaks one.
pub fn check(bytes: &[u8]) -> Option<&'static str> {
    let s = match std::str::from_utf8(bytes) {
        Ok(s) => s,
        Err(_) => return Some("not-utf8"),
    };
    if s.is_empty() {
        return Some("empty");
    }
    if bytes.len() > 200 {
        return Some("too-long");
    }
    let segments: Vec<_> = s.split('/').collect();
    if segments.iter().any(|x| x.is_empty()) {
        return Some("empty-segment");
    }
    if segments.iter().any(|x| *x == "." || *x == "..") {
        return Some("dot-segment");
    }
    if segments.iter().any(|x| x.len() > 100) {
        return Some("segment-too-long");
    }
    if s.chars()
        .any(|c| c <= '\u{1f}' || c == '\u{7f}' || "\\:*?\"<>|".contains(c))
    {
        return Some("forbidden-character");
    }
    if segments
        .iter()
        .any(|x| x.ends_with('.') || x.ends_with(' '))
    {
        return Some("trailing-dot-or-space");
    }
    if segments.iter().any(|x| x.starts_with(' ')) {
        return Some("leading-space");
    }
    if segments.iter().any(|x| reserved(x)) {
        return Some("reserved-name");
    }
    if unicode::nfc(s) != s {
        return Some("not-nfc");
    }
    if s.chars().any(|c| !unicode::assigned(c)) {
        return Some("unassigned-character");
    }
    None
}
fn reserved(s: &str) -> bool {
    let base = s.split('.').next().unwrap().to_ascii_uppercase();
    if ["CON", "PRN", "AUX", "NUL"].contains(&base.as_str()) {
        return true;
    }
    if let Some(rest) = base
        .strip_prefix("COM")
        .or_else(|| base.strip_prefix("LPT"))
    {
        return rest.chars().count() == 1
            && rest
                .chars()
                .all(|c| c.is_ascii_digit() || "¹²³".contains(c));
    }
    false
}
pub fn set(v: &Value) -> Value {
    let paths: Vec<_> = v.get("paths").array().iter().map(Value::str).collect();
    let mut pairs = Vec::new();
    for i in 0..paths.len() {
        for j in i + 1..paths.len() {
            if unicode::fold(paths[i]) == unicode::fold(paths[j]) {
                let mut pair = [paths[i], paths[j]];
                pair.sort();
                pairs.push(pair);
            }
        }
    }
    pairs.sort();
    json::object(vec![(
        "collisions",
        Value::Array(
            pairs
                .iter()
                .map(|p| Value::Array(p.iter().map(|x| json::string(x)).collect()))
                .collect(),
        ),
    )])
}
