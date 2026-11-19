//! One provider session (conformance/README.md, "Session"):
//!
//!     dodona-kernel session --deadline-ms N --max-line N --max-log N -- <provider argv>
//!
//! hello, the manifest with its echo, one `decision.index` request, shutdown,
//! and every process the provider started ended. One deadline covers it all.
use crate::json::{self, Value};
use crate::proc::{self, Tree};
use crate::wire::{self, Log, Peer};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

pub struct Limits {
    pub deadline_ms: u64,
    pub max_line: usize,
    pub max_log: usize,
}

/// The limits and the provider command, from the arguments after `session`.
pub fn arguments(args: &[String]) -> Result<(Limits, Vec<String>), String> {
    let split = args
        .iter()
        .position(|a| a == "--")
        .ok_or("no `--` before the provider command")?;
    let (flags, provider) = (&args[..split], &args[split + 1..]);
    if provider.is_empty() {
        return Err("no provider command after `--`".into());
    }
    let (mut deadline, mut line, mut log) = (None, None, None);
    let mut it = flags.iter();
    while let Some(flag) = it.next() {
        let value: u64 = it
            .next()
            .and_then(|v| v.parse().ok())
            .ok_or(format!("`{flag}` needs a whole number"))?;
        match flag.as_str() {
            "--deadline-ms" => deadline = Some(value),
            "--max-line" => line = Some(value),
            "--max-log" => log = Some(value),
            other => return Err(format!("no option `{other}`")),
        }
    }
    let missing = |name: &str| format!("`{name}` is required");
    Ok((
        Limits {
            deadline_ms: deadline.ok_or_else(|| missing("--deadline-ms"))?,
            max_line: line.ok_or_else(|| missing("--max-line"))? as usize,
            max_log: log.ok_or_else(|| missing("--max-log"))? as usize,
        },
        provider.to_vec(),
    ))
}

pub fn hello(max_line: usize, deadline_ms: u64) -> Value {
    json::object(vec![
        ("type", json::string("hello")),
        ("protocol", Value::Array(vec![json::string("0.2")])),
        (
            "limits",
            json::object(vec![
                ("max_line_bytes", Value::Number(max_line as i64)),
                ("deadline_ms", Value::Number(deadline_ms as i64)),
            ]),
        ),
        ("echo", json::string(wire::ECHO)),
    ])
}

/// Whether an answer to hello is a manifest that returns the echo unchanged.
pub fn manifest_ok(m: &Value) -> bool {
    m.text("type") == Some("manifest")
        && m.text("echo") == Some(wire::ECHO)
        && matches!(m.opt("manifest"), Some(Value::Object(_)))
}

/// Why an answer is not the result of request `id` for `capability`, if it is not.
pub fn answer_fault(a: &Value, id: &str, capability: &str) -> Option<&'static str> {
    if a.text("id") != Some(id) {
        return Some("wrong-id");
    }
    match a.text("type") {
        Some("result") => {}
        Some("error") => return Some("provider-error"),
        _ => return Some("unexpected"),
    }
    if a.text("capability") != Some(capability) {
        return Some("wrong-capability");
    }
    None
}

fn hold(peer: &mut Peer, limits: &Limits, until: Instant) -> Result<(), &'static str> {
    peer.send(&hello(limits.max_line, limits.deadline_ms), until)?;
    if !manifest_ok(&peer.read(until)?) {
        return Err("bad-manifest");
    }
    peer.send(
        &json::object(vec![
            ("type", json::string("request")),
            ("id", json::string("1")),
            ("deadline_ms", Value::Number(limits.deadline_ms as i64)),
            ("capability", json::string("decision.index")),
            ("body", json::object(vec![("files", Value::Array(vec![]))])),
        ]),
        until,
    )?;
    if let Some(fault) = answer_fault(&peer.read(until)?, "1", "decision.index") {
        return Err(fault);
    }
    peer.shutdown(until)
}

pub fn run(args: &[String]) -> Result<Value, String> {
    let (limits, provider) = arguments(args)?;
    let until = Instant::now() + Duration::from_millis(limits.deadline_ms);
    let tree = Tree::spawn(
        Command::new(&provider[0])
            .args(&provider[1..])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped()),
    );
    let mut tree = match tree {
        Ok(t) => t,
        Err(e) if proc::unconfined(&e) => return Err(e.to_string()),
        Err(_) => return Ok(outcome(Err("closed"), 0, false)),
    };
    let log = Log::drain(tree.child.stderr.take().expect("piped"), limits.max_log);
    let mut peer = Peer::new(tree, limits.max_line, false);
    let result = hold(&mut peer, &limits, until);
    peer.end();
    log.settle();
    let bytes = log.total();
    Ok(outcome(result, bytes, bytes > limits.max_log as u64))
}

fn outcome(result: Result<(), &str>, log_bytes: u64, truncated: bool) -> Value {
    let mut fields = match result {
        Ok(()) => vec![("outcome", json::string("ok"))],
        Err(reason) => vec![
            ("outcome", json::string("error")),
            ("reason", json::string(reason)),
        ],
    };
    fields.push(("log_bytes", Value::Number(log_bytes as i64)));
    fields.push(("log_truncated", Value::Bool(truncated)));
    json::object(fields)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn strings(s: &[&str]) -> Vec<String> {
        s.iter().map(|x| x.to_string()).collect()
    }
    #[test]
    fn reads_its_arguments() {
        let (l, p) = arguments(&strings(&[
            "--deadline-ms",
            "3000",
            "--max-line",
            "1024",
            "--max-log",
            "5",
            "--",
            "prov",
            "a",
        ]))
        .unwrap();
        assert_eq!((l.deadline_ms, l.max_line, l.max_log), (3000, 1024, 5));
        assert_eq!(p, ["prov", "a"]);
        assert!(arguments(&strings(&["--deadline-ms", "1", "--", "p"])).is_err());
        assert!(arguments(&strings(&["--deadline-ms", "x", "--", "p"])).is_err());
        assert!(arguments(&strings(&[
            "--deadline-ms",
            "1",
            "--max-line",
            "1",
            "--max-log",
            "1",
            "--"
        ]))
        .is_err());
        assert!(arguments(&strings(&["--other", "1", "--", "p"])).is_err());
    }
    #[test]
    fn judges_answers() {
        let m = |s: &str| json::parse(s.as_bytes()).unwrap();
        let echo = json::encode(&json::string(wire::ECHO));
        assert!(manifest_ok(&m(&format!(
            r#"{{"type":"manifest","echo":{echo},"manifest":{{}}}}"#
        ))));
        assert!(!manifest_ok(&m(&format!(
            r#"{{"type":"manifest","echo":{echo},"manifest":[]}}"#
        ))));
        assert!(!manifest_ok(&m(
            r#"{"type":"manifest","echo":"x","manifest":{}}"#
        )));
        assert!(!manifest_ok(&m(&format!(
            r#"{{"type":"result","echo":{echo},"manifest":{{}}}}"#
        ))));
        let c = "decision.index";
        assert_eq!(
            answer_fault(
                &m(r#"{"type":"result","id":"1","capability":"decision.index"}"#),
                "1",
                c
            ),
            None
        );
        assert_eq!(
            answer_fault(
                &m(r#"{"type":"result","id":"2","capability":"decision.index"}"#),
                "1",
                c
            ),
            Some("wrong-id")
        );
        assert_eq!(
            answer_fault(&m(r#"{"type":"error","id":"1"}"#), "1", c),
            Some("provider-error")
        );
        assert_eq!(
            answer_fault(&m(r#"{"type":"hello","id":"1"}"#), "1", c),
            Some("unexpected")
        );
        assert_eq!(
            answer_fault(&m(r#"{"type":"result","id":"1","capability":"x"}"#), "1", c),
            Some("wrong-capability")
        );
    }
}
