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
fn entry(line: &[u8], previous: Option<&str>) -> Option<Value> {
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
    let entry = json::parse(payload.as_bytes()).ok()?;
    let shaped = matches!(&entry, Value::Object(fields) if fields.len() == 3)
        && matches!(entry.opt("kind"), Some(Value::String(_)))
        && entry.opt("body").is_some()
        && match (entry.opt("previous"), previous) {
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
    let mut previous: Option<String> = None;
    if end > 0 {
        for (i, line) in data[..end - 1].split(|b| *b == b'\n').enumerate() {
            let e = entry(line, previous.as_deref()).ok_or(i + 1)?;
            previous = Some(canonical::identity(&e));
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
pub fn append(v: &Value) -> Result<Value, String> {
    // Everything the caller supplies is checked before the lock is taken.
    let path = field(v, "ledger")?;
    let kind = field(v, "kind")?;
    let body = v.opt("body").ok_or("`body` is missing")?;
    let wait = match v.opt("wait_ms") {
        Some(Value::Number(n)) => Duration::from_millis((*n).max(0) as u64),
        _ => return Err("`wait_ms` must be a number".into()),
    };
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
    #[test]
    fn append_releases_the_lock_on_every_path() {
        let path = scratch("paths.ledger");
        let lock_file = format!("{path}.lock");
        let (_, want) = entries(&["a", "b"]);
        // Appended, to a file that does not exist and then to one that does.
        assert!(append(&request(&path, "a"))
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
        assert!(append(&request(&path, "b"))
            .unwrap()
            .opt("appended")
            .is_some());
        assert_eq!(fs::read_to_string(&path).unwrap(), want);
        assert!(!std::path::Path::new(&lock_file).exists());
        // Corrupt: refused, unchanged, lock released.
        fs::write(&path, "garbage\n").unwrap();
        let answer = append(&request(&path, "c")).unwrap();
        assert_eq!(json::encode(&answer), r#"{"refused":"corrupt"}"#);
        assert_eq!(fs::read_to_string(&path).unwrap(), "garbage\n");
        assert!(!std::path::Path::new(&lock_file).exists());
        assert_eq!(
            json::encode(&read(&request(&path, "")).unwrap()),
            r#"{"at":1,"refused":"corrupt"}"#
        );
        // Held by someone else: refused, and their lock is left alone.
        fs::write(&lock_file, "theirs").unwrap();
        let answer = append(&request(&path, "c")).unwrap();
        assert_eq!(json::encode(&answer), r#"{"refused":"locked"}"#);
        assert!(std::path::Path::new(&lock_file).exists());
        fs::remove_file(&lock_file).unwrap();
        // A ledger that cannot be read or written is an error, not `corrupt`, and leaves no lock.
        let dir = scratch("a-directory");
        fs::create_dir_all(&dir).unwrap();
        assert!(append(&request(&dir, "c")).is_err());
        assert!(!std::path::Path::new(&format!("{dir}.lock")).exists());
        assert!(read(&request(&dir, "")).is_err());
        // Bad requests are refused before any lock is taken.
        let bad = json::object(vec![("ledger", json::string(&path))]);
        assert!(append(&bad).is_err());
        assert!(!std::path::Path::new(&lock_file).exists());
        let _ = fs::remove_dir_all(std::path::Path::new(&path).parent().unwrap());
    }
}
