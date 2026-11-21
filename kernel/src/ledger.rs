use crate::{
    canonical,
    json::{self, Value},
};
use std::{
    fs::{self, OpenOptions},
    io::{ErrorKind, Seek, SeekFrom, Write},
    thread,
    time::{Duration, Instant},
};
/// What a ledger file holds.
#[derive(Debug)]
struct Contents {
    entries: Vec<Value>,
    /// Where the last complete line ends. Bytes after it are a torn final entry.
    end: usize,
    torn: bool,
}
fn line(entry: &Value) -> String {
    let payload = json::encode(entry);
    format!(
        "dodona1 {} {} {}\n",
        payload.len(),
        canonical::sha256(payload.as_bytes()),
        payload
    )
}
/// The entry on one complete line, without its line feed, if the line is well
/// formed and names `previous` as the entry before it.
fn entry(line: &[u8], earlier: &[String]) -> Option<Value> {
    let text = std::str::from_utf8(line).ok()?;
    let mut parts = text.splitn(4, ' ');
    let (marker, length, checksum, payload) =
        (parts.next()?, parts.next()?, parts.next()?, parts.next()?);
    if marker != "dodona1"
        || length != payload.len().to_string()
        || checksum != canonical::sha256(payload.as_bytes())
    {
        return None;
    }
    // A payload nested deeper than 64 levels, the entry itself the first, is
    // corrupt. Measured without recursion, before the payload is read as a value.
    let (_, depth) = crate::jsonread::parse(payload, true).ok()?;
    if depth > crate::wire::MAX_DEPTH {
        return None;
    }
    let entry = json::parse(payload.as_bytes()).ok()?;
    let shaped = matches!(&entry, Value::Object(fields) if fields.len() == 3)
        && entry.text("kind").is_some_and(|k| !k.is_empty())
        && entry.opt("body").is_some()
        && match (entry.opt("previous"), earlier.last()) {
            (Some(Value::Null), None) => true,
            (Some(Value::String(p)), Some(want)) => p == want,
            _ => false,
        };
    (shaped && json::encode(&entry) == payload).then_some(entry)
}
/// Read the bytes of a ledger, or say which line, counting from 1, makes it corrupt.
fn parse(data: &[u8]) -> Result<Contents, usize> {
    let end = data.iter().rposition(|b| *b == b'\n').map_or(0, |i| i + 1);
    let mut entries = Vec::new();
    // The identity of every entry so far, in order.
    let mut earlier: Vec<String> = Vec::new();
    if end > 0 {
        let lines = data[..end - 1].split(|b| *b == b'\n');
        for (i, line) in lines.enumerate() {
            let e = entry(line, &earlier).ok_or(i + 1)?;
            earlier.push(canonical::identity(&e));
            entries.push(e);
        }
    }
    Ok(Contents {
        entries,
        end,
        torn: end != data.len(),
    })
}
/// The bytes of the ledger file. One that does not exist is empty.
fn load(path: &str) -> Result<Vec<u8>, String> {
    match fs::read(path) {
        Ok(data) => Ok(data),
        Err(e) if e.kind() == ErrorKind::NotFound => Ok(Vec::new()),
        Err(e) => Err(format!("cannot read the ledger: {e}")),
    }
}
/// The lock file, removed when this is dropped: on every way out of an append.
struct Lock(String);
impl Drop for Lock {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}
/// Take the lock, waiting up to `wait`. `Ok(None)` means someone else still holds it.
fn lock(path: &str, wait: Duration) -> Result<Option<Lock>, String> {
    let name = format!("{path}.lock");
    let start = Instant::now();
    loop {
        match OpenOptions::new().write(true).create_new(true).open(&name) {
            Ok(_) => return Ok(Some(Lock(name))),
            // While another kernel is removing the lock, some systems refuse to create it
            // with a permission error instead of saying it exists. Both mean: held, try again.
            Err(e)
                if matches!(
                    e.kind(),
                    ErrorKind::AlreadyExists | ErrorKind::PermissionDenied
                ) =>
            {
                let left = wait.saturating_sub(start.elapsed());
                if left.is_zero() {
                    return Ok(None);
                }
                thread::sleep(left.min(Duration::from_millis(5)));
            }
            Err(e) => return Err(format!("cannot take the ledger lock: {e}")),
        }
    }
}
fn refused(reason: &str) -> Value {
    json::object(vec![("refused", json::string(reason))])
}
pub fn read(v: &Value) -> Result<Value, String> {
    let path = field(v, "ledger")?;
    Ok(match parse(&load(path)?) {
        Ok(c) => json::object(vec![
            ("entries", Value::Array(c.entries)),
            ("torn", Value::Bool(c.torn)),
        ]),
        Err(at) => json::object(vec![
            ("refused", json::string("corrupt")),
            ("at", Value::Number(at as i64)),
        ]),
    })
}
fn field<'a>(v: &'a Value, name: &str) -> Result<&'a str, String> {
    match v.opt(name) {
        Some(Value::String(s)) => Ok(s),
        _ => Err(format!("`{name}` must be a string")),
    }
}
/// Add one entry, as the request `input` asks. The request is read without
/// recursion and its depth measured on the text, so that a body nested
/// thousands deep is refused like any other too deep, not by running out of
/// stack. A request no deeper than an entry may be is read as every other
/// command's input is.
pub fn append(input: &[u8]) -> Result<Value, String> {
    let unreadable = |reason: &str| format!("the input is not acceptable JSON: {reason}");
    let text = std::str::from_utf8(input).map_err(|_| unreadable("invalid-string"))?;
    let (kept, deepest, under) = crate::jsonread::members(text, true).map_err(unreadable)?;
    let v = if deepest > crate::wire::MAX_DEPTH {
        // Read whole, but nothing deeper than 64 kept: no deep value is built.
        kept
    } else {
        json::parse(input).map_err(unreadable)?
    };
    // How deep the entry would nest: the entry itself is the first level, and its
    // body sits where the request's does.
    let body_depth = under
        .iter()
        .filter(|(k, _)| k == "body")
        .map(|(_, d)| *d)
        .fold(1, usize::max);
    append_read(&v, body_depth)
}
fn append_read(v: &Value, body_depth: usize) -> Result<Value, String> {
    // Everything the caller supplies is checked before the lock is taken.
    let path = field(v, "ledger")?;
    let wait = match v.opt("wait_ms") {
        Some(Value::Number(n)) => Duration::from_millis((*n).max(0) as u64),
        _ => return Err("`wait_ms` must be a number".into()),
    };
    // The caller supplies a kind, any non-empty string, and a body.
    let kind = v.text("kind").filter(|k| !k.is_empty());
    let (Some(kind), Some(body)) = (kind, v.opt("body")) else {
        return Ok(refused("bad-request"));
    };
    // An entry nested deeper than 64 levels, the entry itself the first, could
    // never be read back: it is refused before anything is touched.
    let depth = body_depth;
    if depth > crate::wire::MAX_DEPTH {
        return Ok(refused("bad-request"));
    }
    let Some(_lock) = lock(path, wait)? else {
        return Ok(refused("locked"));
    };
    // From here the lock is held; it is released when `_lock` goes out of
    // scope, after the file has been written, synced and closed.
    let data = load(path)?;
    let Ok(contents) = parse(&data) else {
        return Ok(refused("corrupt"));
    };
    let previous = contents.entries.last().map(canonical::identity);
    let entry = json::object(vec![
        (
            "previous",
            previous.map_or(Value::Null, |p| json::string(&p)),
        ),
        ("kind", json::string(kind)),
        ("body", body.clone()),
    ]);
    let write = || -> std::io::Result<()> {
        let mut f = OpenOptions::new()
            .create(true)
            .truncate(false)
            .write(true)
            .open(path)?;
        // Cut off a torn ending, then write the line after the last whole entry.
        f.set_len(contents.end as u64)?;
        f.seek(SeekFrom::End(0))?;
        f.write_all(line(&entry).as_bytes())?;
        f.sync_all()
    };
    write().map_err(|e| format!("cannot write the ledger: {e}"))?;
    Ok(json::object(vec![(
        "appended",
        json::string(&canonical::identity(&entry)),
    )]))
}
/// Why the append did not complete.
#[derive(Debug, PartialEq)]
#[cfg_attr(not(test), allow(dead_code))]
pub enum NotWritten {
    /// Someone else held the lock for all of the wait.
    Locked,
    /// The ledger is corrupt at this line, counting from 1.
    Corrupt(usize),
    /// A folder could not be made, the ledger read, or the lock taken.
    Failed(String),
}

/// Append one entry of `kind` for each body, in order, all in one append, as
/// a run records its verdicts: the folders on the ledger's path that are not
/// there made, the lock beside the ledger taken (waiting up to `wait`), the
/// ledger read as `ledger-read` reads it and refused if corrupt, an ending cut
/// short cut off, every entry added as one line after the last, the file
/// synced to disk, and the lock released. The identities of the entries
/// appended. With no bodies nothing is touched, not even a folder.
///
/// A write failure can leave complete entries and a torn ending. The next
/// append reads the complete prefix and cuts off any torn ending.
#[cfg_attr(not(test), allow(dead_code))]
pub fn append_entries(
    path: &str,
    kind: &str,
    bodies: &[Value],
    wait: Duration,
) -> Result<Vec<String>, NotWritten> {
    if bodies.is_empty() {
        return Ok(Vec::new());
    }
    fn failed(what: &str, e: impl std::fmt::Display) -> NotWritten {
        NotWritten::Failed(format!("{what}: {e}"))
    }
    if let Some(folder) = std::path::Path::new(path)
        .parent()
        .filter(|f| !f.as_os_str().is_empty())
    {
        fs::create_dir_all(folder).map_err(|e| failed("cannot make the ledger's folder", e))?;
    }
    let Some(_lock) = lock(path, wait).map_err(NotWritten::Failed)? else {
        return Err(NotWritten::Locked);
    };
    // From here the lock is held, and released when `_lock` is dropped,
    // after the file has been written, synced and closed.
    let data = load(path).map_err(NotWritten::Failed)?;
    let contents = parse(&data).map_err(NotWritten::Corrupt)?;
    let mut previous = contents.entries.last().map(canonical::identity);
    let mut lines = String::new();
    let mut appended = Vec::new();
    for body in bodies {
        let entry = json::object(vec![
            ("previous", previous.as_deref().map_or(Value::Null, json::string)),
            ("kind", json::string(kind)),
            ("body", body.clone()),
        ]);
        let id = canonical::identity(&entry);
        lines.push_str(&line(&entry));
        previous = Some(id.clone());
        appended.push(id);
    }
    let write = || -> std::io::Result<()> {
        let mut f = OpenOptions::new()
            .create(true)
            .truncate(false)
            .write(true)
            .open(path)?;
        f.set_len(contents.end as u64)?;
        f.seek(SeekFrom::End(0))?;
        f.write_all(lines.as_bytes())?;
        f.sync_all()
    };
    write().map_err(|e| failed("cannot write the ledger", e))?;
    Ok(appended)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn entries(bodies: &[&str]) -> (Vec<Value>, String) {
        let mut previous = Value::Null;
        let mut out = Vec::new();
        let mut text = String::new();
        for b in bodies {
            let e = json::object(vec![
                ("previous", previous),
                ("kind", json::string("evidence")),
                ("body", json::string(b)),
            ]);
            previous = json::string(&canonical::identity(&e));
            text.push_str(&line(&e));
            out.push(e);
        }
        (out, text)
    }
    #[test]
    fn line_format() {
        let e = json::parse(br#"{"previous":null,"kind":"act","body":{}}"#).unwrap();
        assert_eq!(
            line(&e),
            format!(
                "dodona1 40 {} {}\n",
                canonical::sha256(br#"{"body":{},"kind":"act","previous":null}"#),
                r#"{"body":{},"kind":"act","previous":null}"#
            )
        );
    }
    #[test]
    fn whole_and_torn() {
        let (want, text) = entries(&["a", "b", "c"]);
        let c = parse(text.as_bytes()).unwrap();
        assert_eq!(
            json::encode(&Value::Array(c.entries)),
            json::encode(&Value::Array(want))
        );
        assert!(!c.torn);
        assert_eq!(c.end, text.len());
        let empty = parse(b"").unwrap();
        assert!(empty.entries.is_empty() && !empty.torn && empty.end == 0);
        let (_, two) = entries(&["a", "b"]);
        for cut in 1..text.len() - two.len() {
            let c = parse(&text.as_bytes()[..text.len() - cut]).unwrap();
            assert!(c.torn);
            assert_eq!(c.entries.len(), 2);
            assert_eq!(c.end, two.len());
        }
        let only_torn = parse(b"dodona1 12").unwrap();
        assert!(only_torn.torn && only_torn.entries.is_empty() && only_torn.end == 0);
    }
    #[test]
    fn corruption() {
        let (_, text) = entries(&["a", "b", "c"]);
        let lines: Vec<&str> = text.split_inclusive('\n').collect();
        let at = |s: String| parse(s.as_bytes()).unwrap_err();
        assert_eq!(at(format!("{}{}", lines[0], lines[2])), 2);
        assert_eq!(at(format!("{}{}{}", lines[1], lines[0], lines[2])), 1);
        assert_eq!(at(format!("{text}garbage\n")), 4);
        assert_eq!(at(format!("{text}\n")), 4);
        assert_eq!(at("\n".into()), 1);
        assert_eq!(at(format!("\n{text}")), 1);
        assert_eq!(at(text.replacen('\n', "\r\n", 1)), 1);
        assert_eq!(at(text.replacen("\"b\"", "\"B\"", 1)), 2);
        assert_eq!(at(text.replacen("dodona1", "dodona2", 1)), 1);
        // `previous` must be the entry just before, not an earlier one.
        let (three, _) = entries(&["a", "b", "c"]);
        let skipping = json::object(vec![
            ("previous", json::string(&canonical::identity(&three[1]))),
            ("kind", json::string("evidence")),
            ("body", json::string("d")),
        ]);
        assert_eq!(at(format!("{text}{}", line(&skipping))), 4);
        // A torn ending excuses nothing before it.
        assert_eq!(at(format!("{}garbage\n{}", lines[0], &lines[1][..9])), 2);
        // Well formed, with the right length and checksum, but not canonical or not an entry.
        let raw = |payload: &str| {
            format!(
                "dodona1 {} {} {}\n",
                payload.len(),
                canonical::sha256(payload.as_bytes()),
                payload
            )
        };
        for payload in [
            r#"{"previous":null,"kind":"act","body":{}}"#,
            r#"{"body":{},"kind":"act","previous":null,"extra":1}"#,
            r#"{"body":{},"kind":"act"}"#,
            r#"{"body":{},"kind":7,"previous":null}"#,
            r#"{"body":{},"kind":"","previous":null}"#,
            r#"{"body":{},"kind":"act","previous":"sha256:00","extra":1}"#,
            "null",
            r#"{"body":{},"kind":"act","previous":"sha256:00"}"#,
            r#"[]"#,
            "not json",
        ] {
            assert_eq!(at(raw(payload)), 1, "{payload}");
        }
        assert!(parse(raw(r#"{"body":{},"kind":"act","previous":null}"#).as_bytes()).is_ok());
        // The length is plain decimal: no sign, no leading zero.
        let good = raw(r#"{"body":{},"kind":"act","previous":null}"#);
        assert_eq!(at(good.replacen(" 40 ", " 040 ", 1)), 1);
        assert_eq!(at(good.replacen(" 40 ", " +40 ", 1)), 1);
        assert_eq!(at(good.replacen(" 40 ", "  40 ", 1)), 1);
    }
    fn scratch(name: &str) -> String {
        let dir = std::env::temp_dir().join(format!("dodona-kernel-test-{}", std::process::id()));
        fs::create_dir_all(&dir).unwrap();
        let path = dir.join(name);
        let _ = fs::remove_file(&path);
        path.to_str().unwrap().to_owned()
    }
    fn request(path: &str, body: &str) -> Value {
        json::object(vec![
            ("ledger", json::string(path)),
            ("kind", json::string("evidence")),
            ("body", json::string(body)),
            ("wait_ms", Value::Number(0)),
        ])
    }
    /// An append asked as the command is asked: as text.
    fn ask(v: &Value) -> Result<Value, String> {
        append(json::encode(v).as_bytes())
    }
    /// A request whose body is an object nested `levels` deep, written as text,
    /// since no value that deep is built here.
    fn deep_request(path: &str, levels: usize) -> String {
        format!(
            r#"{{"body":{}{{}}{},"kind":"note","ledger":{},"wait_ms":0}}"#,
            r#"{"x":"#.repeat(levels - 1),
            "}".repeat(levels - 1),
            json::encode(&json::string(path))
        )
    }
    #[test]
    fn deep_bodies() {
        // A folder of its own: the other test removes its folder when it ends.
        let dir = std::env::temp_dir().join(format!("dodona-kernel-deep-{}", std::process::id()));
        fs::create_dir_all(&dir).unwrap();
        let path = dir.join("deep.ledger").to_str().unwrap().to_owned();
        let _ = fs::remove_file(&path);
        let lock_file = format!("{path}.lock");
        // Deep enough to run out of stack if it were read by recursion.
        for levels in [64, 5_000, 100_000] {
            let answer = append(deep_request(&path, levels).as_bytes()).unwrap();
            assert_eq!(json::encode(&answer), r#"{"refused":"bad-request"}"#);
            assert!(!std::path::Path::new(&path).exists());
            assert!(!std::path::Path::new(&lock_file).exists());
        }
        // Refused before the lock is looked at.
        fs::write(&lock_file, "theirs").unwrap();
        let answer = append(deep_request(&path, 5_000).as_bytes()).unwrap();
        assert_eq!(json::encode(&answer), r#"{"refused":"bad-request"}"#);
        fs::remove_file(&lock_file).unwrap();
        // A body that nests the entry 64 deep is written and read back whole.
        let answer = append(deep_request(&path, 63).as_bytes()).unwrap();
        assert!(answer.opt("appended").is_some());
        let back = read(&request(&path, "")).unwrap();
        assert_eq!(back.get("entries").array().len(), 1);
        // A request deep somewhere other than its body is judged by its body.
        let other = format!(
            r#"{{"body":{{}},"extra":{}{},"kind":"note","ledger":{},"wait_ms":0}}"#,
            "[".repeat(5_000),
            "]".repeat(5_000),
            json::encode(&json::string(&path))
        );
        assert!(append(other.as_bytes()).unwrap().opt("appended").is_some());
        // Input that is not acceptable JSON is still an error, not a refusal.
        assert!(append(b"{\"body\":1,\"body\":2}").is_err());
        assert!(append(b"\xff").is_err());
        let _ = fs::remove_dir_all(&dir);
    }
    #[test]
    fn append_releases_the_lock_on_every_path() {
        let path = scratch("paths.ledger");
        let lock_file = format!("{path}.lock");
        let (_, want) = entries(&["a", "b"]);
        // Appended, to a file that does not exist and then to one that does.
        assert!(ask(&request(&path, "a"))
            .unwrap()
            .opt("appended")
            .is_some());
        assert!(!std::path::Path::new(&lock_file).exists());
        // A torn ending is cut off first.
        fs::write(
            &path,
            format!("{}dodona1 99 torn", &want[..want.find('\n').unwrap() + 1]),
        )
        .unwrap();
        assert!(ask(&request(&path, "b"))
            .unwrap()
            .opt("appended")
            .is_some());
        assert_eq!(fs::read_to_string(&path).unwrap(), want);
        assert!(!std::path::Path::new(&lock_file).exists());
        // Corrupt: refused, unchanged, lock released.
        fs::write(&path, "garbage\n").unwrap();
        let answer = ask(&request(&path, "c")).unwrap();
        assert_eq!(json::encode(&answer), r#"{"refused":"corrupt"}"#);
        assert_eq!(fs::read_to_string(&path).unwrap(), "garbage\n");
        assert!(!std::path::Path::new(&lock_file).exists());
        assert_eq!(
            json::encode(&read(&request(&path, "")).unwrap()),
            r#"{"at":1,"refused":"corrupt"}"#
        );
        // Held by someone else: refused, and their lock is left alone.
        fs::write(&lock_file, "theirs").unwrap();
        let answer = ask(&request(&path, "c")).unwrap();
        assert_eq!(json::encode(&answer), r#"{"refused":"locked"}"#);
        assert!(std::path::Path::new(&lock_file).exists());
        fs::remove_file(&lock_file).unwrap();
        // A ledger that cannot be read or written is an error, not `corrupt`, and leaves no lock.
        let dir = scratch("a-directory");
        fs::create_dir_all(&dir).unwrap();
        assert!(ask(&request(&dir, "c")).is_err());
        assert!(!std::path::Path::new(&format!("{dir}.lock")).exists());
        assert!(read(&request(&dir, "")).is_err());
        // Bad requests are refused before any lock is taken.
        let bad = json::object(vec![("ledger", json::string(&path))]);
        assert!(ask(&bad).is_err());
        assert!(!std::path::Path::new(&lock_file).exists());
        // No kind that is a non-empty string, or no body: refused, nothing written, no lock.
        let fresh = scratch("fresh.ledger");
        for (kind, body) in [
            (None, Some(Value::Null)),
            (Some(Value::Number(7)), Some(Value::Null)),
            (Some(Value::Null), Some(Value::Null)),
            (Some(json::string("")), Some(Value::Null)),
            (Some(json::string("act")), None),
        ] {
            let mut request = vec![
                ("ledger", json::string(&fresh)),
                ("wait_ms", Value::Number(0)),
            ];
            request.extend(kind.map(|k| ("kind", k)));
            request.extend(body.map(|b| ("body", b)));
            let answer = ask(&json::object(request)).unwrap();
            assert_eq!(json::encode(&answer), r#"{"refused":"bad-request"}"#);
            assert!(!std::path::Path::new(&fresh).exists());
            assert!(!std::path::Path::new(&format!("{fresh}.lock")).exists());
        }
        // Any other kind is kept, and a null body is a body.
        let odd = json::object(vec![
            ("ledger", json::string(&fresh)),
            ("kind", json::string("something-else")),
            ("body", Value::Null),
            ("wait_ms", Value::Number(0)),
        ]);
        assert!(ask(&odd).unwrap().opt("appended").is_some());
        assert!(ask(&request(&fresh, "after"))
            .unwrap()
            .opt("appended")
            .is_some());
        assert!(read(&request(&fresh, "")).unwrap().opt("entries").is_some());
        let _ = fs::remove_dir_all(std::path::Path::new(&path).parent().unwrap());
    }
}
