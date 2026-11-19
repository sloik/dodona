//! Reading and writing provider messages (protocol/README.md, "Framing";
//! conformance/README.md, "Session" and "Reading in a check").
//!
//! Standard output is read by a thread of its own, in chunks, and cut into lines
//! that are never held longer than the limit; standard error by another, which
//! counts everything and keeps only up to its cap. The host waits for a line on a
//! monotonic clock and never on the pipe itself.
use crate::json::{self, Value};
use crate::proc::Tree;
use std::io::{Read, Write};
use std::process::ChildStdin;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

/// How deeply a message read strictly may nest.
pub const MAX_DEPTH: usize = 64;
/// The opening echo: non-ASCII letters, a character outside the Basic
/// Multilingual Plane and control characters.
pub const ECHO: &str = "zażółć gęślą jaźń \u{1}\u{7}\t\u{1b}\u{1f}\u{7f} ü 😀 ☃";

pub enum Event {
    Line(Vec<u8>),
    TooLong,
    Closed,
}

/// Lines from `source`, each without its line feed. A line longer than `max`
/// bytes is reported as too long as soon as it is, and nothing more is read.
pub fn lines(mut source: impl Read + Send + 'static, max: usize) -> Receiver<Event> {
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let mut line = Vec::new();
        let mut chunk = vec![0u8; 65536];
        loop {
            let n = match source.read(&mut chunk) {
                Ok(0) | Err(_) => {
                    let _ = tx.send(Event::Closed);
                    return;
                }
                Ok(n) => n,
            };
            let mut rest = &chunk[..n];
            while !rest.is_empty() {
                let end = rest.iter().position(|b| *b == b'\n');
                let part = &rest[..end.unwrap_or(rest.len())];
                if line.len() + part.len() > max {
                    let _ = tx.send(Event::TooLong);
                    return;
                }
                line.extend_from_slice(part);
                match end {
                    Some(i) => {
                        if tx.send(Event::Line(std::mem::take(&mut line))).is_err() {
                            return;
                        }
                        rest = &rest[i + 1..];
                    }
                    None => rest = &[],
                }
            }
        }
    });
    rx
}

/// Standard error, read all the time: how many bytes came, what was kept, and a
/// signal when it ends.
pub struct Log {
    pub bytes: Arc<AtomicU64>,
    /// What is kept of it, for the log attachment a record will carry.
    #[allow(dead_code)]
    pub kept: Arc<Mutex<Vec<u8>>>,
    done: Receiver<()>,
}
impl Log {
    pub fn drain(mut source: impl Read + Send + 'static, cap: usize) -> Log {
        let bytes = Arc::new(AtomicU64::new(0));
        let kept = Arc::new(Mutex::new(Vec::new()));
        let (tx, done) = mpsc::channel();
        let (b, k) = (bytes.clone(), kept.clone());
        std::thread::spawn(move || {
            let mut chunk = vec![0u8; 65536];
            while let Ok(n) = source.read(&mut chunk) {
                if n == 0 {
                    break;
                }
                b.fetch_add(n as u64, Ordering::SeqCst);
                if let Ok(mut kept) = k.lock() {
                    let room = cap.saturating_sub(kept.len()).min(n);
                    kept.extend_from_slice(&chunk[..room]);
                }
            }
            let _ = tx.send(());
        });
        Log { bytes, kept, done }
    }
    /// Wait a little for the end of standard error, once every process is gone.
    pub fn settle(&self) {
        let _ = self.done.recv_timeout(Duration::from_secs(2));
    }
    pub fn total(&self) -> u64 {
        self.bytes.load(Ordering::SeqCst)
    }
}

/// The deepest nesting of arrays and objects in a JSON text.
pub fn depth(text: &[u8]) -> usize {
    let (mut depth, mut deepest, mut in_string, mut escaped) = (0usize, 0usize, false, false);
    for &b in text {
        if in_string {
            if escaped {
                escaped = false;
            } else if b == b'\\' {
                escaped = true;
            } else if b == b'"' {
                in_string = false;
            }
            continue;
        }
        match b {
            b'"' => in_string = true,
            b'[' | b'{' => {
                depth += 1;
                deepest = deepest.max(depth);
            }
            b']' | b'}' => depth = depth.saturating_sub(1),
            _ => {}
        }
    }
    deepest
}

/// One line read as a message, or why it is not one. `strict` is the reading
/// of a check: the canonical encoding's refusals have reasons of their own.
pub fn message(line: &[u8], strict: bool) -> Result<Value, &'static str> {
    if line.starts_with(b"\xef\xbb\xbf") || line.ends_with(b"\r") {
        return Err("framing");
    }
    if std::str::from_utf8(line).is_err() {
        return Err("encoding");
    }
    if depth(line) > MAX_DEPTH {
        return Err(if strict { "too-deep" } else { "malformed" });
    }
    let v = match json::parse(line) {
        Ok(v) => v,
        Err("duplicate-key") if strict => return Err("duplicate-key"),
        Err("not-an-integer") if strict => return Err("not-an-integer"),
        Err(_) => return Err("malformed"),
    };
    match v.opt("type") {
        Some(Value::String(_)) if matches!(v, Value::Object(_)) => Ok(v),
        _ => Err("malformed"),
    }
}

/// A provider started as a tree, with its standard output read as lines.
pub struct Peer {
    pub tree: Tree,
    stdin: Option<ChildStdin>,
    rx: Receiver<Event>,
    closed: bool,
    strict: bool,
}
impl Peer {
    pub fn new(mut tree: Tree, max_line: usize, strict: bool) -> Peer {
        let stdin = tree.child.stdin.take();
        let stdout = tree.child.stdout.take().expect("standard output is piped");
        Peer {
            tree,
            stdin,
            rx: lines(stdout, max_line),
            closed: false,
            strict,
        }
    }
    /// Send one message. A provider that cannot be written to has gone away.
    pub fn send(&mut self, v: &Value) -> Result<(), &'static str> {
        let stdin = self.stdin.as_mut().ok_or("closed")?;
        let mut text = json::encode(v).into_bytes();
        text.push(b'\n');
        stdin
            .write_all(&text)
            .and_then(|_| stdin.flush())
            .map_err(|_| "closed")
    }
    /// The next event, or None at `until`.
    fn event(&mut self, until: Instant) -> Option<Event> {
        if self.closed {
            return Some(Event::Closed);
        }
        let event = match self
            .rx
            .recv_timeout(until.saturating_duration_since(Instant::now()))
        {
            Ok(e) => e,
            Err(RecvTimeoutError::Timeout) => return None,
            Err(RecvTimeoutError::Disconnected) => Event::Closed,
        };
        if matches!(event, Event::Closed | Event::TooLong) {
            self.closed = true;
        }
        Some(event)
    }
    /// The next message, waiting no later than `until`.
    pub fn read(&mut self, until: Instant) -> Result<Value, &'static str> {
        match self.event(until) {
            None => Err("deadline"),
            Some(Event::TooLong) => Err("too-long"),
            Some(Event::Closed) => Err("closed"),
            Some(Event::Line(line)) => message(&line, self.strict),
        }
    }
    /// After the last answer: say `shutdown`, wait no later than `until` for the
    /// provider to end, end everything it started, and read what it wrote to the
    /// end. Anything more than nothing is `unexpected`.
    pub fn shutdown(&mut self, until: Instant) -> Result<(), &'static str> {
        let _ = self.send(&json::object(vec![("type", json::string("shutdown"))]));
        while !self.tree.exited() {
            if Instant::now() >= until {
                return Err("deadline");
            }
            match self.event((Instant::now() + Duration::from_millis(10)).min(until)) {
                Some(Event::Line(_)) | Some(Event::TooLong) => return Err("unexpected"),
                Some(Event::Closed) => std::thread::sleep(Duration::from_millis(10)),
                None => {}
            }
        }
        self.end();
        // Every process is gone, so standard output ends after whatever was written.
        let wait = Instant::now() + Duration::from_secs(2);
        match self.event(wait) {
            Some(Event::Line(_)) | Some(Event::TooLong) => Err("unexpected"),
            _ => Ok(()),
        }
    }
    /// End the provider and everything it started.
    pub fn end(&mut self) {
        self.stdin = None;
        self.tree.end();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn reading_a_line() {
        assert_eq!(
            message(b"\xef\xbb\xbf{\"type\":\"x\"}", true).unwrap_err(),
            "framing"
        );
        assert_eq!(message(b"{\"type\":\"x\"}\r", true).unwrap_err(), "framing");
        assert_eq!(
            message(b"{\"type\":\"\xff\"}", true).unwrap_err(),
            "encoding"
        );
        assert_eq!(message(b"[1,2,3]", true).unwrap_err(), "malformed");
        assert_eq!(message(b"{\"type\":1}", true).unwrap_err(), "malformed");
        assert_eq!(message(b"not json", false).unwrap_err(), "malformed");
        let dup = b"{\"type\":\"x\",\"type\":\"y\"}";
        assert_eq!(message(dup, true).unwrap_err(), "duplicate-key");
        assert_eq!(message(dup, false).unwrap_err(), "malformed");
        assert_eq!(
            message(b"{\"type\":\"x\",\"n\":1.0}", true).unwrap_err(),
            "not-an-integer"
        );
        let deep = |n: usize| {
            format!(
                "{{\"type\":\"x\",\"v\":{}{}}}",
                "[".repeat(n),
                "]".repeat(n)
            )
            .into_bytes()
        };
        assert!(message(&deep(63), true).is_ok());
        assert_eq!(message(&deep(64), true).unwrap_err(), "too-deep");
        assert_eq!(message(&deep(64), false).unwrap_err(), "malformed");
        assert_eq!(depth(br#"{"a":"[[[{"}"#), 1);
        assert_eq!(depth(br#"{"a":"\"[["}"#), 1);
        assert!(message(b"{\"type\":\"hello\"}", true).is_ok());
    }
    #[test]
    fn cutting_lines() {
        let rx = lines(&b"one\ntwo\nthree"[..], 10);
        let mut got = Vec::new();
        while let Ok(e) = rx.recv() {
            match e {
                Event::Line(l) => got.push(String::from_utf8(l).unwrap()),
                Event::TooLong => got.push("too long".into()),
                Event::Closed => break,
            }
        }
        assert_eq!(got, ["one", "two"]);
        let rx = lines(&b"short\nthis line is too long\n"[..], 10);
        assert!(matches!(rx.recv().unwrap(), Event::Line(_)));
        assert!(matches!(rx.recv().unwrap(), Event::TooLong));
        let rx = lines(&b"0123456789\n"[..], 10);
        assert!(matches!(rx.recv().unwrap(), Event::Line(l) if l.len() == 10));
    }
    #[test]
    fn the_echo_survives_encoding() {
        let v = json::object(vec![("echo", json::string(ECHO))]);
        let back = json::parse(json::encode(&v).as_bytes()).unwrap();
        assert_eq!(back.text("echo"), Some(ECHO));
        assert!(ECHO.chars().any(|c| c < ' ') && ECHO.chars().any(|c| !c.is_ascii()));
    }
}
