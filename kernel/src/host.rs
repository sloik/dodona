//! One check taken from a provider to a verdict (conformance/README.md, "Host
//! checks: rules a schema cannot express"). The provider and the executor are
//! commands the kernel is given; it names neither.
//!
//! The rules are pure functions of what the provider said and what the check was
//! given, each returning the reason it is broken: `read_input` for the host's own
//! input, `manifest` for the manifest, `run_fault` for a `next`, `report_fault`
//! for what an executor reports, `final_verdict` for a `final`.
use crate::canonical;
use crate::json::{self, Value};
use crate::path;
use crate::proc::Tree;
use crate::session::{answer_fault, hello};
use crate::wire::{self, Log, Peer};
use std::io::{Read, Write};
use std::path::Path;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

/// A check may ask for this many runs; the next is refused.
pub const MAX_RUNS: usize = 8;
/// The longest line the host reads from a provider in a check.
pub const MAX_LINE: usize = 1 << 20;
/// The strength ranks, weakest first.
pub const RANKS: [&str; 4] = ["documented", "sampled", "bounded", "exhaustive"];
/// The verdicts a provider may give.
pub const VERDICTS: [&str; 4] = ["passed", "failed", "error", "unsupported"];
/// The largest attachment the host hashes again.
pub const MAX_ATTACHMENT: u64 = 64 << 20;
/// The longest the host waits for an executor beyond its deadline: 24 hours.
pub const MAX_WALL_MS: u64 = 24 * 60 * 60 * 1000;

/// What the check was given, and what the manifest declared.
pub struct Given {
    pub obligation: Value,
    pub inputs: Vec<(String, String)>,
    pub tools: Vec<(String, String)>,
    pub platform: Value,
    pub declared: Vec<String>,
    pub ceiling: Ceiling,
}
/// The class and rank the manifest declares for `obligation.check`, if it does.
pub type Ceiling = Option<(String, String)>;

impl Given {
    /// The files the obligation names: `specified_by`, then `targets`.
    pub fn named(&self) -> Vec<String> {
        let mut names = Vec::new();
        for field in ["specified_by", "targets"] {
            names.extend(
                strings(self.obligation.opt(field))
                    .into_iter()
                    .map(str::to_owned),
            );
        }
        names
    }
}

fn same(a: Option<&Value>, b: Option<&Value>) -> bool {
    match (a, b) {
        (Some(a), Some(b)) => json::encode(a) == json::encode(b),
        _ => false,
    }
}

fn is_object(v: Option<&Value>) -> bool {
    matches!(v, Some(Value::Object(_)))
}

/// The strings of a list, leaving out anything else in it.
fn strings(v: Option<&Value>) -> Vec<&str> {
    match v {
        Some(Value::Array(a)) => a
            .iter()
            .filter_map(|x| match x {
                Value::String(s) => Some(s.as_str()),
                _ => None,
            })
            .collect(),
        _ => vec![],
    }
}

/// Whether a value is a list of strings.
fn all_strings(v: Option<&Value>) -> bool {
    matches!(v, Some(Value::Array(a)) if a.len() == strings(v).len())
}

/// Whether a value is a list of objects, each with a string under every field named.
fn objects_with(v: Option<&Value>, fields: &[&str]) -> bool {
    matches!(v, Some(Value::Array(a)) if a.iter().all(|e| {
        matches!(e, Value::Object(_)) && fields.iter().all(|f| e.text(f).is_some())
    }))
}

/// The values under one string field of each entry of a list.
fn field_of<'a>(v: Option<&'a Value>, field: &str) -> Vec<&'a str> {
    match v {
        Some(Value::Array(a)) => a.iter().filter_map(|e| e.text(field)).collect(),
        _ => vec![],
    }
}

/// Every `${tool:NAME}` in an argument, with what follows it up to the end.
fn tool_refs(arg: &str) -> Vec<(&str, &str)> {
    let mut found = Vec::new();
    let mut rest = arg;
    while let Some(at) = rest.find("${tool:") {
        let after = &rest[at + "${tool:".len()..];
        match after.find('}') {
            Some(close) => {
                found.push((&after[..close], &after[close + 1..]));
                rest = &after[close + 1..];
            }
            None => break,
        }
    }
    found
}

fn passes(p: &str) -> bool {
    path::check(p.as_bytes()).is_none()
}

/// A character that can start or join a path, or is not printable ASCII.
fn needs_to_be_a_file(arg: &str) -> bool {
    arg.contains("..")
        || arg
            .chars()
            .any(|c| "/\\~@$%".contains(c) || !(' '..='~').contains(&c))
}

/// Whether an argument is, whole, one file of a tool: `${tool:NAME}/PATH`.
/// What PATH may hold is rule 5's.
fn whole_tool_file(arg: &str) -> bool {
    let refs = tool_refs(arg);
    refs.len() == 1 && arg.starts_with("${tool:") && refs[0].1.starts_with('/')
}

/// Rule 5 for the PATH of `${tool:NAME}/PATH`: the path check, and every
/// segment ASCII letters, digits, `.`, `_` and `-` only, so that nothing can be
/// carried after the file.
fn tool_file_passes(file: &str) -> bool {
    passes(file)
        && file.split('/').all(|s| {
            s.chars()
                .all(|c| c.is_ascii_alphanumeric() || "._-".contains(c))
        })
}

/// Rule 2: whether a run description has its shape. `env` is left to rule 7.
pub fn described(run: &Value) -> bool {
    let program = run.opt("program");
    let integers = |l: &Value| match l {
        Value::Object(o) => o.iter().all(|(_, v)| matches!(v, Value::Number(_))),
        _ => false,
    };
    matches!(run, Value::Object(_))
        && is_object(program)
        && program.is_some_and(|p| p.text("tool").is_some() && p.text("path").is_some())
        && matches!(run.opt("args"), Some(Value::Array(_)))
        && objects_with(run.opt("inputs"), &["path", "identity"])
        && objects_with(run.opt("outputs"), &["path"])
        && objects_with(run.opt("tools"), &["name", "digest"])
        && is_object(run.opt("platform"))
        && run.opt("cwd").is_none_or(|c| matches!(c, Value::String(_)))
        && run.opt("limits").is_none_or(integers)
}

/// Why a run the provider asks for may not start, if it may not. `runs` is how
/// many runs this check has already started. The rules are kept in their order.
pub fn run_fault(g: &Given, runs: usize, run: &Value) -> Option<&'static str> {
    // 1. No more than eight runs.
    if runs >= MAX_RUNS {
        return Some("too-many-runs");
    }
    // 2. The description has its shape.
    if !described(run) {
        return Some("bad-description");
    }
    let program = run.get("program");
    let args = strings(run.opt("args"));
    let inputs = field_of(run.opt("inputs"), "path");
    let outputs = field_of(run.opt("outputs"), "path");
    let run_tools = run.get("tools").array();
    // 3. The platform the check was asked for.
    if !same(run.opt("platform"), Some(&g.platform)) {
        return Some("platform-mismatch");
    }
    // 4. Every tool named is declared, and given to this check by digest.
    let mut named = vec![program.text("tool").unwrap_or_default()];
    named.extend(args.iter().flat_map(|a| tool_refs(a)).map(|(name, _)| name));
    if named.iter().any(|t| !g.declared.iter().any(|d| d == t)) {
        return Some("undeclared-tool");
    }
    if named.iter().any(|t| !g.tools.iter().any(|(n, _)| n == t)) {
        return Some("tool-not-in-key");
    }
    let given = |e: &Value| {
        g.tools
            .iter()
            .find(|(n, _)| Some(n.as_str()) == e.text("name"))
    };
    if run_tools.iter().any(|e| given(e).is_none()) {
        return Some("tool-not-in-key");
    }
    if run_tools
        .iter()
        .any(|e| given(e).map(|(_, d)| d.as_str()) != e.text("digest"))
    {
        return Some("tool-digest-mismatch");
    }
    // 5. Every path passes the path check. An argument holding NUL is left to rule 10.
    let words: Vec<&str> = args.iter().copied().filter(|a| !a.contains('\0')).collect();
    let mut paths = vec![program.text("path").unwrap_or_default()];
    paths.extend(inputs.iter().chain(outputs.iter()));
    let tool_files: Vec<&str> = words
        .iter()
        .flat_map(|a| tool_refs(a))
        .filter_map(|(_, after)| after.strip_prefix('/'))
        .collect();
    paths.extend(run.text("cwd"));
    if !paths.iter().all(|p| passes(p)) {
        return Some("bad-path");
    }
    if !tool_files.iter().all(|f| tool_file_passes(f)) {
        return Some("bad-path");
    }
    // 6. An argument that could name a file is, whole, one of the run's files.
    let file_arg = |a: &&str| inputs.contains(a) || whole_tool_file(a);
    if words.iter().any(|a| needs_to_be_a_file(a) && !file_arg(a)) {
        return Some("bad-path");
    }
    // 7. No environment, whatever its value.
    if run.opt("env").is_some() {
        return Some("env-not-allowed");
    }
    // 8. No output over an input of the run or of the check, whatever the ASCII case.
    let over = |o: &&str| {
        let o = o.to_ascii_lowercase();
        inputs.iter().any(|i| i.to_ascii_lowercase() == o)
            || g.inputs.iter().any(|(i, _)| i.to_ascii_lowercase() == o)
    };
    if outputs.iter().any(over) {
        return Some("output-overwrites-input");
    }
    // 9. Every input is in the key, with the identity it has there.
    let entries = run.get("inputs").array();
    let keyed = |e: &Value| {
        g.inputs
            .iter()
            .find(|(p, _)| Some(p.as_str()) == e.text("path"))
    };
    if entries.iter().any(|e| keyed(e).is_none()) {
        return Some("input-not-in-key");
    }
    if entries
        .iter()
        .any(|e| keyed(e).map(|(_, i)| i.as_str()) != e.text("identity"))
    {
        return Some("identity-mismatch");
    }
    // 10. Every argument is a string without NUL.
    if !all_strings(run.opt("args")) || args.iter().any(|a| a.contains('\0')) {
        return Some("bad-arguments");
    }
    // 11. The run reads every file its obligation names.
    if g.named().iter().any(|n| !inputs.contains(&n.as_str())) {
        return Some("missing-input");
    }
    None
}

/// The key a run is given to the executor under: its check, its number, its description.
pub fn run_key(obligation: &Value, inputs: &Value, number: usize, description: &Value) -> String {
    let check = canonical::identity(&json::object(vec![
        ("obligation", obligation.clone()),
        ("inputs", inputs.clone()),
    ]));
    canonical::identity(&json::object(vec![
        ("check", json::string(&check)),
        ("run", Value::Number(number as i64)),
        (
            "description",
            json::string(&canonical::identity(description)),
        ),
    ]))
}

/// The tools of a list as (name, digest) pairs, sorted, or None if one is not.
fn tool_pairs(v: Option<&Value>) -> Option<Vec<(String, String)>> {
    let mut pairs = match v {
        Some(Value::Array(a)) => a
            .iter()
            .map(|t| Some((t.text("name")?.to_owned(), t.text("digest")?.to_owned())))
            .collect::<Option<Vec<_>>>()?,
        _ => return None,
    };
    pairs.sort();
    Some(pairs)
}

/// The verdict that ends the check when an executor's report is not a run that
/// exited as described; None when the provider is to be given the report.
pub fn report_fault(run: &Value, report: Option<&Value>) -> Option<&'static str> {
    let report = match report {
        Some(r @ Value::Object(_)) => r,
        _ => return Some("error"),
    };
    if report.text("end") == Some("unavailable") {
        return Some("unavailable");
    }
    if report.text("end") != Some("exited") {
        return Some("error");
    }
    if !same(report.opt("platform"), run.opt("platform")) {
        return Some("error");
    }
    if tool_pairs(report.opt("tools_ran")).is_none()
        || tool_pairs(report.opt("tools_ran")) != tool_pairs(run.opt("tools"))
    {
        return Some("error");
    }
    None
}

/// The bytes of a file under `root`, reached without following a symbolic link
/// at any step, if it is a regular file of at most `MAX_ATTACHMENT` bytes.
pub fn attachment(root: &Path, path: &str) -> Option<Vec<u8>> {
    let mut at = root.to_path_buf();
    for segment in path.split('/') {
        at.push(segment);
        if std::fs::symlink_metadata(&at)
            .ok()?
            .file_type()
            .is_symlink()
        {
            return None;
        }
    }
    // No step is a link, so the file's own metadata is the file's.
    let meta = std::fs::metadata(&at).ok()?;
    if !meta.file_type().is_file() || meta.len() > MAX_ATTACHMENT {
        return None;
    }
    let mut bytes = Vec::new();
    std::fs::File::open(&at)
        .ok()?
        .take(MAX_ATTACHMENT + 1)
        .read_to_end(&mut bytes)
        .ok()?;
    (bytes.len() as u64 <= MAX_ATTACHMENT).then_some(bytes)
}

/// The verdict a `final` gives, or why it is refused. `runs` is how many runs exited.
pub fn final_verdict(
    g: &Given,
    runs: usize,
    f: &Value,
    root: &Path,
) -> Result<String, &'static str> {
    let shaped = matches!(f, Value::Object(_))
        && f.opt("attachments")
            .is_none_or(|a| objects_with(Some(a), &["path", "identity"]));
    if !shaped {
        return Err("bad-final");
    }
    let attachments: &[Value] = f.opt("attachments").map_or(&[], Value::array);
    let path_of = |a: &Value| a.text("path").unwrap_or_default().to_owned();
    if !attachments
        .iter()
        .all(|a| passes(&path_of(a)) && attachment(root, &path_of(a)).is_some())
    {
        return Err("bad-path");
    }
    let rehashed = |a: &Value| {
        attachment(root, &path_of(a)).map(|bytes| format!("sha256:{}", canonical::sha256(&bytes)))
    };
    if attachments
        .iter()
        .any(|a| rehashed(a).as_deref() != a.text("identity"))
    {
        return Err("identity-mismatch");
    }
    let verdict = f.text("verdict").unwrap_or_default();
    if !VERDICTS.contains(&verdict) {
        return Err("bad-verdict");
    }
    if verdict == "passed" || verdict == "failed" {
        if runs == 0 {
            return Err("verdict-without-run");
        }
        let rank = |r: Option<&str>| RANKS.iter().position(|x| Some(*x) == r);
        let (class, ceiling) = match &g.ceiling {
            Some((class, rank_name)) => (class.as_str(), rank(Some(rank_name))),
            None => ("", None),
        };
        let strength = f.opt("strength");
        let stated = strength.and_then(|s| rank(s.text("rank")));
        if stated.is_none() || ceiling.is_none() || stated > ceiling {
            return Err("strength-above-ceiling");
        }
        if strength.and_then(|s| s.text("class")) != Some(class) {
            return Err("strength-class-mismatch");
        }
    }
    Ok(verdict.to_owned())
}

/// What the manifest declares: its tools, and the strength of `obligation.check`.
/// None when it does not have the shape the contract gives it.
pub fn manifest(m: &Value) -> Option<(Vec<String>, Ceiling)> {
    let manifest = m.opt("manifest")?;
    if !objects_with(manifest.opt("capabilities"), &["capability"]) {
        return None;
    }
    let names = field_of(manifest.opt("capabilities"), "capability");
    if (1..names.len()).any(|i| names[..i].contains(&names[i])) {
        return None;
    }
    let check = manifest
        .get("capabilities")
        .array()
        .iter()
        .find(|c| c.text("capability") == Some("obligation.check"));
    let ceiling = match check.and_then(|c| c.opt("strength")) {
        None => None,
        Some(s) => {
            let rank = s.text("rank").filter(|r| RANKS.contains(r))?;
            Some((s.text("class")?.to_owned(), rank.to_owned()))
        }
    };
    let tool_name = |n: &str| {
        !n.is_empty()
            && n.chars()
                .all(|c| c.is_ascii_alphanumeric() || "._-".contains(c))
    };
    if !objects_with(manifest.opt("tools"), &["name"])
        || !field_of(manifest.opt("tools"), "name")
            .into_iter()
            .all(tool_name)
    {
        return None;
    }
    let declared = field_of(manifest.opt("tools"), "name");
    Some((declared.into_iter().map(str::to_owned).collect(), ceiling))
}

/// Give one run to the executor command and read its report, strictly. None when
/// the executor fails, prints no object that can be read, or is not done by `wait`.
fn execute(executor: &[String], root: &Path, asked: &Value, wait: Duration) -> Option<Value> {
    let mut tree = Tree::spawn(
        Command::new(&executor[0])
            .args(&executor[1..])
            .current_dir(root)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null()),
    )
    .ok()?;
    let mut stdout = tree.child.stdout.take()?;
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        let mut out = Vec::new();
        let _ = stdout.read_to_end(&mut out);
        let _ = tx.send(out);
    });
    if let Some(mut stdin) = tree.child.stdin.take() {
        let text = json::encode(asked);
        std::thread::spawn(move || {
            let _ = stdin.write_all(text.as_bytes());
        });
    }
    let until = Instant::now() + wait;
    let status = loop {
        if let Ok(Some(status)) = tree.child.try_wait() {
            break status;
        }
        if Instant::now() >= until {
            return None; // stopped waiting: the run timed out
        }
        std::thread::sleep(Duration::from_millis(5));
    };
    tree.end();
    let out = rx.recv_timeout(Duration::from_secs(2)).ok()?;
    if !status.success() {
        return None;
    }
    match wire::strict(std::str::from_utf8(out.trim_ascii()).ok()?) {
        Ok(v @ Value::Object(_)) => Some(v),
        _ => None,
    }
}

enum Outcome {
    Verdict(String),
    Refused(&'static str),
}

struct Asked {
    root: String,
    provider: Vec<String>,
    executor: Vec<String>,
    obligation: Value,
    inputs: Value,
    tools: Value,
    deadline_ms: u64,
}

/// The host's own input, if it has the shape the contract gives it.
fn read_input(v: &Value) -> Option<(Asked, Given)> {
    let command = |k: &str| {
        let list = v.opt(k);
        (all_strings(list) && !strings(list).is_empty()).then(|| {
            strings(list)
                .into_iter()
                .map(str::to_owned)
                .collect::<Vec<_>>()
        })
    };
    let pairs = |k: &str, a: &str, b: &str| {
        objects_with(v.opt(k), &[a, b]).then(|| {
            v.get(k)
                .array()
                .iter()
                .map(|e| (e.get(a).str().to_owned(), e.get(b).str().to_owned()))
                .collect::<Vec<_>>()
        })
    };
    let obligation = v.opt("obligation").filter(|o| is_object(Some(o)))?;
    if !all_strings(obligation.opt("specified_by")) || !all_strings(obligation.opt("targets")) {
        return None;
    }
    let deadline_ms = match v.opt("deadline_ms") {
        Some(Value::Number(n)) if *n > 0 => *n as u64,
        _ => return None,
    };
    let asked = Asked {
        root: v.text("root")?.to_owned(),
        provider: command("provider")?,
        executor: command("executor")?,
        obligation: obligation.clone(),
        inputs: v.get("inputs").clone(),
        tools: v.opt("tools")?.clone(),
        deadline_ms,
    };
    let given = Given {
        obligation: obligation.clone(),
        inputs: pairs("inputs", "path", "identity")?,
        tools: pairs("tools", "name", "digest")?,
        platform: v.opt("platform").filter(|p| is_object(Some(p)))?.clone(),
        declared: vec![],
        ceiling: None,
    };
    Some((asked, given))
}

fn request(id: usize, deadline_ms: u64, body: Value) -> Value {
    json::object(vec![
        ("type", json::string("request")),
        ("id", json::string(&id.to_string())),
        ("deadline_ms", Value::Number(deadline_ms as i64)),
        ("capability", json::string("obligation.check")),
        ("body", body),
    ])
}

fn drive(
    peer: &mut Peer,
    asked: &Asked,
    g: &mut Given,
    runs: &mut usize,
) -> Result<Outcome, &'static str> {
    let wait = Duration::from_millis(asked.deadline_ms);
    peer.send(&hello(MAX_LINE, asked.deadline_ms), Instant::now() + wait)?;
    let m = peer.read(Instant::now() + wait)?;
    if !crate::session::manifest_ok(&m) {
        return Err("bad-manifest");
    }
    let (declared, ceiling) = manifest(&m).ok_or("bad-manifest")?;
    g.declared = declared;
    g.ceiling = ceiling;
    let start = json::object(vec![
        ("op", json::string("start")),
        ("obligation", g.obligation.clone()),
        ("inputs", asked.inputs.clone()),
        ("tools", asked.tools.clone()),
        ("platform", g.platform.clone()),
    ]);
    let mut id = 1;
    peer.send(
        &request(id, asked.deadline_ms, start),
        Instant::now() + wait,
    )?;
    loop {
        let answer = peer.read(Instant::now() + wait)?;
        if let Some(fault) = answer_fault(&answer, &id.to_string(), "obligation.check") {
            return Err(fault);
        }
        let body = answer.opt("body");
        if !is_object(body) {
            return Err("unexpected");
        }
        let next = body.and_then(|b| b.opt("next"));
        let fin = body.and_then(|b| b.opt("final"));
        let run = match (next, fin) {
            (Some(run), None) => run,
            (None, Some(f)) => {
                return final_verdict(g, *runs, f, Path::new(&asked.root)).map(Outcome::Verdict)
            }
            _ => return Err("neither-or-both"),
        };
        if let Some(fault) = run_fault(g, *runs, run) {
            return Err(fault);
        }
        *runs += 1;
        let given = json::object(vec![
            ("number", Value::Number(*runs as i64)),
            (
                "run_key",
                json::string(&run_key(&asked.obligation, &asked.inputs, *runs, run)),
            ),
            ("run", run.clone()),
        ]);
        let wall = match run.opt("limits").and_then(|l| l.opt("wall_ms")) {
            Some(Value::Number(n)) if *n > 0 => (*n as u64).min(MAX_WALL_MS),
            _ => 0,
        };
        let report = execute(
            &asked.executor,
            Path::new(&asked.root),
            &given,
            wait + Duration::from_millis(wall),
        );
        if let Some(verdict) = report_fault(run, report.as_ref()) {
            return Ok(Outcome::Verdict(verdict.to_owned()));
        }
        id += 1;
        let result = json::object(vec![
            ("op", json::string("run.result")),
            ("check", json::string("1")),
            ("run", Value::Number(*runs as i64)),
            ("report", report.unwrap_or(Value::Null)),
        ]);
        peer.send(
            &request(id, asked.deadline_ms, result),
            Instant::now() + wait,
        )?;
    }
}

pub fn check(v: &Value) -> Result<Value, String> {
    let mut runs = 0;
    let outcome = match read_input(v) {
        None => Outcome::Refused("bad-input"),
        Some((asked, mut g)) => {
            if g.named()
                .iter()
                .any(|n| !g.inputs.iter().any(|(p, _)| p == n))
            {
                Outcome::Refused("unknown-file")
            } else {
                host(&asked, &mut g, &mut runs)
            }
        }
    };
    let runs = ("runs", Value::Number(runs as i64));
    Ok(match outcome {
        Outcome::Verdict(v) => json::object(vec![
            ("outcome", json::string("verdict")),
            ("verdict", json::string(&v)),
            runs,
        ]),
        Outcome::Refused(r) => json::object(vec![
            ("outcome", json::string("refused")),
            ("reason", json::string(r)),
            runs,
        ]),
    })
}

/// Start the provider, take the check through it, and end every process it started.
fn host(asked: &Asked, g: &mut Given, runs: &mut usize) -> Outcome {
    let tree = Tree::spawn(
        Command::new(&asked.provider[0])
            .args(&asked.provider[1..])
            .current_dir(&asked.root)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped()),
    );
    let mut tree = match tree {
        Ok(t) => t,
        Err(_) => return Outcome::Refused("closed"),
    };
    let log = Log::drain(tree.child.stderr.take().expect("piped"), 65536);
    let mut peer = Peer::new(tree, MAX_LINE, true);
    let outcome = drive(&mut peer, asked, g, runs).unwrap_or_else(Outcome::Refused);
    let _ = peer.shutdown(Instant::now() + Duration::from_secs(1));
    peer.end();
    log.settle();
    outcome
}

#[cfg(test)]
mod tests {
    use super::*;
    fn v(s: &str) -> Value {
        json::parse(s.as_bytes()).unwrap()
    }
    const A: &str = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    const C: &str = "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";
    fn given() -> Given {
        Given {
            obligation: v(r#"{"specified_by":["a.txt"],"targets":["a.txt"]}"#),
            inputs: vec![("a.txt".into(), A.into())],
            tools: vec![("checker".into(), C.into())],
            platform: v(r#"{"os":"linux","arch":"aarch64"}"#),
            declared: vec!["checker".into(), "shell".into()],
            ceiling: Some(("test".into(), "bounded".into())),
        }
    }
    fn good() -> Value {
        v(&format!(
            r#"{{"program":{{"tool":"checker","path":"bin/checker"}},"args":["--lib","${{tool:checker}}/lib/rules.jar","a.txt"],
               "inputs":[{{"path":"a.txt","identity":"{A}"}}],"outputs":[],"limits":{{"wall_ms":1,"output_bytes":1}},
               "platform":{{"arch":"aarch64","os":"linux"}},"tools":[{{"name":"checker","digest":"{C}"}}],"cwd":"work"}}"#
        ))
    }
    fn with(field: &str, value: &str) -> Value {
        let mut run = good();
        match run.opt_mut(field) {
            Some(slot) => *slot = v(value),
            None => {
                if let Value::Object(o) = &mut run {
                    o.push((field.into(), v(value)));
                }
            }
        }
        run
    }
    #[test]
    fn a_run_that_keeps_every_rule() {
        assert_eq!(run_fault(&given(), 0, &good()), None);
        assert_eq!(run_fault(&given(), 7, &good()), None);
    }
    #[test]
    fn each_rule_in_order() {
        let g = given();
        let fault = |run: &Value| run_fault(&g, 0, run);
        assert_eq!(run_fault(&g, 8, &good()), Some("too-many-runs"));
        assert_eq!(run_fault(&g, 8, &v("null")), Some("too-many-runs"));
        for (field, value) in [
            ("program", r#"{"tool":"checker"}"#),
            ("program", r#""bin/x""#),
            ("args", r#""a.txt""#),
            ("args", "null"),
            ("inputs", r#"{"path":"a.txt"}"#),
            ("inputs", r#"[{"path":"a.txt"}]"#),
            ("outputs", r#"[{"optional":true}]"#),
            ("outputs", r#"{"path":"x"}"#),
            ("tools", r#"[{"name":"checker"}]"#),
            ("platform", r#""linux""#),
            ("cwd", "1"),
            ("limits", r#"{"wall_ms":"1"}"#),
            ("limits", "[]"),
        ] {
            assert_eq!(
                fault(&with(field, value)),
                Some("bad-description"),
                "{field}"
            );
        }
        let mut no_tools = good();
        if let Value::Object(o) = &mut no_tools {
            o.retain(|(k, _)| k != "tools");
        }
        assert_eq!(fault(&no_tools), Some("bad-description"));
        assert_eq!(fault(&v("null")), Some("bad-description"));
        assert_eq!(fault(&with("env", "null")), Some("env-not-allowed"));
        assert_eq!(
            fault(&with("platform", r#"{"os":"windows","arch":"x86_64"}"#)),
            Some("platform-mismatch")
        );
        assert_eq!(
            fault(&with("program", r#"{"tool":"other","path":"bin/x"}"#)),
            Some("undeclared-tool")
        );
        assert_eq!(
            fault(&with("args", r#"["${tool:other}"]"#)),
            Some("undeclared-tool")
        );
        assert_eq!(
            fault(&with("program", r#"{"tool":"shell","path":"bin/sh"}"#)),
            Some("tool-not-in-key")
        );
        assert_eq!(
            fault(&with(
                "tools",
                &format!(r#"[{{"name":"shell","digest":"{C}"}}]"#)
            )),
            Some("tool-not-in-key")
        );
        assert_eq!(
            fault(&with(
                "tools",
                &format!(r#"[{{"name":"checker","digest":"{A}"}}]"#)
            )),
            Some("tool-digest-mismatch")
        );
        assert_eq!(
            fault(&with("program", r#"{"tool":"checker","path":"../sh"}"#)),
            Some("bad-path")
        );
        assert_eq!(fault(&with("cwd", r#""..""#)), Some("bad-path"));
        assert_eq!(
            fault(&with("outputs", r#"[{"path":"/tmp/x"}]"#)),
            Some("bad-path")
        );
        assert_eq!(
            fault(&with("args", r#"["${tool:checker}/../x"]"#)),
            Some("bad-path")
        );
        for arg in [
            "-I..",
            "-c=/etc",
            "@f",
            "~/x",
            "%x",
            "file:///x",
            "\\x",
            "-c=\u{ff0f}x",
            "${tool:checker}/x=/y",
        ] {
            let args = json::encode(&Value::Array(vec![json::string(arg)]));
            assert_eq!(fault(&with("args", &args)), Some("bad-path"), "{arg}");
        }
        assert_eq!(fault(&with("env", r#"{"A":"b"}"#)), Some("env-not-allowed"));
        assert_eq!(fault(&with("env", "{}")), Some("env-not-allowed"));
        assert_eq!(fault(&with("env", "[]")), Some("env-not-allowed"));
        assert_eq!(
            fault(&with("outputs", r#"[{"path":"A.TXT"}]"#)),
            Some("output-overwrites-input")
        );
        let mut other = given();
        other.inputs.push(("b.txt".into(), A.into()));
        assert_eq!(
            run_fault(&other, 0, &with("outputs", r#"[{"path":"b.txt"}]"#)),
            Some("output-overwrites-input")
        );
        // NUL is rule 10's, even inside what looks like a tool's file.
        assert_eq!(
            fault(&with("args", r#"["-I${tool:checker}/x\u0000"]"#)),
            Some("bad-arguments")
        );
        assert_eq!(
            fault(&with("outputs", r#"[{"path":"a.txt"}]"#)),
            Some("output-overwrites-input")
        );
        assert_eq!(
            fault(&with(
                "inputs",
                &format!(r#"[{{"path":"b.txt","identity":"{A}"}}]"#)
            )),
            Some("input-not-in-key")
        );
        assert_eq!(
            fault(&with(
                "inputs",
                &format!(r#"[{{"path":"a.txt","identity":"{C}"}}]"#)
            )),
            Some("identity-mismatch")
        );
        assert_eq!(
            fault(&with("args", r#"["a.txt\u0000x"]"#)),
            Some("bad-arguments")
        );
        assert_eq!(fault(&with("args", "[1]")), Some("bad-arguments"));
        assert_eq!(fault(&with("args", "[]")), None);
        let mut nothing = with("inputs", "[]");
        *nothing.opt_mut("args").unwrap() = v("[]");
        assert_eq!(fault(&nothing), Some("missing-input"));
        // Two rules broken: the first in order is the reason.
        let mut both = with("platform", r#"{"os":"windows","arch":"x86_64"}"#);
        *both.opt_mut("program").unwrap() = v(r#"{"tool":"other","path":"bin/x"}"#);
        assert_eq!(fault(&both), Some("platform-mismatch"));
    }
    #[test]
    fn tool_references() {
        assert_eq!(
            tool_refs("${tool:a}/x:${tool:b}/y"),
            [("a", "/x:${tool:b}/y"), ("b", "/y")]
        );
        assert_eq!(tool_refs("${tool:a"), []);
        assert!(whole_tool_file("${tool:a}/lib/x.jar"));
        assert!(!whole_tool_file("${tool:a}"));
        assert!(!whole_tool_file("-x${tool:a}/y"));
        assert!(tool_file_passes("lib/x-1_2.jar"));
        assert!(!tool_file_passes("y=/z"));
        assert!(!tool_file_passes("lib/x\u{e9}.jar"));
        assert!(!tool_file_passes("../x"));
    }
    #[test]
    fn the_run_key_has_the_number() {
        let (o, i, d) = (v("{}"), v("[]"), v(r#"{"x":1}"#));
        assert_ne!(run_key(&o, &i, 1, &d), run_key(&o, &i, 2, &d));
        assert_ne!(run_key(&o, &i, 1, &d), run_key(&o, &i, 1, &v("{}")));
        let check = canonical::identity(&v(r#"{"inputs":[],"obligation":{}}"#));
        let want = canonical::identity(&json::object(vec![
            ("check", json::string(&check)),
            ("run", Value::Number(3)),
            ("description", json::string(&canonical::identity(&d))),
        ]));
        assert_eq!(run_key(&o, &i, 3, &d), want);
    }
    #[test]
    fn reports() {
        let run = good();
        let report = |end: &str, platform: &str, tools: &str| {
            v(&format!(
                r#"{{"end":"{end}","platform":{platform},"tools_ran":{tools}}}"#
            ))
        };
        let p = r#"{"os":"linux","arch":"aarch64"}"#;
        let t = format!(r#"[{{"name":"checker","digest":"{C}"}}]"#);
        assert_eq!(report_fault(&run, Some(&report("exited", p, &t))), None);
        assert_eq!(report_fault(&run, None), Some("error"));
        assert_eq!(
            report_fault(&run, Some(&report("unavailable", p, &t))),
            Some("unavailable")
        );
        assert_eq!(
            report_fault(&run, Some(&report("timed-out", p, &t))),
            Some("error")
        );
        let other = r#"{"os":"macos","arch":"x86_64"}"#;
        assert_eq!(
            report_fault(&run, Some(&report("exited", other, &t))),
            Some("error")
        );
        assert_eq!(
            report_fault(&run, Some(&report("exited", p, "[]"))),
            Some("error")
        );
        let digest = format!(r#"[{{"name":"checker","digest":"{A}"}}]"#);
        assert_eq!(
            report_fault(&run, Some(&report("exited", p, &digest))),
            Some("error")
        );
    }
    #[test]
    fn finals() {
        let g = given();
        let root = std::env::temp_dir();
        let f = |s: &str, runs: usize| final_verdict(&g, runs, &v(s), &root);
        let s = r#""strength":{"class":"test","rank":"bounded"}"#;
        assert_eq!(
            f(&format!(r#"{{"verdict":"passed",{s}}}"#), 1).as_deref(),
            Ok("passed")
        );
        assert_eq!(
            f(&format!(r#"{{"verdict":"failed",{s}}}"#), 1).as_deref(),
            Ok("failed")
        );
        assert_eq!(
            f(r#"{"verdict":"unsupported"}"#, 0).as_deref(),
            Ok("unsupported")
        );
        assert_eq!(f(r#"{"verdict":"error"}"#, 1).as_deref(), Ok("error"));
        assert_eq!(
            f(&format!(r#"{{"verdict":"passed",{s}}}"#), 0),
            Err("verdict-without-run")
        );
        assert_eq!(f(r#"{"verdict":"maybe"}"#, 1), Err("bad-verdict"));
        assert_eq!(
            f(r#"{"verdict":"passed"}"#, 1),
            Err("strength-above-ceiling")
        );
        let exhaustive = r#"{"verdict":"passed","strength":{"class":"test","rank":"exhaustive"}}"#;
        assert_eq!(f(exhaustive, 1), Err("strength-above-ceiling"));
        let sampled = r#"{"verdict":"passed","strength":{"class":"test","rank":"sampled"}}"#;
        assert_eq!(f(sampled, 1).as_deref(), Ok("passed"));
        let proof = r#"{"verdict":"passed","strength":{"class":"proof","rank":"bounded"}}"#;
        assert_eq!(f(proof, 1), Err("strength-class-mismatch"));
        let outside = format!(
            r#"{{"verdict":"passed",{s},"attachments":[{{"path":"../x","identity":"{A}"}}]}}"#
        );
        assert_eq!(f(&outside, 1), Err("bad-path"));
        assert_eq!(
            f(
                r#"{"verdict":"maybe","attachments":[{"path":"/x","identity":"x"}]}"#,
                1
            ),
            Err("bad-path")
        );
        assert_eq!(f(r#""passed""#, 1), Err("bad-final"));
        assert_eq!(
            f(r#"{"verdict":"maybe","attachments":{}}"#, 1),
            Err("bad-final")
        );
        assert_eq!(
            f(r#"{"verdict":"maybe","attachments":[{"path":"x"}]}"#, 1),
            Err("bad-final")
        );
        assert_eq!(
            f(r#"{"verdict":"maybe","attachments":["x"]}"#, 1),
            Err("bad-final")
        );
        let no_class = r#"{"verdict":"passed","strength":{"rank":"bounded"}}"#;
        assert_eq!(f(no_class, 1), Err("strength-class-mismatch"));
        let name = format!("dodona-kernel-test-{}.txt", std::process::id());
        std::fs::write(root.join(&name), b"kept\n").unwrap();
        let id = format!("sha256:{}", canonical::sha256(b"kept\n"));
        let att = |id: &str| {
            format!(
                r#"{{"verdict":"passed",{s},"attachments":[{{"path":"{name}","identity":"{id}"}}]}}"#
            )
        };
        assert_eq!(f(&att(&id), 1).as_deref(), Ok("passed"));
        assert_eq!(f(&att(A), 1), Err("identity-mismatch"));
        std::fs::remove_file(root.join(&name)).unwrap();
        // A file that is not there is not a regular file.
        assert_eq!(f(&att(&id), 1), Err("bad-path"));
        let dir = format!("dodona-kernel-test-dir-{}", std::process::id());
        std::fs::create_dir(root.join(&dir)).unwrap();
        let in_dir =
            format!(r#"{{"verdict":"error","attachments":[{{"path":"{dir}","identity":"{A}"}}]}}"#);
        assert_eq!(f(&in_dir, 1), Err("bad-path"));
        std::fs::remove_dir(root.join(&dir)).unwrap();
        let none = Given {
            ceiling: None,
            ..given()
        };
        let passed = v(&format!(r#"{{"verdict":"passed",{s}}}"#));
        assert_eq!(
            final_verdict(&none, 1, &passed, &root),
            Err("strength-above-ceiling")
        );
    }
    #[test]
    fn manifests() {
        let m = v(
            r#"{"manifest":{"capabilities":[{"capability":"obligation.check",
                     "strength":{"class":"test","rank":"bounded"}}],"tools":[{"name":"checker"}]}}"#,
        );
        let (declared, ceiling) = manifest(&m).unwrap();
        assert_eq!(declared, ["checker"]);
        assert_eq!(ceiling, Some(("test".into(), "bounded".into())));
        assert!(manifest(&v(r#"{"manifest":{}}"#)).is_none());
        assert!(manifest(&v(r#"{"manifest":{"capabilities":{}}}"#)).is_none());
        let bad = |caps: &str, tools: &str| {
            let text = format!(r#"{{"manifest":{{"capabilities":{caps},"tools":{tools}}}}}"#);
            manifest(&v(&text)).is_none()
        };
        let check = r#"{"capability":"obligation.check"}"#;
        assert!(!bad(&format!("[{check}]"), r#"[{"name":"a.b_c-1"}]"#));
        assert!(bad(&format!("[{check},{check}]"), "[]"));
        assert!(bad(&format!(r#"[{check},"obligation.check"]"#), "[]"));
        assert!(bad(r#"[{"capability":1}]"#, "[]"));
        let strength = |s: &str| format!(r#"[{{"capability":"obligation.check","strength":{s}}}]"#);
        assert!(bad(&strength(r#"{"class":"test","rank":"certain"}"#), "[]"));
        assert!(bad(&strength(r#"{"rank":"bounded"}"#), "[]"));
        assert!(bad(&strength(r#""bounded""#), "[]"));
        assert!(bad(&format!("[{check}]"), r#"["checker"]"#));
        assert!(bad(&format!("[{check}]"), r#"[{"name":"a/b"}]"#));
        assert!(bad(&format!("[{check}]"), r#"[{"name":""}]"#));
        assert!(bad(&format!("[{check}]"), "{}"));
        assert!(bad(&format!("[{check}]"), "null"));
    }
    #[test]
    fn input_of_the_wrong_shape_is_not_handled() {
        let reason = |s: &str| check(&v(s)).unwrap().text("reason").map(str::to_owned);
        assert_eq!(reason("{}").as_deref(), Some("bad-input"));
        assert_eq!(reason("[]").as_deref(), Some("bad-input"));
        let ok = r#"{"root":".","provider":["p"],"executor":["e"],"obligation":{"specified_by":["a"],"targets":["b"]},
                    "inputs":[{"path":"a","identity":"x"}],"tools":[],"platform":{},"deadline_ms":1}"#;
        // A file the obligation names is not among the inputs: refused before anything starts.
        assert_eq!(check(&v(ok)).unwrap().text("reason"), Some("unknown-file"));
        for (from, to) in [
            (r#""deadline_ms":1"#, r#""deadline_ms":0"#),
            (r#""deadline_ms":1"#, r#""deadline_ms":"1""#),
            (r#"["p"]"#, "[]"),
            (r#"["p"]"#, "[1]"),
            (r#""root":".""#, r#""root":1"#),
            (r#""targets":["b"]"#, r#""targets":"b""#),
            (r#""specified_by":["a"],"#, ""),
            (r#""identity":"x""#, r#""identity":1"#),
            (r#""tools":[]"#, r#""tools":[{"name":"t"}]"#),
            (r#""tools":[]"#, r#""tools":{}"#),
            (r#""platform":{}"#, r#""platform":"linux""#),
        ] {
            assert_eq!(
                reason(&ok.replace(from, to)).as_deref(),
                Some("bad-input"),
                "{to}"
            );
        }
    }
}
