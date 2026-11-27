//! Reading and writing provider messages (protocol/README.md, "Framing";
//! conformance/README.md, "Session" and "Reading in a check").
//!
//! Standard output is read by a thread of its own, in chunks, and cut into lines
//! that are never held longer than the limit; standard error by another, which
//! counts everything and keeps only up to its cap. The host waits for a line on a
//! monotonic clock and never on the pipe itself.
use crate::json::{self, Value};
use crate::jsonread;
use crate::proc::Tree;
use std::io::{Read, Write};
use std::process::ChildStdin;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

/// How long a provider has to exit after `shutdown`.
pub const SHUTDOWN_GRACE: Duration = Duration::from_secs(1);
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

/// A JSON text read strictly, as the canonical encoding writes it, at any depth
/// and whole; only then is its depth measured. For a check's messages and an
/// executor's report.
pub fn strict(text: &str) -> Result<Value, &'static str> {
    let (v, depth) = match jsonread::parse(text, true) {
        Ok(read) => read,
        Err("invalid-string") => return Err("encoding"),
        Err(reason @ ("duplicate-key" | "not-an-integer")) => return Err(reason),
        Err(_) => return Err("malformed"),
    };
    if depth > MAX_DEPTH {
        return Err("too-deep");
    }
    Ok(v)
}

/// One line read as a message, or why it is not one. `strict` is the reading
/// of a check; a session reads any valid JSON.
pub fn message(line: &[u8], strict: bool) -> Result<Value, &'static str> {
    if line.starts_with(b"\xef\xbb\xbf") || line.ends_with(b"\r") {
        return Err("framing");
    }
    let text = std::str::from_utf8(line).map_err(|_| "encoding")?;
    let v = if strict {
        self::strict(text)?
    } else {
        jsonread::parse(text, false).map_err(|_| "malformed")?.0
    };
    match v.opt("type") {
        Some(Value::String(_)) if matches!(v, Value::Object(_)) => Ok(v),
        _ => Err("malformed"),
    }
}

/// A provider started as a tree, with its standard output read as lines.
pub struct Peer {
    pub tree: Tree,
    writer: Option<Writer>,
    rx: Receiver<Event>,
    closed: bool,
    strict: bool,
    /// Whether a `shutdown` message was written whole by `shutdown`.
    said_shutdown: bool,
    /// Whether `shutdown` gives the provider its whole grace even after it
    /// writes something more (see `wait_out_grace`).
    patient: bool,
}
/// Standard input of the provider, written by a thread of its own, so that a
/// provider that stops reading cannot hold the host past a deadline.
struct Writer {
    tx: mpsc::Sender<Vec<u8>>,
    written: Receiver<bool>,
    /// Messages handed to the thread and not yet reported written.
    behind: usize,
}
impl Writer {
    fn new(mut stdin: ChildStdin) -> Writer {
        let (tx, rx) = mpsc::channel::<Vec<u8>>();
        let (done, written) = mpsc::channel();
        std::thread::spawn(move || {
            for text in rx {
                let ok = stdin.write_all(&text).and_then(|_| stdin.flush()).is_ok();
                if done.send(ok).is_err() || !ok {
                    return;
                }
            }
        });
        Writer {
            tx,
            written,
            behind: 0,
        }
    }
}
impl Peer {
    pub fn new(mut tree: Tree, max_line: usize, strict: bool) -> Peer {
        let writer = tree.child.stdin.take().map(Writer::new);
        let stdout = tree.child.stdout.take().expect("standard output is piped");
        Peer {
            tree,
            writer,
            rx: lines(stdout, max_line),
            closed: false,
            strict,
            said_shutdown: false,
            patient: false,
        }
    }
    /// From now on `shutdown` waits out the provider's grace even when it writes
    /// something more after `shutdown` was sent (a late answer to an earlier
    /// request, say), so that it can still read `shutdown` and exit on its own
    /// as a provider is given a moment to do. What it wrote is read and dropped,
    /// never taken as an answer, and `shutdown` still says `unexpected`.
    pub fn wait_out_grace(&mut self) {
        self.patient = true;
    }
    /// Whether `shutdown` has written its message whole to the provider.
    pub fn said_shutdown(&self) -> bool {
        self.said_shutdown
    }
    /// Send one message, written whole no later than `until`. A provider that
    /// cannot be written to has gone away.
    pub fn send(&mut self, v: &Value, until: Instant) -> Result<(), &'static str> {
        let w = self.writer.as_mut().ok_or("closed")?;
        let mut text = json::encode(v).into_bytes();
        text.push(b'\n');
        w.tx.send(text).map_err(|_| "closed")?;
        w.behind += 1;
        while w.behind > 0 {
            match w
                .written
                .recv_timeout(until.saturating_duration_since(Instant::now()))
            {
                Ok(true) => w.behind -= 1,
                Ok(false) | Err(RecvTimeoutError::Disconnected) => return Err("closed"),
                Err(RecvTimeoutError::Timeout) => return Err("deadline"),
            }
        }
        Ok(())
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
        let said = self
            .send(
                &json::object(vec![("type", json::string("shutdown"))]),
                until,
            )
            .is_ok();
        self.said_shutdown |= said;
        // The provider has a second to exit, less if the deadline is nearer; one
        // still running then is ended with everything it started, its answer standing.
        let grace = (Instant::now() + SHUTDOWN_GRACE).min(until);
        let mut late = false;
        while !self.tree.exited() && Instant::now() < grace {
            match self.event((Instant::now() + Duration::from_millis(10)).min(grace)) {
                Some(Event::Line(_)) | Some(Event::TooLong) if self.patient => late = true,
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
            _ if late => Err("unexpected"),
            _ => Ok(()),
        }
    }
    /// End the provider and everything it started.
    pub fn end(&mut self) {
        self.writer = None;
        self.tree.end();
    }
}

#[cfg(test)]
mod late_tests {
    use super::*;
    use std::io::BufRead;
    use std::process::{Command, Stdio};

    const MARK: &str = "DODONA_WIRE_LATE_MARK";

    /// The provider the test below starts: it writes a late line, waits a
    /// little, and only then reads its input; if that is `shutdown`, it leaves
    /// a file where `MARK` says and exits on its own.
    #[test]
    #[ignore = "the provider a shutdown test starts; not a test of its own"]
    fn late_provider() {
        let Some(mark) = std::env::var_os(MARK) else {
            return;
        };
        std::thread::sleep(Duration::from_millis(50));
        let mut out = std::io::stdout().lock();
        let _ = out.write_all(b"{\"type\":\"result\",\"id\":\"late\"}\n");
        let _ = out.flush();
        drop(out);
        std::thread::sleep(Duration::from_millis(200));
        let mut line = String::new();
        let _ = std::io::stdin().lock().read_line(&mut line);
        if line.contains("shutdown") {
            let _ = std::fs::write(mark, b"read shutdown");
        }
    }

    fn start(mark: &std::path::Path) -> Peer {
        let exe = std::env::current_exe().unwrap();
        let tree = Tree::spawn(
            Command::new(exe)
                .args(["--ignored", "--exact", "wire::late_tests::late_provider", "--quiet", "--test-threads=1"])
                .env(MARK, mark)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::null()),
        )
        .unwrap();
        Peer::new(tree, 1 << 20, true)
    }

    #[test]
    fn a_late_line_after_shutdown_does_not_cut_the_grace_short() {
        let dir = std::env::temp_dir().join(format!("dodona-wire-late-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        // Waiting out the grace: the provider reads `shutdown` and exits on its
        // own; what it wrote late is still `unexpected`, and read as nothing else.
        let patient = dir.join("patient");
        let mut p = start(&patient);
        p.wait_out_grace();
        assert_eq!(p.shutdown(Instant::now() + SHUTDOWN_GRACE), Err("unexpected"));
        assert!(p.said_shutdown());
        p.end();
        assert!(patient.exists());
        // Control, as every other caller has it: the first late line ends the
        // wait, the provider is ended before it reads `shutdown`, and leaves no file.
        let impatient = dir.join("impatient");
        let mut q = start(&impatient);
        assert_eq!(q.shutdown(Instant::now() + SHUTDOWN_GRACE), Err("unexpected"));
        q.end();
        std::thread::sleep(Duration::from_millis(500));
        assert!(!impatient.exists());
        let _ = std::fs::remove_dir_all(&dir);
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
        // A session reads valid JSON as JSON: the last of a repeated key stands.
        assert_eq!(message(dup, false).unwrap().text("type"), Some("y"));
        assert!(message(b"{\"type\":\"x\",\"n\":1.5}", false).is_ok());
        assert_eq!(
            message(b"{\"type\":\"x\",\"n\":9007199254740992}", true).unwrap_err(),
            "not-an-integer"
        );
        assert_eq!(
            message(b"{\"type\":\"x\",\"s\":\"\\ud800\"}", true).unwrap_err(),
            "encoding"
        );
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
        assert!(message(&deep(64), false).is_ok());
        assert!(message(&deep(100_000), false).is_ok());
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
        assert!(ECHO.chars().any(|c| c < ' ') && !ECHO.is_ascii());
    }
}
