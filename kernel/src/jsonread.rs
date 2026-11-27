//! Reading one JSON text from a provider or an executor, at any depth, without
//! recursion, so that a line nested a million deep is read whole and costs no stack.
//!
//! Read strictly (a check), the canonical encoding's refusals hold at every depth,
//! in the order they occur in the text: `duplicate-key`, `not-an-integer` (a
//! fraction, an exponent, or an integer beyond 2^53 - 1) and `invalid-string` (half
//! of a UTF-16 pair). Read loosely (a session), any valid JSON is accepted: a
//! number that is not such an integer reads as null, a repeated key keeps its last
//! value, and half a pair becomes U+FFFD. Either way the depth is measured, and
//! nothing deeper than `KEPT` is kept: a container below that reads as null.
use crate::json::Value;
use std::collections::HashSet;

/// How deep values are kept.
pub const KEPT: usize = 64;

enum Frame {
    Array {
        items: Vec<Value>,
        kept: bool,
    },
    Object {
        fields: Vec<(String, Value)>,
        keys: HashSet<String>,
        key: String,
        kept: bool,
    },
}

/// The value of a JSON text, and how deeply it nests.
pub fn parse(text: &str, strict: bool) -> Result<(Value, usize), &'static str> {
    members(text, strict).map(|(v, deepest, _)| (v, deepest))
}

type ParsedMembers = (Value, usize, Vec<(String, usize)>);

/// The value of a JSON text, how deeply it nests, and, when it is an object, how
/// deeply the text nests under each of its members, counted from the object
/// itself as the first level. A member whose value holds no list or object is
/// not listed. Measured on the text, so it holds below `KEPT` too.
pub fn members(text: &str, strict: bool) -> Result<ParsedMembers, &'static str> {
    let mut p = Parser {
        s: text,
        pos: 0,
        strict,
    };
    let mut stack: Vec<Frame> = Vec::new();
    let mut deepest = 0;
    let mut under: Vec<(String, usize)> = Vec::new();
    loop {
        p.ws();
        let mut value = match p.peek() {
            Some(open @ (b'{' | b'[')) => {
                p.pos += 1;
                let kept = stack.len() < KEPT;
                deepest = deepest.max(stack.len() + 1);
                if let Some(Frame::Object { key, .. }) = stack.first() {
                    match under.last_mut() {
                        Some((k, d)) if *k == *key => *d = (*d).max(stack.len() + 1),
                        _ => under.push((key.clone(), stack.len() + 1)),
                    }
                }
                p.ws();
                if open == b'[' {
                    if p.take(b']') {
                        empty(kept, false)
                    } else {
                        stack.push(Frame::Array {
                            items: Vec::new(),
                            kept,
                        });
                        continue;
                    }
                } else if p.take(b'}') {
                    empty(kept, true)
                } else {
                    let mut keys = HashSet::new();
                    let key = p.key(&mut keys)?;
                    stack.push(Frame::Object {
                        fields: Vec::new(),
                        keys,
                        key,
                        kept,
                    });
                    continue;
                }
            }
            Some(b'"') => Value::String(p.string()?),
            Some(b't') => p.literal("true", Value::Bool(true))?,
            Some(b'f') => p.literal("false", Value::Bool(false))?,
            Some(b'n') => p.literal("null", Value::Null)?,
            Some(b'-' | b'0'..=b'9') => p.number()?,
            _ => return Err("not-json"),
        };
        // A value is complete: give it to the container it is in, and close every
        // container that ends after it.
        loop {
            let frame = match stack.last_mut() {
                None => {
                    p.ws();
                    if p.pos != p.s.len() {
                        return Err("not-json");
                    }
                    return Ok((value, deepest, under));
                }
                Some(f) => f,
            };
            match frame {
                Frame::Array { items, kept } => {
                    if *kept {
                        items.push(value);
                    }
                }
                Frame::Object {
                    fields, key, kept, ..
                } => {
                    if *kept {
                        let key = std::mem::take(key);
                        fields.retain(|(k, _)| *k != key);
                        fields.push((key, value));
                    }
                }
            }
            p.ws();
            if p.take(b',') {
                if let Frame::Object { keys, key, .. } = frame {
                    p.ws();
                    *key = p.key(keys)?;
                }
                break;
            }
            let close = match frame {
                Frame::Array { .. } => b']',
                Frame::Object { .. } => b'}',
            };
            if !p.take(close) {
                return Err("not-json");
            }
            value = match stack.pop() {
                Some(Frame::Array { items, kept: true }) => Value::Array(items),
                Some(Frame::Object {
                    fields, kept: true, ..
                }) => Value::Object(fields),
                _ => Value::Null,
            };
        }
    }
}

fn empty(kept: bool, object: bool) -> Value {
    match (kept, object) {
        (false, _) => Value::Null,
        (true, false) => Value::Array(Vec::new()),
        (true, true) => Value::Object(Vec::new()),
    }
}

struct Parser<'a> {
    s: &'a str,
    pos: usize,
    strict: bool,
}
impl Parser<'_> {
    fn peek(&self) -> Option<u8> {
        self.s.as_bytes().get(self.pos).copied()
    }
    fn ws(&mut self) {
        while matches!(self.peek(), Some(b' ' | b'\n' | b'\r' | b'\t')) {
            self.pos += 1;
        }
    }
    fn take(&mut self, b: u8) -> bool {
        let found = self.peek() == Some(b);
        if found {
            self.pos += 1;
        }
        found
    }
    fn literal(&mut self, word: &str, v: Value) -> Result<Value, &'static str> {
        if !self.s[self.pos..].starts_with(word) {
            return Err("not-json");
        }
        self.pos += word.len();
        Ok(v)
    }
    /// An object's key and the colon after it. A key seen before in the same
    /// object is refused when reading strictly.
    fn key(&mut self, keys: &mut HashSet<String>) -> Result<String, &'static str> {
        if self.peek() != Some(b'"') {
            return Err("not-json");
        }
        let key = self.string()?;
        if !keys.insert(key.clone()) && self.strict {
            return Err("duplicate-key");
        }
        self.ws();
        if !self.take(b':') {
            return Err("not-json");
        }
        Ok(key)
    }
    fn hex(&mut self) -> Result<u32, &'static str> {
        let digits = self.s.get(self.pos..self.pos + 4).ok_or("not-json")?;
        if !digits.bytes().all(|b| b.is_ascii_hexdigit()) {
            return Err("not-json");
        }
        self.pos += 4;
        u32::from_str_radix(digits, 16).map_err(|_| "not-json")
    }
    fn half_pair(&self) -> Result<char, &'static str> {
        if self.strict {
            Err("invalid-string")
        } else {
            Ok('\u{fffd}')
        }
    }
    fn string(&mut self) -> Result<String, &'static str> {
        self.pos += 1;
        let mut out = String::new();
        loop {
            let c = self.s[self.pos..].chars().next().ok_or("not-json")?;
            self.pos += c.len_utf8();
            match c {
                '"' => return Ok(out),
                '\\' => {
                    let e = self.peek().ok_or("not-json")?;
                    self.pos += 1;
                    out.push(match e {
                        b'"' => '"',
                        b'\\' => '\\',
                        b'/' => '/',
                        b'b' => '\u{8}',
                        b'f' => '\u{c}',
                        b'n' => '\n',
                        b'r' => '\r',
                        b't' => '\t',
                        b'u' => {
                            let n = self.hex()?;
                            if (0xd800..=0xdbff).contains(&n) {
                                let rest = &self.s[self.pos..];
                                let low = if rest.starts_with("\\u") {
                                    let at = self.pos;
                                    self.pos += 2;
                                    let low = self.hex()?;
                                    if (0xdc00..=0xdfff).contains(&low) {
                                        Some(low)
                                    } else {
                                        self.pos = at;
                                        None
                                    }
                                } else {
                                    None
                                };
                                match low {
                                    Some(low) => char::from_u32(
                                        0x10000 + ((n - 0xd800) << 10) + (low - 0xdc00),
                                    )
                                    .ok_or("invalid-string")?,
                                    None => self.half_pair()?,
                                }
                            } else if (0xdc00..=0xdfff).contains(&n) {
                                self.half_pair()?
                            } else {
                                char::from_u32(n).ok_or("invalid-string")?
                            }
                        }
                        _ => return Err("not-json"),
                    });
                }
                c if c < ' ' => return Err("not-json"),
                c => out.push(c),
            }
        }
    }
    fn digits(&mut self) -> usize {
        let start = self.pos;
        while matches!(self.peek(), Some(b'0'..=b'9')) {
            self.pos += 1;
        }
        self.pos - start
    }
    fn number(&mut self) -> Result<Value, &'static str> {
        let start = self.pos;
        self.take(b'-');
        match self.peek() {
            Some(b'0') => self.pos += 1,
            Some(b'1'..=b'9') => {
                self.digits();
            }
            _ => return Err("not-json"),
        }
        let integer_end = self.pos;
        let mut integer = true;
        if self.take(b'.') {
            integer = false;
            if self.digits() == 0 {
                return Err("not-json");
            }
        }
        if matches!(self.peek(), Some(b'e' | b'E')) {
            integer = false;
            self.pos += 1;
            if matches!(self.peek(), Some(b'+' | b'-')) {
                self.pos += 1;
            }
            if self.digits() == 0 {
                return Err("not-json");
            }
        }
        let n = self.s[start..integer_end]
            .parse::<i64>()
            .ok()
            .filter(|n| integer && n.unsigned_abs() <= 9007199254740991);
        match n {
            Some(n) => Ok(Value::Number(n)),
            None if self.strict => Err("not-an-integer"),
            None => Ok(Value::Null),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::json;
    fn strict(s: &str) -> Result<String, &'static str> {
        parse(s, true).map(|(v, _)| json::encode(&v))
    }
    fn loose(s: &str) -> Result<String, &'static str> {
        parse(s, false).map(|(v, _)| json::encode(&v))
    }
    #[test]
    fn reads_what_the_strict_parser_reads() {
        for s in [
            r#"{"a":[1,-2,{"b":null}],"c":"x\u00e9\ud83d\ude00\n","d":true,"e":false,"f":{}}"#,
            "[]",
            "\"\"",
            "0",
            " [ 1 , 2 ] ",
            r#"{"z":1,"a":2}"#,
        ] {
            assert_eq!(
                strict(s),
                Ok(json::encode(&json::parse(s.as_bytes()).unwrap())),
                "{s}"
            );
        }
        for s in [
            "{",
            "[1,]",
            "{\"a\"}",
            "{\"a\":1,}",
            "01",
            "1.",
            "\"\\x\"",
            "[1 2]",
            "tru",
            "{} x",
            "",
            "\"a",
        ] {
            assert_eq!(strict(s), Err("not-json"), "{s}");
            assert_eq!(loose(s), Err("not-json"), "{s}");
        }
    }
    #[test]
    fn strict_refusals_at_any_depth() {
        assert_eq!(strict(r#"{"x":{"a":1,"a":2}}"#), Err("duplicate-key"));
        assert_eq!(strict(r#"{"x":[1.0]}"#), Err("not-an-integer"));
        assert_eq!(strict("1e3"), Err("not-an-integer"));
        assert_eq!(strict("9007199254740992"), Err("not-an-integer"));
        assert_eq!(strict("-9007199254740991"), Ok("-9007199254740991".into()));
        assert_eq!(strict("99999999999999999999999"), Err("not-an-integer"));
        assert_eq!(strict(r#"["\ud800"]"#), Err("invalid-string"));
        assert_eq!(strict(r#""\udc00""#), Err("invalid-string"));
        assert_eq!(strict(r#""\ud800\u0041""#), Err("invalid-string"));
    }
    #[test]
    fn loose_reading() {
        assert_eq!(
            loose(r#"{"v":1.5,"w":1,"w":2}"#),
            Ok(r#"{"v":null,"w":2}"#.into())
        );
        assert_eq!(loose(r#""\ud800A""#), Ok("\"\u{fffd}A\"".into()));
        assert_eq!(loose(r#""\ud800\u0041""#), Ok("\"\u{fffd}A\"".into()));
    }
    #[test]
    fn depth_without_recursion() {
        let deep = |n: usize| format!("{}{}", "[".repeat(n), "]".repeat(n));
        assert_eq!(parse(&deep(64), true).unwrap().1, 64);
        assert_eq!(parse(&deep(65), true).unwrap().1, 65);
        let (v, d) = parse(&deep(1_000_000), false).unwrap();
        assert_eq!(d, 1_000_000);
        drop(v);
        assert_eq!(parse("{}", true).unwrap().1, 1);
        assert_eq!(parse("1", true).unwrap().1, 0);
        // Nothing below the kept depth is kept, so a deep value costs no stack to drop.
        let (v, _) = parse(&deep(70), true).unwrap();
        let mut level = &v;
        let mut kept = 0;
        while let Value::Array(a) = level {
            kept += 1;
            match a.first() {
                Some(next) => level = next,
                None => break,
            }
        }
        assert_eq!(kept, KEPT);
        // A key repeated after a deep part is still found: the line is read whole.
        let text = format!(
            r#"{{"body":{}1{},"body":{{}}}}"#,
            r#"{"x":"#.repeat(65),
            "}".repeat(65)
        );
        assert_eq!(parse(&text, true).unwrap_err(), "duplicate-key");
    }
    #[test]
    fn depth_under_each_member() {
        let (_, d, under) = members(r#"{"a":1,"b":[[]],"c":{"x":{}},"d":"s"}"#, true).unwrap();
        assert_eq!(d, 3);
        assert_eq!(under, vec![("b".to_owned(), 3), ("c".to_owned(), 3)]);
        assert!(members("[[[]]]", true).unwrap().2.is_empty());
        assert!(members("{}", true).unwrap().2.is_empty());
        // Measured on the text, below the kept depth too, and with no recursion.
        let deep = |n: usize| format!("{}{}", "[".repeat(n), "]".repeat(n));
        let text = format!(r#"{{"body":{},"kind":"k","z":[]}}"#, deep(1_000_000));
        let (v, d, under) = members(&text, true).unwrap();
        assert_eq!(d, 1_000_001);
        assert_eq!(under, vec![("body".to_owned(), 1_000_001), ("z".to_owned(), 2)]);
        assert_eq!(v.text("kind"), Some("k"));
    }
}
