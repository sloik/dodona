use std::fmt::Write;

#[derive(Clone, Debug)]
pub enum Value {
    Null,
    Bool(bool),
    Number(i64),
    String(String),
    Array(Vec<Value>),
    Object(Vec<(String, Value)>),
}
impl Value {
    pub fn get(&self, key: &str) -> &Value {
        self.opt(key).unwrap()
    }
    pub fn opt(&self, key: &str) -> Option<&Value> {
        if let Value::Object(v) = self {
            v.iter().find(|(k, _)| k == key).map(|(_, v)| v)
        } else {
            None
        }
    }
    pub fn opt_mut(&mut self, key: &str) -> Option<&mut Value> {
        if let Value::Object(v) = self {
            v.iter_mut().find(|(k, _)| k == key).map(|(_, v)| v)
        } else {
            None
        }
    }
    pub fn str(&self) -> &str {
        if let Value::String(s) = self {
            s
        } else {
            panic!("expected string")
        }
    }
    pub fn array(&self) -> &[Value] {
        if let Value::Array(a) = self {
            a
        } else {
            panic!("expected array")
        }
    }
    pub fn object(&self) -> &[(String, Value)] {
        if let Value::Object(o) = self {
            o
        } else {
            panic!("expected object")
        }
    }
    pub fn number(&self) -> i64 {
        if let Value::Number(n) = self {
            *n
        } else {
            panic!("expected number")
        }
    }
}
pub fn string(s: &str) -> Value {
    Value::String(s.into())
}
pub fn object(v: Vec<(&str, Value)>) -> Value {
    Value::Object(v.into_iter().map(|(k, v)| (k.into(), v)).collect())
}

pub fn encode(v: &Value) -> String {
    fn write(v: &Value, out: &mut String) {
        match v {
            Value::Null => out.push_str("null"),
            Value::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
            Value::Number(n) => {
                write!(out, "{n}").unwrap();
            }
            Value::String(s) => {
                out.push('"');
                for c in s.chars() {
                    match c {
                        '"' => out.push_str("\\\""),
                        '\\' => out.push_str("\\\\"),
                        '\u{8}' => out.push_str("\\b"),
                        '\t' => out.push_str("\\t"),
                        '\n' => out.push_str("\\n"),
                        '\u{c}' => out.push_str("\\f"),
                        '\r' => out.push_str("\\r"),
                        c if c < ' ' => {
                            write!(out, "\\u{:04x}", c as u32).unwrap();
                        }
                        c => out.push(c),
                    }
                }
                out.push('"');
            }
            Value::Array(a) => {
                out.push('[');
                for (i, x) in a.iter().enumerate() {
                    if i > 0 {
                        out.push(',')
                    }
                    write(x, out);
                }
                out.push(']');
            }
            Value::Object(o) => {
                let mut entries: Vec<_> = o.iter().collect();
                entries.sort_by(|a, b| a.0.encode_utf16().cmp(b.0.encode_utf16()));
                out.push('{');
                for (i, (k, v)) in entries.iter().enumerate() {
                    if i > 0 {
                        out.push(',')
                    }
                    write(&Value::String(k.clone()), out);
                    out.push(':');
                    write(v, out);
                }
                out.push('}');
            }
        }
    }
    let mut out = String::new();
    write(v, &mut out);
    out
}

pub fn parse(bytes: &[u8]) -> Result<Value, &'static str> {
    let s = std::str::from_utf8(bytes).map_err(|_| "invalid-string")?;
    let mut p = Parser { s, pos: 0 };
    let v = p.value()?;
    p.ws();
    if p.pos != s.len() {
        return Err("not-json");
    }
    Ok(v)
}
struct Parser<'a> {
    s: &'a str,
    pos: usize,
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
        if self.peek() == Some(b) {
            self.pos += 1;
            true
        } else {
            false
        }
    }
    fn value(&mut self) -> Result<Value, &'static str> {
        self.ws();
        match self.peek() {
            Some(b'"') => Ok(Value::String(self.string()?)),
            Some(b'{') => self.object(),
            Some(b'[') => self.array(),
            Some(b't') => self.literal("true", Value::Bool(true)),
            Some(b'f') => self.literal("false", Value::Bool(false)),
            Some(b'n') => self.literal("null", Value::Null),
            Some(b'-' | b'0'..=b'9') => self.number(),
            _ => Err("not-json"),
        }
    }
    fn literal(&mut self, s: &str, v: Value) -> Result<Value, &'static str> {
        if self.s[self.pos..].starts_with(s) {
            self.pos += s.len();
            Ok(v)
        } else {
            Err("not-json")
        }
    }
    fn hex(&mut self) -> Result<u32, &'static str> {
        let mut n = 0;
        for _ in 0..4 {
            let b = self.peek().ok_or("not-json")?;
            self.pos += 1;
            n = n * 16 + (b as char).to_digit(16).ok_or("not-json")?;
        }
        Ok(n)
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
                    match e {
                        b'"' => out.push('"'),
                        b'\\' => out.push('\\'),
                        b'/' => out.push('/'),
                        b'b' => out.push('\u{8}'),
                        b'f' => out.push('\u{c}'),
                        b'n' => out.push('\n'),
                        b'r' => out.push('\r'),
                        b't' => out.push('\t'),
                        b'u' => {
                            let mut n = self.hex()?;
                            if (0xd800..=0xdbff).contains(&n) {
                                if !self.s[self.pos..].starts_with("\\u") {
                                    return Err("invalid-string");
                                }
                                self.pos += 2;
                                let low = self.hex()?;
                                if !(0xdc00..=0xdfff).contains(&low) {
                                    return Err("invalid-string");
                                }
                                n = 0x10000 + ((n - 0xd800) << 10) + (low - 0xdc00);
                            } else if (0xdc00..=0xdfff).contains(&n) {
                                return Err("invalid-string");
                            }
                            out.push(char::from_u32(n).ok_or("invalid-string")?);
                        }
                        _ => return Err("not-json"),
                    }
                }
                c if c < ' ' => return Err("not-json"),
                c => out.push(c),
            }
        }
    }
    fn number(&mut self) -> Result<Value, &'static str> {
        let start = self.pos;
        self.take(b'-');
        match self.peek() {
            Some(b'0') => {
                self.pos += 1;
            }
            Some(b'1'..=b'9') => {
                while matches!(self.peek(), Some(b'0'..=b'9')) {
                    self.pos += 1
                }
            }
            _ => return Err("not-json"),
        }
        let integer_end = self.pos;
        let mut fractional = false;
        if self.take(b'.') {
            fractional = true;
            let start = self.pos;
            while matches!(self.peek(), Some(b'0'..=b'9')) {
                self.pos += 1
            }
            if start == self.pos {
                return Err("not-json");
            }
        }
        if matches!(self.peek(), Some(b'e' | b'E')) {
            fractional = true;
            self.pos += 1;
            if matches!(self.peek(), Some(b'+' | b'-')) {
                self.pos += 1
            }
            let start = self.pos;
            while matches!(self.peek(), Some(b'0'..=b'9')) {
                self.pos += 1
            }
            if start == self.pos {
                return Err("not-json");
            }
        }
        if fractional {
            return Err("not-an-integer");
        }
        let n = self.s[start..integer_end]
            .parse::<i64>()
            .map_err(|_| "integer-out-of-range")?;
        if n.unsigned_abs() > 9007199254740991 {
            return Err("integer-out-of-range");
        }
        Ok(Value::Number(n))
    }
    fn array(&mut self) -> Result<Value, &'static str> {
        self.pos += 1;
        let mut a = Vec::new();
        self.ws();
        if self.take(b']') {
            return Ok(Value::Array(a));
        }
        loop {
            a.push(self.value()?);
            self.ws();
            if self.take(b']') {
                break;
            }
            if !self.take(b',') {
                return Err("not-json");
            }
        }
        Ok(Value::Array(a))
    }
    fn object(&mut self) -> Result<Value, &'static str> {
        self.pos += 1;
        let mut o: Vec<(String, Value)> = Vec::new();
        self.ws();
        if self.take(b'}') {
            return Ok(Value::Object(o));
        }
        loop {
            self.ws();
            if self.peek() != Some(b'"') {
                return Err("not-json");
            }
            let k = self.string()?;
            if o.iter().any(|(key, _)| key == &k) {
                return Err("duplicate-key");
            }
            self.ws();
            if !self.take(b':') {
                return Err("not-json");
            }
            let v = self.value()?;
            o.push((k, v));
            self.ws();
            if self.take(b'}') {
                break;
            }
            if !self.take(b',') {
                return Err("not-json");
            }
        }
        Ok(Value::Object(o))
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn refusals() {
        for (s, r) in [
            ("{", "not-json"),
            ("1.0", "not-an-integer"),
            ("9007199254740992", "integer-out-of-range"),
            ("{\"x\":1,\"x\":2}", "duplicate-key"),
            ("\"\\ud800\"", "invalid-string"),
        ] {
            assert_eq!(parse(s.as_bytes()).unwrap_err(), r);
        }
    }
    #[test]
    fn fields() {
        let mut v = parse(br#"{"a":{"b":1}}"#).unwrap();
        assert!(v.opt("x").is_none());
        assert!(v.opt_mut("x").is_none());
        *v.opt_mut("a").unwrap().opt_mut("b").unwrap() = Value::Number(2);
        assert_eq!(encode(&v), r#"{"a":{"b":2}}"#);
        assert!(Value::Null.opt_mut("a").is_none());
    }
    #[test]
    fn utf16_order() {
        assert_eq!(
            encode(&parse("{\"～\":1,\"😀\":2}".as_bytes()).unwrap()),
            "{\"😀\":2,\"～\":1}"
        );
    }
}
