//! The status of a whole project (conformance/README.md, "How a project's
//! status is judged"; decision 0034).
//!
//!     dodona-kernel status < INPUT.json
//!
//! The command reads the project file, asks the providers the site names for
//! the obligations and the intents, reads the ledgers and the policy it is
//! given, and builds the status scenario J it judges. Its report is the last
//! result `status::run` gives for J: the same code as the `scenario` command,
//! so the report cannot say anything J does not. It runs nothing.
//!
//! The steps are numbered as in the contract. The first rule broken gives the
//! reason, and nothing after it is done: no provider is started before the
//! project file and every claimed file have been read. Every answer, a refusal
//! included, is one JSON object and the exit status is 0.
use crate::canonical;
use crate::host;
use crate::json::{self, key_order, Value};
use crate::ledger;
use crate::proc::{self, Tree};
use crate::session::{hello, manifest_ok};
use crate::status;
use crate::wire::{self, Log, Peer};
use std::cmp::Ordering;
use std::fs;
use std::io::ErrorKind;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

/// What this command serves.
const SERVED: [&str; 2] = ["obligation.enumerate", "intent.index"];
/// The separation levels a floor may name.
const LEVELS: [&str; 6] = [
    "self",
    "helper",
    "apart",
    "tested",
    "cross-make",
    "credentialed",
];
/// The kinds of act a floor may be given for.
const FLOOR_KINDS: [&str; 5] = [
    "confirm-baseline",
    "match-check",
    "grant-amendment",
    "close-deferred",
    "change-policy",
];
/// The longest deadline the input may give: a day.
const MAX_DEADLINE_MS: i64 = 86_400_000;
/// How much of a provider's standard error is kept.
const MAX_LOG: usize = 65536;

/// Why the project gets no report: the reason the contract names, and words for a person.
struct Stop {
    reason: &'static str,
    detail: String,
}
type Step<T> = Result<T, Stop>;
fn stop<T>(reason: &'static str, detail: impl Into<String>) -> Step<T> {
    Err(Stop {
        reason,
        detail: detail.into(),
    })
}

/// The answer to one input: a report, or a refusal. Never anything else.
pub fn answer(input: &[u8]) -> Value {
    match run(input) {
        Ok(v) => v,
        Err(s) => json::object(vec![
            ("refused", json::string(s.reason)),
            ("detail", json::string(&s.detail)),
        ]),
    }
}

/// The answer of the run command (conformance/README.md, "How a project's run
/// is judged"): the status command's report after the project's unrecorded
/// checks were run and their verdicts recorded, with `counts`; or a refusal,
/// in the status command's form. Never anything else.
pub fn run_answer(input: &[u8]) -> Value {
    match run_input::run_native(input) {
        Ok(v) => v,
        Err(s) => json::object(vec![
            ("refused", json::string(s.reason)),
            ("detail", json::string(&s.detail)),
        ]),
    }
}

// Small readers of JSON that never panic.

/// A list of strings, or None.
fn strings(v: Option<&Value>) -> Option<Vec<String>> {
    match v {
        Some(Value::Array(a)) => a
            .iter()
            .map(|x| match x {
                Value::String(s) => Some(s.clone()),
                _ => None,
            })
            .collect(),
        _ => None,
    }
}
fn is_object(v: Option<&Value>) -> bool {
    matches!(v, Some(Value::Object(_)))
}
fn list(v: Option<&Value>) -> Option<&[Value]> {
    match v {
        Some(Value::Array(a)) => Some(a),
        _ => None,
    }
}
/// A string that is there and not empty.
fn named(v: &Value, field: &str) -> bool {
    v.text(field).is_some_and(|s| !s.is_empty())
}
fn order(a: &str, b: &str) -> Ordering {
    key_order(a, b)
}
/// Sorted as the canonical encoding sorts keys, each member once.
fn sort_set(mut items: Vec<String>) -> Vec<String> {
    items.sort_by(|a, b| order(a, b));
    items.dedup();
    items
}
/// Whether a list is already sorted as the canonical encoding sorts keys, each member once.
fn sorted_once(items: &[String]) -> bool {
    items
        .windows(2)
        .all(|w| order(&w[0], &w[1]) == Ordering::Less)
}
fn texts(items: &[String]) -> Value {
    Value::Array(items.iter().map(|s| json::string(s)).collect())
}
/// An object with its members in the order the canonical encoding writes them.
fn sorted_object(mut members: Vec<(String, Value)>) -> Value {
    members.sort_by(|a, b| order(&a.0, &b.0));
    Value::Object(members)
}

/// Relative: not empty, not starting with `/`, no `\`, no `:` and no NUL, and no
/// segment that is empty, `.` or `..`.
fn relative(p: &str) -> bool {
    !p.is_empty()
        && !p.starts_with('/')
        && !p.contains('\\')
        && !p.contains(':')
        && !p.contains('\0')
        && p.split('/').all(|s| !matches!(s, "" | "." | ".."))
}

/// Whether some step of `rel` under `root` is a link (a junction counts as one).
/// A step that cannot be looked at is left to whatever reads the path.
fn link_on_the_way(root: &Path, rel: &str) -> bool {
    let mut here = root.to_path_buf();
    rel.split('/').any(|part| {
        here.push(part);
        fs::symlink_metadata(&here).is_ok_and(|m| m.file_type().is_symlink())
    })
}

/// A regular file under `root`, reached without a link at any step.
fn plain_file(root: &Path, rel: &str) -> bool {
    !link_on_the_way(root, rel)
        && fs::symlink_metadata(root.join(rel)).is_ok_and(|m| m.file_type().is_file())
}

fn file_identity(bytes: &[u8]) -> String {
    format!("sha256:{}", canonical::sha256(bytes))
}

// Step 1. The input.

struct Provider {
    command: Vec<String>,
    /// CODE: a digest of the provider's own files, keyed by their paths.
    code: String,
}
struct Input {
    root: PathBuf,
    project: String,
    policy_source: String,
    ledgers: Vec<String>,
    owner_ledger: String,
    platform: String,
    /// The site's platform object exactly as given: a check is started on it.
    /// Read by the run command only, which is not served yet.
    #[allow(dead_code)]
    platform_given: Value,
    writer: String,
    runner: String,
    /// The site's tools as `{"name", "digest"}`, the form a key holds.
    tools: Value,
    /// The site's tools as `{"name", "version", "digest"}`, the form a check is
    /// started with. Read by the run command only.
    #[allow(dead_code)]
    tools_given: Value,
    providers: Vec<(String, Provider)>,
    deadline_ms: u64,
    /// Where every session notes what it sends a provider and reads from one:
    /// set by the run command when it keeps a transcript, never by `status`.
    recorder: Option<Recorder>,
    required: Vec<String>,
    min_hard_gates: i64,
    floors: Value,
    not_applied: Vec<String>,
}
impl Input {
    fn provider(&self, name: &str) -> Option<&Provider> {
        self.providers
            .iter()
            .find(|(n, _)| n == name)
            .map(|(_, p)| p)
    }
}

/// One JSON object alone on standard input, read as a check reads a message.
fn framed(input: &[u8]) -> Option<Value> {
    let body = input.strip_suffix(b"\n").unwrap_or(input);
    if !(body.starts_with(b"{") && body.ends_with(b"}")) {
        return None;
    }
    let v = wire::strict(std::str::from_utf8(body).ok()?).ok()?;
    matches!(v, Value::Object(_)).then_some(v)
}

/// The policy as the site hands it over, or why it cannot be read.
fn policy_problem(p: &Value) -> Option<&'static str> {
    let fields = match p {
        Value::Object(o) => o,
        _ => return Some("the policy is not an object"),
    };
    let expected = ["required", "min_hard_gates", "floors", "not_applied"];
    if fields.len() != expected.len() || !expected.iter().all(|k| p.opt(k).is_some()) {
        return Some(
            "the policy must hold exactly required, min_hard_gates, floors and not_applied",
        );
    }
    if strings(p.opt("required")).is_none() {
        return Some("policy.required is not a list of strings");
    }
    if !matches!(p.opt("min_hard_gates"), Some(Value::Number(n)) if *n >= 0) {
        return Some("policy.min_hard_gates is not a whole number of at least 0");
    }
    let floors_ok = match p.opt("floors") {
        Some(Value::Object(f)) => f.iter().all(|(k, v)| {
            FLOOR_KINDS.contains(&k.as_str())
                && matches!(v, Value::String(l) if LEVELS.contains(&l.as_str()))
        }),
        _ => false,
    };
    if !floors_ok {
        return Some("policy.floors does not map kinds of act to levels on the scale");
    }
    match strings(p.opt("not_applied")) {
        Some(n) if sorted_once(&n) => None,
        _ => Some("policy.not_applied is not a sorted list of strings, each once"),
    }
}

fn read_input(input: &[u8]) -> Step<Input> {
    let bad = |why: &str| stop("bad-input", why);
    let v = match framed(input) {
        Some(v) => v,
        None => return bad("the input is not one JSON object alone, read strictly"),
    };
    let text = |k: &str| v.text(k).map(str::to_owned);
    let site = v.opt("site").filter(|s| is_object(Some(s)));
    let (root, project, policy_source, owner_ledger, ledgers, site) = match (
        text("root"),
        text("project"),
        text("policy_source"),
        text("owner_ledger"),
        strings(v.opt("ledgers")),
        site,
    ) {
        (Some(r), Some(p), Some(s), Some(o), Some(l), Some(site)) => (r, p, s, o, l, site),
        _ => return bad("the input does not have the shape the contract gives"),
    };
    if !relative(&project) || !relative(&owner_ledger) || !ledgers.iter().all(|l| relative(l)) {
        return bad("project, owner_ledger and every ledger must be relative paths");
    }
    let platform = site.opt("platform").filter(|p| is_object(Some(p)));
    let (os, arch) = match platform.map(|p| (p.text("os"), p.text("arch"))) {
        Some((Some(os), Some(arch))) => (os, arch),
        _ => return bad("site.platform needs a string os and arch"),
    };
    let (writer, runner) = match (site.text("writer"), site.text("runner")) {
        (Some(w), Some(r)) => (w.to_owned(), r.to_owned()),
        _ => return bad("site.writer and site.runner must be strings"),
    };
    let tools = match list(site.opt("tools")) {
        Some(t)
            if t.iter().all(|t| {
                is_object(Some(t))
                    && ["name", "version", "digest"]
                        .iter()
                        .all(|k| t.text(k).is_some())
            }) =>
        {
            t
        }
        _ => {
            return bad(
                "site.tools must be a list of objects with a string name, version and digest",
            )
        }
    };
    let field = |t: &Value, fields: &[&str]| {
        json::object(fields.iter().map(|k| (*k, t.get(k).clone())).collect())
    };
    let tools_given = Value::Array(
        tools
            .iter()
            .map(|t| field(t, &["name", "version", "digest"]))
            .collect(),
    );
    let tools = Value::Array(tools.iter().map(|t| field(t, &["name", "digest"])).collect());
    // The whole object, as the site gives it: a platform may say more than its
    // os and arch (protocol/common.schema.json: `libc`, `emulated_on`).
    let platform_given = platform.cloned().unwrap_or(Value::Null);
    let mut providers = Vec::new();
    match site.opt("providers") {
        Some(Value::Object(ps)) => {
            for (name, p) in ps {
                // No argument a program is given can hold a NUL.
                let command = strings(p.opt("command"))
                    .filter(|c| !c.is_empty() && !c.iter().any(|a| a.contains('\0')));
                match (is_object(Some(p)), command, strings(p.opt("code"))) {
                    (true, Some(command), Some(code)) => providers.push((name.clone(), command, code)),
                    _ => return stop("bad-input", format!("provider {name}: needs a non-empty list of strings command and a list of strings code")),
                }
            }
        }
        _ => return bad("site.providers is not an object"),
    }
    let deadline_ms = match site.opt("deadline_ms") {
        Some(Value::Number(n)) if (1..=MAX_DEADLINE_MS).contains(n) => *n as u64,
        _ => return bad("site.deadline_ms is not a whole number from 1 to 86,400,000"),
    };
    let policy = v.opt("policy").unwrap_or(&Value::Null);
    if let Some(why) = policy_problem(policy) {
        return bad(why);
    }
    let root = PathBuf::from(root);
    if !fs::metadata(&root).is_ok_and(|m| m.is_dir()) {
        return bad("root is not a directory");
    }
    for (name, _, code) in &providers {
        if sort_set(code.clone()).len() != code.len() {
            return stop(
                "bad-input",
                format!("provider {name}: a code path listed twice"),
            );
        }
        if let Some(rel) = code
            .iter()
            .find(|rel| !relative(rel) || !plain_file(&root, rel))
        {
            return stop("bad-input", format!(
                "provider {name}: code path {rel:?} is not a regular file under root reached without a link"
            ));
        }
    }
    // Then every provider's code is read, before any provider is started.
    let mut read = Vec::new();
    for (name, command, code) in providers {
        let mut files = Vec::new();
        for rel in &code {
            match fs::read(root.join(rel)) {
                Ok(bytes) => files.push((rel.clone(), json::string(&canonical::sha256(&bytes)))),
                Err(e) => return stop("unreadable-file", format!("provider {name}: {rel}: {e}")),
            }
        }
        let digest = canonical::identity(&sorted_object(files));
        let code = digest["sha256:".len()..][..16].to_owned();
        read.push((name, Provider { command, code }));
    }
    Ok(Input {
        root,
        project,
        policy_source,
        ledgers,
        owner_ledger,
        platform: format!("{os}/{arch}"),
        platform_given,
        writer,
        runner,
        tools,
        tools_given,
        providers: read,
        deadline_ms,
        recorder: None,
        required: strings(policy.opt("required")).unwrap_or_default(),
        min_hard_gates: policy.get("min_hard_gates").number(),
        floors: policy.get("floors").clone(),
        not_applied: strings(policy.opt("not_applied")).unwrap_or_default(),
    })
}

// Step 2. The project file, in the subset of TOML a kernel reads.

enum Toml {
    Text(String),
    List(Vec<String>),
}
/// One table of the project file: its keys in the order given.
type Table = Vec<(String, Toml)>;

struct Binding {
    name: String,
    provider: String,
    capabilities: Vec<String>,
    patterns: Vec<String>,
}
impl Binding {
    fn serves(&self, capability: &str) -> bool {
        self.capabilities.iter().any(|c| c == capability)
    }
}

/// A string in double quotes holding no `"` or `\`, at the start of `s`, and what follows it.
fn quoted(s: &str) -> Option<(String, &str)> {
    let rest = s.strip_prefix('"')?;
    let end = rest.find('"')?;
    let inside = &rest[..end];
    (!inside.contains('\\')).then(|| (inside.to_owned(), &rest[end + 1..]))
}

/// A value: a string, or a list on the same line of strings, with any spaces
/// after `[`, before `]` and around each comma; then nothing, spaces, or one
/// or more spaces and a comment.
fn toml_value(s: &str) -> Option<Toml> {
    let (value, rest) = if s.starts_with('"') {
        let (text, rest) = quoted(s)?;
        (Toml::Text(text), rest)
    } else {
        let mut rest = s.strip_prefix('[')?.trim_start_matches(' ');
        let mut items = Vec::new();
        if let Some(after) = rest.strip_prefix(']') {
            rest = after;
        } else {
            loop {
                let (item, after) = quoted(rest)?;
                items.push(item);
                rest = after.trim_start_matches(' ');
                if let Some(after) = rest.strip_prefix(',') {
                    rest = after.trim_start_matches(' ');
                } else {
                    rest = rest.strip_prefix(']')?;
                    break;
                }
            }
        }
        (Toml::List(items), rest)
    };
    let tail = rest.trim_start_matches(' ');
    let ends_well = tail.is_empty() || (tail.starts_with('#') && rest.starts_with(' '));
    ends_well.then_some(value)
}

/// A character no line of the project file may hold.
fn forbidden(c: char) -> bool {
    c <= '\u{1f}' || ('\u{7f}'..='\u{9f}').contains(&c)
}

/// One segment of a match pattern: `*`, ranges `[a-b]` of two printable ASCII
/// characters other than `/ : [ \ ]` with `a` no later than `b`, and any other
/// character but `[`, `]`, `\` and `/`.
fn pattern_segment(seg: &str) -> bool {
    let end = |c: char| ('\u{21}'..='\u{7e}').contains(&c) && !"/:[\\]".contains(c);
    let chars: Vec<char> = seg.chars().collect();
    let mut i = 0;
    while i < chars.len() {
        match chars[i] {
            '[' => {
                let ok = i + 4 < chars.len()
                    && end(chars[i + 1])
                    && chars[i + 2] == '-'
                    && end(chars[i + 3])
                    && chars[i + 4] == ']'
                    && chars[i + 1] <= chars[i + 3];
                if !ok {
                    return false;
                }
                i += 5;
            }
            ']' | '\\' | '/' | ':' => return false,
            _ => i += 1,
        }
    }
    true
}
/// A match pattern: a relative path whose segments are pattern segments.
fn pattern_ok(p: &str) -> bool {
    relative(p) && p.split('/').all(pattern_segment)
}

fn read_project(raw: &[u8]) -> Step<Vec<Binding>> {
    let bad = |why: String| stop("bad-project", why);
    let text = match std::str::from_utf8(raw) {
        Ok(t) => t,
        Err(_) => return bad("the project file is not UTF-8".into()),
    };
    if text.starts_with('\u{feff}') {
        return bad("the project file starts with a byte-order mark".into());
    }
    #[derive(PartialEq)]
    enum Here {
        Nowhere,
        Single(&'static str),
        Binding,
        Other,
    }
    let mut here = Here::Nowhere;
    let (mut project, mut policy): (Option<Table>, Option<Table>) = (None, None);
    let mut bindings: Vec<Table> = Vec::new();
    let mut others: Vec<Table> = Vec::new();
    for (number, line) in text.split('\n').enumerate() {
        let number = number + 1;
        if line.chars().any(forbidden) {
            return bad(format!(
                "line {number}: a carriage return, tab or control character"
            ));
        }
        let content = line.trim_start_matches(' ');
        if content.is_empty() || content.starts_with('#') {
            continue;
        }
        match line {
            "[project]" | "[policy]" => {
                let slot = if line == "[project]" {
                    &mut project
                } else {
                    &mut policy
                };
                if slot.is_some() {
                    return bad(format!("line {number}: {line} is given twice"));
                }
                *slot = Some(Vec::new());
                here = Here::Single(if line == "[project]" {
                    "project"
                } else {
                    "policy"
                });
                continue;
            }
            "[[binding]]" => {
                bindings.push(Vec::new());
                here = Here::Binding;
                continue;
            }
            "[[platform]]" | "[[tool]]" => {
                others.push(Vec::new());
                here = Here::Other;
                continue;
            }
            _ => {}
        }
        let key_end = line
            .find(|c: char| !(c.is_ascii_lowercase() || c == '_'))
            .unwrap_or(line.len());
        let key = &line[..key_end];
        let value = line[key_end..].strip_prefix(" = ").and_then(toml_value);
        let value = match value {
            Some(v) if !key.is_empty() => v,
            _ => {
                return bad(format!(
                    "line {number}: not in the subset of TOML a kernel reads"
                ))
            }
        };
        let table = match here {
            Here::Nowhere => None,
            Here::Single("project") => project.as_mut(),
            Here::Single(_) => policy.as_mut(),
            Here::Binding => bindings.last_mut(),
            Here::Other => others.last_mut(),
        };
        match table {
            Some(t) if !t.iter().any(|(k, _)| k == key) => t.push((key.to_owned(), value)),
            _ => {
                return bad(format!(
                    "line {number}: a key before any header, or given twice"
                ))
            }
        }
    }
    let mut out: Vec<Binding> = Vec::new();
    for table in bindings {
        let get = |k: &str| table.iter().find(|(key, _)| key == k).map(|(_, v)| v);
        let binding = match (get("name"), get("provider"), get("capabilities"), get("match")) {
            (Some(Toml::Text(n)), Some(Toml::Text(p)), Some(Toml::List(c)), None) => {
                (n, p, c, Vec::new())
            }
            (Some(Toml::Text(n)), Some(Toml::Text(p)), Some(Toml::List(c)), Some(Toml::List(m))) => {
                (n, p, c, m.clone())
            }
            _ => {
                return bad(
                    "a binding needs a string name and provider and a list of capabilities, and match is a list"
                        .into(),
                )
            }
        };
        if let Some(p) = binding.3.iter().find(|p| !pattern_ok(p)) {
            return bad(format!(
                "binding {}: the match pattern {p:?} is outside the pattern language",
                binding.0
            ));
        }
        out.push(Binding {
            name: binding.0.clone(),
            provider: binding.1.clone(),
            capabilities: binding.2.clone(),
            patterns: binding.3,
        });
    }
    for (i, b) in out.iter().enumerate() {
        if out[..i].iter().any(|a| a.name == b.name) {
            return bad(format!("two bindings are named {}", b.name));
        }
    }
    Ok(out)
}

// Step 4. Files a binding claims.

/// One file found under the root: its path from the root, and where it is.
struct Found {
    rel: String,
    /// False when some segment of the path is not UTF-8: no name the protocol carries.
    utf8: bool,
    path: PathBuf,
}

/// Every regular file under `root`, reached without a link at any step, with
/// no segment `.git`. Entries are told apart by what the listing says of them,
/// never by following them. A folder that cannot be listed is `unreadable-file`.
fn regular_files(root: &Path) -> Step<Vec<Found>> {
    let unreadable =
        |p: &Path, e: std::io::Error| stop("unreadable-file", format!("{}: {e}", p.display()));
    let mut found = Vec::new();
    let mut todo = vec![(root.to_path_buf(), String::new(), true)];
    while let Some((here, rel, utf8)) = todo.pop() {
        let entries = match fs::read_dir(&here) {
            Ok(e) => e,
            Err(e) => return unreadable(&here, e),
        };
        for entry in entries {
            let entry = match entry {
                Ok(e) => e,
                Err(e) => return unreadable(&here, e),
            };
            let name = entry.file_name();
            if name == ".git" {
                continue;
            }
            let kind = match entry.file_type() {
                Ok(k) => k,
                Err(e) => return unreadable(&entry.path(), e),
            };
            let text = name.to_str();
            let child_rel = if rel.is_empty() {
                name.to_string_lossy().into_owned()
            } else {
                format!("{rel}/{}", name.to_string_lossy())
            };
            let child_utf8 = utf8 && text.is_some();
            if kind.is_symlink() {
                continue;
            } else if kind.is_dir() {
                todo.push((entry.path(), child_rel, child_utf8));
            } else if kind.is_file() {
                found.push(Found {
                    rel: child_rel,
                    utf8: child_utf8,
                    path: entry.path(),
                });
            }
        }
    }
    Ok(found)
}

/// One segment of a path against one segment of a pattern: `*` is any run of
/// characters, `[a-b]` one character from `a` to `b`, anything else itself.
fn segment_matches(pattern: &[char], name: &[char]) -> bool {
    match pattern.first() {
        None => name.is_empty(),
        Some('*') => (0..=name.len()).any(|i| segment_matches(&pattern[1..], &name[i..])),
        Some('[') if pattern.len() >= 5 => {
            !name.is_empty()
                && pattern[1] <= name[0]
                && name[0] <= pattern[3]
                && segment_matches(&pattern[5..], &name[1..])
        }
        Some(c) => name.first() == Some(c) && segment_matches(&pattern[1..], &name[1..]),
    }
}
/// A pattern and a path have the same number of segments, and each segment matches.
fn matches(pattern: &str, rel: &str) -> bool {
    let (p, r): (Vec<&str>, Vec<&str>) = (pattern.split('/').collect(), rel.split('/').collect());
    p.len() == r.len()
        && p.iter().zip(&r).all(|(a, b)| {
            segment_matches(
                &a.chars().collect::<Vec<_>>(),
                &b.chars().collect::<Vec<_>>(),
            )
        })
}

/// The files a binding claims, each `{"path", "identity"}`, sorted by path.
/// A claimed file that cannot be read is `unreadable-file`.
fn claimed(files: &[Found], patterns: &[String]) -> Step<Vec<(String, String)>> {
    let mut out = Vec::new();
    for f in files {
        if !patterns.iter().any(|p| matches(p, &f.rel)) {
            continue;
        }
        if !f.utf8 {
            return stop(
                "unreadable-file",
                format!("{}: a name that is not UTF-8", f.rel),
            );
        }
        match fs::read(&f.path) {
            Ok(bytes) => out.push((f.rel.clone(), file_identity(&bytes))),
            Err(e) => return stop("unreadable-file", format!("{}: {e}", f.rel)),
        }
    }
    out.sort_by(|a, b| order(&a.0, &b.0));
    Ok(out)
}
fn file_refs(files: &[(String, String)]) -> Value {
    Value::Array(
        files
            .iter()
            .map(|(p, i)| {
                json::object(vec![
                    ("path", json::string(p)),
                    ("identity", json::string(i)),
                ])
            })
            .collect(),
    )
}

// Steps 5 and 7. A session with a provider, as in a check.

/// Every message sent to a provider and read from one, in order, each as
/// `{"to": "provider" or "kernel", "message"}`: what a run's transcript holds.
type Recorder = std::rc::Rc<std::cell::RefCell<Vec<Value>>>;

/// A session owns its connection: the ids of its requests count from 1 on it
/// alone, and however it is left, by `close` or by being dropped on a refusal,
/// `shutdown` is sent once and every process the provider started is ended.
struct Session {
    peer: Peer,
    log: Log,
    manifest: Value,
    wait: Duration,
    deadline_ms: u64,
    ids: RequestIds,
    closed: bool,
    /// The run's recorder, if it keeps a transcript. Noting a message never
    /// changes what is sent or how an answer is judged.
    recorder: Option<Recorder>,
}
/// The ids of one session's requests: "1", "2" and on, never shared with another session.
struct RequestIds {
    next: u64,
}
impl RequestIds {
    fn new() -> RequestIds {
        RequestIds { next: 1 }
    }
    fn take(&mut self) -> String {
        let id = self.next.to_string();
        self.next += 1;
        id
    }
}
impl Drop for Session {
    fn drop(&mut self) {
        self.close();
    }
}
impl Session {
    /// Start the binding's provider in `root`, say hello, and read its manifest.
    fn open(input: &Input, binding: &Binding) -> Step<Session> {
        // Step 3 has made sure the site has this provider.
        let command = match input.provider(&binding.provider) {
            Some(p) => &p.command,
            None => return stop("no-provider", binding.provider.clone()),
        };
        let tree = Tree::spawn(
            Command::new(&command[0])
                .args(&command[1..])
                .current_dir(&input.root)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped()),
        );
        let mut tree = match tree {
            Ok(t) => t,
            // A provider that could not be confined to a tree of its own has been ended.
            Err(e) => {
                let why = if proc::unconfined(&e) {
                    "not confined"
                } else {
                    "not started"
                };
                return stop(
                    "provider-not-started",
                    format!("{}: {why}: {e}", binding.provider),
                );
            }
        };
        let log = match tree.child.stderr.take() {
            Some(stderr) => Log::drain(stderr, MAX_LOG),
            None => return stop("provider-not-started", binding.provider.clone()),
        };
        let mut s = Session {
            peer: Peer::new(tree, host::MAX_LINE, true),
            log,
            manifest: Value::Null,
            wait: Duration::from_millis(input.deadline_ms),
            deadline_ms: input.deadline_ms,
            ids: RequestIds::new(),
            closed: false,
            recorder: input.recorder.clone(),
        };
        // A provider closed by a project is given its whole moment to exit on
        // its own after `shutdown`, even if it first writes a late answer: a
        // session refused at its deadline is closed while that answer may
        // still be on its way. The late answer is never read as one.
        s.peer.wait_out_grace();
        match s.greet(binding) {
            Ok(()) => Ok(s),
            Err(reason) => {
                s.close();
                stop(reason, binding.provider.clone())
            }
        }
    }
    fn greet(&mut self, binding: &Binding) -> Result<(), &'static str> {
        self.send_and_note(
            &hello(host::MAX_LINE, self.deadline_ms),
        )?;
        let m = self.peer.read(Instant::now() + self.wait)?;
        self.note("kernel", &m);
        if !manifest_ok(&m) || host::manifest(&m).is_none() {
            return Err("bad-manifest");
        }
        let manifest = m.get("manifest");
        let strings = ["name", "version", "protocol"]
            .iter()
            .all(|k| manifest.text(k).is_some());
        if !strings || manifest.text("protocol") != Some("0.2") {
            return Err("bad-manifest");
        }
        if manifest.text("name") != Some(binding.provider.as_str()) {
            return Err("provider-mismatch");
        }
        self.manifest = manifest.clone();
        Ok(())
    }
    /// The request this session sends next, with its own id: "1" for the first.
    fn request(&mut self, capability: &str, body: Value) -> (String, Value) {
        let id = self.ids.take();
        let request = json::object(vec![
            ("type", json::string("request")),
            ("id", json::string(&id)),
            ("deadline_ms", Value::Number(self.deadline_ms as i64)),
            ("capability", json::string(capability)),
            ("body", body),
        ]);
        (id, request)
    }
    /// One request, and the body of its result.
    fn ask(&mut self, capability: &str, body: Value) -> Result<Value, &'static str> {
        let (id, request) = self.request(capability, body);
        self.peer.send(&request, Instant::now() + self.wait)?;
        self.note("provider", &request);
        let a = self.peer.read(Instant::now() + self.wait)?;
        self.note("kernel", &a);
        if a.text("id") != Some(id.as_str()) {
            return Err("wrong-id");
        }
        if a.text("type") == Some("error") {
            return Err("provider-error");
        }
        if a.text("type") != Some("result") || !is_object(a.opt("body")) {
            return Err("unexpected");
        }
        if a.text("capability") != Some(capability) {
            return Err("wrong-capability");
        }
        Ok(a.get("body").clone())
    }
    /// `shutdown`, a second to exit, and every process the provider started
    /// ended. What it writes after its answer is not read.
    /// Once only: a second call, or the drop after a `close`, does nothing.
    fn close(&mut self) {
        if self.closed {
            return;
        }
        self.closed = true;
        let _ = self.peer.shutdown(Instant::now() + wire::SHUTDOWN_GRACE);
        // `shutdown` is the one message the wire layer sends itself: noted
        // only if it was written whole, and after it was.
        note_shutdown(self.recorder.as_ref(), self.peer.said_shutdown());
        self.peer.end();
        self.log.settle();
    }
    fn send_and_note(&mut self, message: &Value) -> Result<(), &'static str> {
        self.peer.send(message, Instant::now() + self.wait)?;
        self.note("provider", message);
        Ok(())
    }
    /// Note a message sent (`to` "provider") or read (`to` "kernel"), if the
    /// run keeps a transcript.
    fn note(&self, to: &str, message: &Value) {
        note_to(self.recorder.as_ref(), to, message);
    }
}

/// The one place a transcript entry is made. A message is noted once it was
/// written whole to a provider (`to` "provider") or read whole from one as a
/// message (`to` "kernel", noted before it is judged), never before; so the
/// entries are in the order the messages crossed the wire, over every session.
/// A send that failed or a line that is no message is not noted.
fn note_to(recorder: Option<&Recorder>, to: &str, message: &Value) {
    if let Some(r) = recorder {
        r.borrow_mut().push(json::object(vec![
            ("to", json::string(to)),
            ("message", message.clone()),
        ]));
    }
}

/// Note the `shutdown` the wire layer sent, if it was written whole.
fn note_shutdown(recorder: Option<&Recorder>, said: bool) {
    if said {
        note_to(recorder, "provider", &json::object(vec![("type", json::string("shutdown"))]));
    }
}

/// Ask one binding's provider one thing, and end the session whatever the answer.
fn consult(
    input: &Input,
    binding: &Binding,
    capability: &str,
    body: Value,
) -> Step<(Value, Value)> {
    let mut s = Session::open(input, binding)?;
    let answer = s.ask(capability, body);
    s.close();
    match answer {
        Ok(body) => Ok((body, std::mem::replace(&mut s.manifest, Value::Null))),
        Err(reason) => stop(reason, format!("{}: {capability}", binding.provider)),
    }
}

/// Ask one binding's provider one thing, and keep the session open if the
/// answer came: for the run command, whose checks go to the provider that
/// enumerated. On a broken session it is closed before the refusal, as
/// `consult` closes it; dropped later, on any refusal, it is closed then.
fn consult_and_keep(
    input: &Input,
    binding: &Binding,
    capability: &str,
    body: Value,
) -> Step<(Value, Session)> {
    let mut s = Session::open(input, binding)?;
    match s.ask(capability, body) {
        Ok(body) => Ok((body, s)),
        Err(reason) => {
            s.close();
            stop(reason, format!("{}: {capability}", binding.provider))
        }
    }
}

/// The served bindings that list `capability`, sorted by name.
fn listing<'a>(bindings: &'a [Binding], capability: &str) -> Vec<&'a Binding> {
    let mut out: Vec<&Binding> = bindings.iter().filter(|b| b.serves(capability)).collect();
    out.sort_by(|a, b| order(&a.name, &b.name));
    out
}

// Steps 5 and 6. Obligations and their keys.

struct Obligations {
    /// name -> {"preimage": P}, in the order found. Moved into J by `snapshot`.
    found: Vec<(String, Value)>,
    /// Every obligation as {"binding", "name"}, sorted by binding and then name.
    listed: Vec<(String, String)>,
    not_checkable: Vec<String>,
    /// For the run command only (empty for `status`): the session of each
    /// binding that lists `obligation.check`, kept open, sorted by binding.
    kept: Vec<Kept>,
    /// For the run command only: what each listed obligation's check is
    /// started with, in the order found.
    checks: Vec<Checkable>,
}

/// A session kept open after `obligation.enumerate` for the checks of its
/// binding (run step 5), with what its manifest declared then. Dropping it
/// closes the session.
#[allow(dead_code)]
struct Kept {
    binding: String,
    session: Session,
    /// The manifest lists `obligation.check`; a check on a session whose
    /// manifest does not is counted as refused (run step 11).
    offers_check: bool,
    /// The tools the manifest declares, as the host checks read them.
    declared: Vec<String>,
    /// The class and rank the manifest declares for `obligation.check`.
    ceiling: host::Ceiling,
}

/// What a check of one obligation is started with (run step 11), as it was
/// measured in steps 4 to 6, so that what is checked is what was keyed.
#[allow(dead_code)]
struct Checkable {
    binding: String,
    name: String,
    /// The obligation as enumerated, with its `binding` and without `inputs`.
    obligation: Value,
    /// F: each file the provider listed in `inputs`, with the identity it was keyed with.
    inputs: Vec<(String, String)>,
    /// The site's tools the manifest names, `{"name", "version", "digest"}`, in the site's order.
    tools: Value,
    /// The site's platform object exactly as given.
    platform: Value,
    /// The preimage of step 6, which a recorded verdict carries.
    preimage: Value,
}

#[allow(dead_code)]
impl Checkable {
    /// The body of the request that starts the check, as the host checks give it.
    fn start(&self) -> Value {
        json::object(vec![
            ("op", json::string("start")),
            ("obligation", self.obligation.clone()),
            ("inputs", file_refs(&self.inputs)),
            ("tools", self.tools.clone()),
            ("platform", self.platform.clone()),
        ])
    }
    /// What the host check rules judge each run and the final against.
    fn given(&self, declared: &[String], ceiling: &host::Ceiling) -> host::Given {
        host::Given {
            obligation: self.obligation.clone(),
            inputs: self.inputs.clone(),
            tools: self
                .tools
                .array()
                .iter()
                .map(|t| (t.get("name").str().to_owned(), t.get("digest").str().to_owned()))
                .collect(),
            platform: self.platform.clone(),
            declared: declared.to_vec(),
            ceiling: ceiling.clone(),
        }
    }
}

/// The obligation as a check is started with it: as enumerated, without
/// `inputs`, with `binding`.
fn as_checked(o: &Value, binding: &str) -> Value {
    let mut members: Vec<(String, Value)> = o
        .object()
        .iter()
        .filter(|(k, _)| k != "inputs" && k != "binding")
        .cloned()
        .collect();
    members.push(("binding".to_owned(), json::string(binding)));
    sorted_object(members)
}

/// Whether a manifest (the `manifest` object) lists `obligation.check`.
fn offers_check(manifest: &Value) -> bool {
    list(manifest.opt("capabilities"))
        .unwrap_or_default()
        .iter()
        .any(|c| c.text("capability") == Some("obligation.check"))
}

fn obligation_shaped(o: &Value) -> bool {
    is_object(Some(o))
        && named(o, "name")
        && o.text("kind").is_some()
        && strings(o.opt("specified_by")).is_some()
        && strings(o.opt("targets")).is_some()
        && o.text("expect").is_some()
        && is_object(o.opt("config"))
        && o.opt("defect_of")
            .is_none_or(|d| matches!(d, Value::String(_)))
        && o.opt("inputs").is_some()
}

/// Steps 5 and 6. With `keep` (the run command), the session of a binding
/// that lists `obligation.check` stays open, and what each check is started
/// with is kept; without it (the status command), every session is ended as
/// soon as its answer is read, before the answer is judged.
fn obligations(
    input: &Input,
    bindings: &[Binding],
    claims: &[(String, Vec<(String, String)>)],
    keep: bool,
) -> Step<Obligations> {
    let mut out = Obligations {
        found: Vec::new(),
        listed: Vec::new(),
        not_checkable: Vec::new(),
        kept: Vec::new(),
        checks: Vec::new(),
    };
    for binding in listing(bindings, "obligation.enumerate") {
        let files: &[(String, String)] = claims
            .iter()
            .find(|(n, _)| *n == binding.name)
            .map_or(&[], |(_, f)| f);
        let body = json::object(vec![
            ("binding", json::string(&binding.name)),
            ("definitions", Value::Array(vec![])),
            ("files", file_refs(files)),
        ]);
        // A session kept here is closed when it is dropped, on every refusal below.
        let (answer, manifest, session) = if keep && binding.serves("obligation.check") {
            let (answer, s) = consult_and_keep(input, binding, "obligation.enumerate", body)?;
            (answer, s.manifest.clone(), Some(s))
        } else {
            let (answer, manifest) = consult(input, binding, "obligation.enumerate", body)?;
            (answer, manifest, None)
        };
        let bad = |why: &str| stop("bad-answer", format!("binding {}: {why}", binding.name));
        // Each rule over every obligation of the answer before the next rule.
        let items = match list(answer.opt("obligations")) {
            Some(items) => items,
            None => return bad("obligations is not a list"),
        };
        let rejected = match answer.opt("rejected") {
            None => &[][..],
            Some(r) => match list(Some(r)) {
                Some(r)
                    if r.iter()
                        .all(|x| is_object(Some(x)) && x.text("name").is_some()) =>
                {
                    r
                }
                _ => return bad("rejected is not a list of objects each with a string name"),
            },
        };
        if !items.iter().all(obligation_shaped) {
            return bad("an obligation does not have the shape the contract gives");
        }
        let identity_of = |p: &str| files.iter().find(|(f, _)| f == p).map(|(_, i)| i.clone());
        for o in items {
            let ok = strings(o.opt("inputs"))
                .is_some_and(|i| sorted_once(&i) && i.iter().all(|p| identity_of(p).is_some()));
            if !ok {
                return stop("bad-inputs", o.get("name").str().to_owned());
            }
        }
        for o in items {
            let inputs = strings(o.opt("inputs")).unwrap_or_default();
            let named = strings(o.opt("specified_by"))
                .unwrap_or_default()
                .into_iter()
                .chain(strings(o.opt("targets")).unwrap_or_default());
            if !named.into_iter().all(|p| inputs.contains(&p)) {
                return stop("unknown-file", o.get("name").str().to_owned());
            }
        }
        let provider = input.provider(&binding.provider).map_or("", |p| &p.code);
        // The site's tools that the provider's manifest names, in the site's order.
        let named_tools: Vec<&str> = list(manifest.opt("tools"))
            .unwrap_or_default()
            .iter()
            .filter_map(|t| t.text("name"))
            .collect();
        let tools = Value::Array(
            input
                .tools
                .array()
                .iter()
                .filter(|t| t.text("name").is_some_and(|n| named_tools.contains(&n)))
                .cloned()
                .collect(),
        );
        // The same tools, as a check is started with them: with their versions.
        let tools_given = Value::Array(
            input
                .tools_given
                .array()
                .iter()
                .filter(|tool| tool.text("name").is_some_and(|name| named_tools.contains(&name)))
                .cloned()
                .collect(),
        );
        let version = format!(
            "{}+{}+{}",
            manifest.get("version").str(),
            provider,
            input.runner
        );
        for o in items {
            let name = o.get("name").str();
            if out.found.iter().any(|(n, _)| n == name) {
                return stop("duplicate-obligation", name.to_owned());
            }
            let inputs: Vec<(String, String)> = strings(o.opt("inputs"))
                .unwrap_or_default()
                .into_iter()
                .map(|p| {
                    let i = identity_of(&p).unwrap_or_default();
                    (p, i)
                })
                .collect();
            let identities = |field: &str| {
                let paths = strings(o.opt(field)).unwrap_or_default();
                texts(&sort_set(
                    inputs
                        .iter()
                        .filter(|(p, _)| paths.contains(p))
                        .map(|(_, i)| i.clone())
                        .collect(),
                ))
            };
            let closure = sort_set(
                inputs
                    .iter()
                    .map(|(p, i)| {
                        canonical::identity(&json::object(vec![
                            ("path", json::string(p)),
                            ("identity", json::string(i)),
                        ]))
                    })
                    .collect(),
            );
            let preimage = json::object(vec![
                (
                    "obligation",
                    json::string(&canonical::identity(&json::object(vec![
                        ("binding", json::string(&binding.name)),
                        ("name", json::string(name)),
                    ]))),
                ),
                ("kind", json::string("check")),
                (
                    "inputs",
                    json::object(vec![
                        ("specified_by", identities("specified_by")),
                        ("targets", identities("targets")),
                        ("closure", texts(&closure)),
                        ("tools", tools.clone()),
                        (
                            "config",
                            json::string(&canonical::identity(o.get("config"))),
                        ),
                        ("expect", o.get("expect").clone()),
                    ]),
                ),
                (
                    "provider",
                    json::object(vec![
                        ("name", manifest.get("name").clone()),
                        ("version", json::string(&version)),
                        ("protocol", manifest.get("protocol").clone()),
                    ]),
                ),
            ]);
            if keep {
                out.checks.push(Checkable {
                    binding: binding.name.clone(),
                    name: name.to_owned(),
                    obligation: as_checked(o, &binding.name),
                    inputs: inputs.clone(),
                    tools: tools_given.clone(),
                    platform: input.platform_given.clone(),
                    preimage: preimage.clone(),
                });
            }
            out.found
                .push((name.to_owned(), json::object(vec![("preimage", preimage)])));
            out.listed.push((binding.name.clone(), name.to_owned()));
        }
        out.not_checkable
            .extend(rejected.iter().map(|r| r.get("name").str().to_owned()));
        if let Some(session) = session {
            // `greet` has read the manifest with `host::manifest`, so it has this shape.
            let (declared, ceiling) = host::manifest(&json::object(vec![(
                "manifest",
                session.manifest.clone(),
            )]))
            .unwrap_or_default();
            out.kept.push(Kept {
                binding: binding.name.clone(),
                offers_check: offers_check(&session.manifest),
                declared,
                ceiling,
                session,
            });
        }
    }
    out.listed
        .sort_by(|a, b| order(&a.0, &b.0).then_with(|| order(&a.1, &b.1)));
    out.not_checkable = sort_set(std::mem::take(&mut out.not_checkable));
    Ok(out)
}

// Step 7. Intents.

fn person(v: Option<&Value>) -> bool {
    is_object(v) && v.is_some_and(|p| p.text("id").is_some())
}
fn criterion_shaped(c: &Value) -> bool {
    is_object(Some(c))
        && named(c, "id")
        && c.text("statement").is_some()
        && c.text("gate").is_some()
        && list(c.opt("links")).is_some_and(|links| {
            links.iter().all(|l| {
                is_object(Some(l)) && l.text("binding").is_some() && l.text("obligation").is_some()
            })
        })
}
fn intent_shaped(i: &Value) -> bool {
    is_object(Some(i))
        && named(i, "name")
        && i.text("text").is_some()
        && person(i.opt("owner"))
        && (i.opt("worker").is_none() || person(i.opt("worker")))
        && list(i.opt("children")).is_some_and(|c| {
            c.iter()
                .all(|c| matches!(c, Value::String(s) if !s.is_empty()))
        })
        && list(i.opt("criteria")).is_some_and(|c| c.iter().all(criterion_shaped))
}

struct Intents {
    /// id -> the intent as status scenarios take it, sorted by id.
    judged: Vec<(String, Value)>,
    /// A criterion declares what no status rule reads yet.
    unread: bool,
}

fn intents(
    input: &Input,
    bindings: &[Binding],
    claims: &[(String, Vec<(String, String)>)],
    listed: &[(String, String)],
) -> Step<Intents> {
    let mut answers: Vec<Value> = Vec::new();
    let obligations = Value::Array(
        listed
            .iter()
            .map(|(b, n)| {
                json::object(vec![
                    ("binding", json::string(b)),
                    ("name", json::string(n)),
                ])
            })
            .collect(),
    );
    for binding in listing(bindings, "intent.index") {
        let files: &[(String, String)] = claims
            .iter()
            .find(|(n, _)| *n == binding.name)
            .map_or(&[], |(_, f)| f);
        let body = json::object(vec![
            ("binding", json::string(&binding.name)),
            ("files", file_refs(files)),
            ("obligations", obligations.clone()),
        ]);
        let (answer, _) = consult(input, binding, "intent.index", body)?;
        let rejected = match answer.opt("rejected") {
            None => Some(&[][..]),
            Some(r) => {
                list(Some(r)).filter(|r| r.iter().all(|x| is_object(Some(x)) && named(x, "path")))
            }
        };
        let items = list(answer.opt("intents"));
        let (items, rejected) = match (items, rejected) {
            (Some(i), Some(r)) if i.iter().all(intent_shaped) => (i, r),
            _ => {
                return stop(
                    "bad-answer",
                    format!(
                        "binding {}: the answer does not have the shape the contract gives",
                        binding.name
                    ),
                )
            }
        };
        if !rejected.is_empty() {
            let paths: Vec<&str> = rejected.iter().filter_map(|r| r.text("path")).collect();
            return stop("intent-unreadable", paths.join(", "));
        }
        answers.extend(items.iter().cloned());
    }
    let criteria = |i: &Value| i.get("criteria").array().to_vec();
    let unread = answers.iter().flat_map(criteria).any(|c| {
        c.opt("limit_days").is_some()
            || c.opt("not_applicable").is_some()
            || c.get("links")
                .array()
                .iter()
                .any(|l| l.opt("varying").is_some())
    });
    // Over the intents of every binding, each rule over every intent before the next.
    for i in &answers {
        let ids: Vec<&str> = i
            .get("criteria")
            .array()
            .iter()
            .map(|c| c.get("id").str())
            .collect();
        if (1..ids.len()).any(|k| ids[..k].contains(&ids[k])) {
            return stop("duplicate-criterion", i.get("name").str().to_owned());
        }
    }
    for i in &answers {
        for c in i.get("criteria").array() {
            for l in c.get("links").array() {
                let (b, o) = (l.get("binding").str(), l.get("obligation").str());
                if !listed.iter().any(|(lb, lo)| lb == b && lo == o) {
                    return stop(
                        "unknown-link",
                        format!(
                            "{} criterion {}: {b}/{o}",
                            i.get("name").str(),
                            c.get("id").str()
                        ),
                    );
                }
            }
        }
    }
    let names: Vec<&str> = answers.iter().map(|i| i.get("name").str()).collect();
    if let Some(k) = (1..names.len()).find(|&k| names[..k].contains(&names[k])) {
        return stop("duplicate-intent", names[k].to_owned());
    }
    let children = |i: &Value| sort_set(strings(i.opt("children")).unwrap_or_default());
    let mut parent: Vec<(String, String)> = Vec::new();
    for i in &answers {
        for child in children(i) {
            if parent.iter().any(|(c, _)| *c == child) {
                return stop("two-parents", child);
            }
            parent.push((child, i.get("name").str().to_owned()));
        }
    }
    let parent_of = |n: &str| parent.iter().find(|(c, _)| c == n).map(|(_, p)| p.as_str());
    for name in &names {
        let mut seen = vec![*name];
        let mut here = *name;
        while let Some(p) = parent_of(here) {
            if seen.contains(&p) {
                return stop("intent-cycle", (*name).to_owned());
            }
            seen.push(p);
            here = p;
        }
    }
    let judged = answers
        .iter()
        .map(|i| {
            let criteria = i
                .get("criteria")
                .array()
                .iter()
                .map(|c| {
                    let checked_by = sort_set(
                        c.get("links")
                            .array()
                            .iter()
                            .map(|l| l.get("obligation").str().to_owned())
                            .collect(),
                    );
                    (
                        c.get("id").str().to_owned(),
                        json::object(vec![
                            ("words", c.get("statement").clone()),
                            ("gate", c.get("gate").clone()),
                            ("checked_by", texts(&checked_by)),
                        ]),
                    )
                })
                .collect();
            let worker = i.opt("worker").and_then(|w| w.text("id")).unwrap_or("");
            (
                i.get("name").str().to_owned(),
                json::object(vec![
                    ("owner", i.get("owner").get("id").clone()),
                    ("worker", json::string(worker)),
                    ("children", texts(&children(i))),
                    ("words", i.get("text").clone()),
                    ("criteria", sorted_object(criteria)),
                ]),
            )
        })
        .collect();
    let mut judged: Vec<(String, Value)> = judged;
    judged.sort_by(|a, b| order(&a.0, &b.0));
    Ok(Intents { judged, unread })
}

// Step 8. Ledgers.

#[derive(PartialEq)]
enum Where {
    Present,
    /// Nothing there, and every folder on the way could be entered.
    Absent,
    /// A link to nothing at some step, a folder on the way that cannot be
    /// entered, or anything else in the way: never read as no entries.
    Unreadable,
}
fn ledger_state(root: &Path, rel: &str) -> Where {
    let mut here = root.to_path_buf();
    for part in rel.split('/') {
        here.push(part);
        match fs::metadata(&here) {
            Ok(_) => {}
            Err(e) if e.kind() == ErrorKind::NotFound => {
                return match fs::symlink_metadata(&here) {
                    Err(e) if e.kind() == ErrorKind::NotFound => Where::Absent,
                    _ => Where::Unreadable,
                }
            }
            Err(_) => return Where::Unreadable,
        }
    }
    Where::Present
}

/// Whether two paths are one file, as the operating system identifies files.
#[cfg(unix)]
fn same_file(a: &Path, b: &Path) -> bool {
    use std::os::unix::fs::MetadataExt;
    match (fs::metadata(a), fs::metadata(b)) {
        (Ok(a), Ok(b)) => a.dev() == b.dev() && a.ino() == b.ino(),
        _ => false,
    }
}
/// Whether the handles identify the same file on Windows.
#[cfg(windows)]
fn same_file(a: &Path, b: &Path) -> bool {
    file_id::same(a, b).unwrap_or_else(|| {
        match (fs::canonicalize(a), fs::canonicalize(b)) {
            (Ok(a), Ok(b)) => a == b,
            _ => false,
        }
    })
}

#[cfg(windows)]
#[allow(unsafe_code)]
mod file_id {
    use std::fs::{File, OpenOptions};
    use std::os::windows::fs::OpenOptionsExt;
    use std::os::windows::io::AsRawHandle;
    use std::path::Path;

    const FILE_FLAG_BACKUP_SEMANTICS: u32 = 0x0200_0000;
    const FILE_ID_INFO: i32 = 18;

    #[repr(C)]
    #[derive(PartialEq, Eq)]
    struct FileIdInfo {
        volume: u64,
        file: [u8; 16],
    }

    #[link(name = "kernel32")]
    extern "system" {
        fn GetFileInformationByHandleEx(
            file: *mut std::ffi::c_void,
            class: i32,
            info: *mut std::ffi::c_void,
            size: u32,
        ) -> i32;
    }

    fn id(file: &File) -> Option<FileIdInfo> {
        let mut info = FileIdInfo { volume: 0, file: [0; 16] };
        // SAFETY: file owns the live handle and info holds writable storage of
        // the documented FILE_ID_INFO layout and size for the duration of the call.
        let ok = unsafe {
            GetFileInformationByHandleEx(
                file.as_raw_handle(),
                FILE_ID_INFO,
                (&mut info as *mut FileIdInfo).cast(),
                std::mem::size_of::<FileIdInfo>() as u32,
            )
        };
        (ok != 0).then_some(info)
    }

    pub fn same(a: &Path, b: &Path) -> Option<bool> {
        let open = |path: &Path| {
            OpenOptions::new()
                .access_mode(0)
                .custom_flags(FILE_FLAG_BACKUP_SEMANTICS)
                .open(path)
                .ok()
        };
        // Keep both handles open for the entire comparison.
        let (a, b) = (open(a)?, open(b)?);
        Some(id(&a)? == id(&b)?)
    }
}

/// Without a file index in the standard library, the same file is the same
/// path once every link is resolved. A hard link is not recognised.
#[cfg(not(any(unix, windows)))]
fn same_file(a: &Path, b: &Path) -> bool {
    match (fs::canonicalize(a), fs::canonicalize(b)) {
        (Ok(a), Ok(b)) => a == b,
        _ => false,
    }
}

struct Read {
    entries: Vec<Value>,
    torn: bool,
    absent: bool,
}
fn read_ledger(root: &Path, rel: &str) -> Step<Read> {
    match ledger_state(root, rel) {
        Where::Unreadable => {
            return stop(
                "unreadable-file",
                format!("{rel}: a link to nothing or a folder that cannot be entered on the way"),
            )
        }
        Where::Absent => {
            return Ok(Read {
                entries: vec![],
                torn: false,
                absent: true,
            })
        }
        Where::Present => {}
    }
    let path = root.join(rel);
    match fs::metadata(&path) {
        Ok(m) if m.is_file() => {}
        Ok(_) => return stop("corrupt-ledger", format!("{rel} is not a file")),
        Err(e) => return stop("unreadable-file", format!("{rel}: {e}")),
    }
    // Read as `ledger-read` reads: strictly, as the ledger format requires.
    let path_text = match path.to_str() {
        Some(t) => t,
        None => {
            return stop(
                "unreadable-file",
                format!("{rel}: a path that is not UTF-8"),
            )
        }
    };
    let read = match ledger::read(&json::object(vec![("ledger", json::string(path_text))])) {
        Ok(r) => r,
        Err(e) => return stop("unreadable-file", format!("{rel}: {e}")),
    };
    match (read.opt("entries"), read.opt("torn"), read.opt("at")) {
        (Some(Value::Array(entries)), Some(Value::Bool(torn)), _) => Ok(Read {
            entries: entries.clone(),
            torn: *torn,
            absent: false,
        }),
        (_, _, at) => stop(
            "corrupt-ledger",
            format!("{rel}, line {}", at.map_or_else(String::new, json::encode)),
        ),
    }
}

struct Ledgers {
    /// The entries read, in order: acts from the owner's ledger, then everything else from the others.
    entries: Vec<Value>,
    torn: bool,
    /// Ledgers the site names, not the owner's, that do not exist.
    absent: bool,
}
fn ledgers(input: &Input) -> Step<Ledgers> {
    let root = &input.root;
    let owner = &input.owner_ledger;
    if link_on_the_way(root, owner) {
        return stop("owner-ledger-link", owner.clone());
    }
    let state = ledger_state(root, owner);
    if state == Where::Unreadable {
        return stop(
            "unreadable-file",
            format!("{owner}: a folder on its way cannot be entered"),
        );
    }
    if state == Where::Present && !fs::metadata(root.join(owner)).is_ok_and(|m| m.is_file()) {
        return stop(
            "owner-ledger-link",
            format!("{owner} is not a regular file"),
        );
    }
    let mut sources: Vec<(&str, bool)> = Vec::new();
    let mut seen: Vec<PathBuf> = Vec::new();
    if state == Where::Present {
        sources.push((owner, true));
        seen.push(root.join(owner));
    }
    // A file already read, the owner's ledger included, however its path is spelt, is not read again.
    for rel in &input.ledgers {
        let path = root.join(rel);
        let present = ledger_state(root, rel) == Where::Present;
        if present && seen.iter().any(|s| same_file(&path, s)) {
            continue;
        }
        sources.push((rel, false));
        if present {
            seen.push(path);
        }
    }
    let mut out = Ledgers {
        entries: Vec::new(),
        torn: false,
        absent: false,
    };
    for (rel, is_owner) in sources {
        let read = read_ledger(root, rel)?;
        out.absent |= read.absent && !is_owner;
        out.torn |= read.torn;
        // Acts count from the owner's ledger alone, and nothing else is read from it.
        out.entries.extend(
            read.entries
                .into_iter()
                .filter(|e| (e.text("kind") == Some("act")) == is_owner),
        );
    }
    Ok(out)
}

// Step 11. Coverage.

fn coverage(intents: &[(String, Value)], floor: i64) -> Value {
    let floor = floor.max(1);
    let children = |name: &str| -> Vec<String> {
        intents
            .iter()
            .find(|(n, _)| n == name)
            .and_then(|(_, i)| strings(i.opt("children")))
            .unwrap_or_default()
    };
    let parent_of = |name: &str| -> Option<&str> {
        intents
            .iter()
            .find(|(_, i)| children_of(i).iter().any(|c| c == name))
            .map(|(n, _)| n.as_str())
    };
    let root_of = |name: &str| -> String {
        let mut here = name;
        while let Some(p) = parent_of(here) {
            here = p;
        }
        here.to_owned()
    };
    let own = |name: &str| -> i64 {
        intents.iter().find(|(n, _)| n == name).map_or(0, |(_, i)| {
            i.get("criteria")
                .object()
                .iter()
                .filter(|(_, c)| !matches!(c.text("gate"), Some("soft" | "deferred")))
                .count() as i64
        })
    };
    // It and every intent below it, each once and only if defined.
    let below = |name: &str| -> i64 {
        let mut found: Vec<String> = Vec::new();
        let mut todo = vec![name.to_owned()];
        while let Some(here) = todo.pop() {
            if !found.contains(&here) && intents.iter().any(|(n, _)| *n == here) {
                todo.extend(children(&here));
                found.push(here);
            }
        }
        found.iter().map(|n| own(n)).sum()
    };
    let mut each = Vec::new();
    let mut thinnest: Vec<(String, (String, i64))> = Vec::new();
    for (name, _) in intents {
        let root = root_of(name);
        let subtree = below(name);
        each.push((
            name.clone(),
            json::object(vec![
                ("own_hard", Value::Number(own(name))),
                ("subtree_hard", Value::Number(subtree)),
                ("root", json::string(&root)),
                ("tree_hard", Value::Number(below(&root))),
                ("floor", Value::Number(floor)),
                (
                    "floor_met_only_over_tree",
                    Value::Bool(*name != root && subtree < floor),
                ),
            ]),
        ));
        // `intents` is sorted, so the first on a tie is kept.
        match thinnest.iter_mut().find(|(r, _)| *r == root) {
            Some((_, best)) if own(name) < best.1 => *best = (name.clone(), own(name)),
            Some(_) => {}
            None => thinnest.push((root, (name.clone(), own(name)))),
        }
    }
    json::object(vec![
        ("intents", sorted_object(each)),
        (
            "thinnest",
            sorted_object(
                thinnest
                    .into_iter()
                    .map(|(r, (n, _))| (r, json::string(&n)))
                    .collect(),
            ),
        ),
    ])
}
fn children_of(i: &Value) -> Vec<String> {
    strings(i.opt("children")).unwrap_or_default()
}

// The whole command.

/// What the status command reads of a project and judges, steps 2 to 10. The
/// run command plans from the same, so the two read a project one way.
struct Snapshot {
    not_served: Vec<(String, String)>,
    obligations: Obligations,
    intents: Intents,
    read: Ledgers,
    /// J, the status scenario of step 10.
    judged: Value,
    /// The last result the status rules give for J.
    report: Value,
}

/// Steps 2 to 10, on an input step 1 has read. `keep` is for the run command
/// (see `obligations`); the status command passes false.
fn snapshot(input: &Input, keep: bool) -> Step<Snapshot> {
    let root = &input.root;
    // Step 2.
    if !plain_file(root, &input.project) {
        return stop(
            "bad-project",
            "the project file is not a regular file reached without a link",
        );
    }
    let project = match fs::read(root.join(&input.project)) {
        Ok(p) => p,
        Err(e) => return stop("unreadable-file", format!("{}: {e}", input.project)),
    };
    let bindings = read_project(&project)?;
    // Step 3.
    let mut not_served: Vec<(String, String)> = bindings
        .iter()
        .flat_map(|b| {
            b.capabilities
                .iter()
                .filter(|c| !SERVED.contains(&c.as_str()))
                .map(|c| (b.name.clone(), c.clone()))
        })
        .collect();
    not_served.sort_by(|a, b| order(&a.0, &b.0).then_with(|| order(&a.1, &b.1)));
    not_served.dedup();
    let served: Vec<&Binding> = bindings
        .iter()
        .filter(|b| SERVED.iter().any(|c| b.serves(c)))
        .collect();
    if let Some(b) = served
        .iter()
        .find(|b| input.provider(&b.provider).is_none())
    {
        return stop("no-provider", format!("binding {}: {}", b.name, b.provider));
    }
    // Step 4. First every served binding's files are claimed, then overlaps are looked for.
    let mut claims: Vec<(String, Vec<(String, String)>)> = Vec::new();
    if !served.is_empty() {
        let files = regular_files(root)?;
        for b in &served {
            claims.push((b.name.clone(), claimed(&files, &b.patterns)?));
        }
    }
    for capability in SERVED {
        let mut owners: Vec<(&str, &str)> = Vec::new();
        for (b, (name, files)) in served.iter().zip(&claims) {
            if !b.serves(capability) {
                continue;
            }
            for (path, _) in files {
                if let Some((_, other)) = owners.iter().find(|(p, _)| p == path) {
                    return stop(
                        "overlapping-bindings",
                        format!("{path} is claimed by {other} and {name} for {capability}"),
                    );
                }
                owners.push((path, name));
            }
        }
    }
    // Steps 5 and 6.
    let mut obligations = obligations(input, &bindings, &claims, keep)?;
    // Step 7.
    let intents = intents(&input, &bindings, &claims, &obligations.listed)?;
    // Step 8.
    let read = ledgers(&input)?;
    // Step 9.
    let policy = json::object(vec![
        ("min_hard_gates", Value::Number(input.min_hard_gates.max(1))),
        ("required", texts(&input.required)),
        ("trusted_writers", Value::Array(vec![])),
        ("floors", input.floors.clone()),
        ("attestors", Value::Object(vec![])),
        ("makes", Value::Array(vec![])),
    ]);
    // Step 10.
    let steps = steps_of(&read.entries);
    let judged = json::object(vec![
        ("kind", json::string("status")),
        ("name", json::string("this-project")),
        (
            "self",
            json::object(vec![
                ("writer", json::string(&input.writer)),
                ("platform", json::string(&input.platform)),
            ]),
        ),
        ("policy", policy),
        // Moved, not copied: nothing reads `found` after J is made.
        ("obligations", sorted_object(std::mem::take(&mut obligations.found))),
        ("intents", sorted_object(intents.judged.clone())),
        ("steps", steps),
    ]);
    // The report is what the status rules give for J, and nothing else.
    let report = status::run(&judged).pop().unwrap_or(Value::Null);
    Ok(Snapshot {
        not_served,
        obligations,
        intents,
        read,
        judged,
        report,
    })
}

/// The steps of J (step 10): one `append` for each entry read, in order, and
/// then one step that names nothing, so a project with an empty ledger has a
/// report too.
fn steps_of(entries: &[Value]) -> Value {
    let mut steps: Vec<Value> = entries
        .iter()
        .map(|e| {
            json::object(vec![(
                "do",
                json::object(vec![(
                    "append",
                    json::object(vec![
                        ("kind", e.get("kind").clone()),
                        ("body", e.get("body").clone()),
                    ]),
                )]),
            )])
        })
        .collect();
    steps.push(json::object(vec![(
        "do",
        json::object(vec![(
            "set_gate",
            json::object(vec![
                ("intent", json::string("")),
                ("criterion", json::string("")),
                ("to", json::string("hard")),
            ]),
        )]),
    )]));
    Value::Array(steps)
}

fn run(raw: &[u8]) -> Step<Value> {
    // Step 1.
    let input = read_input(raw)?;
    let snapshot = snapshot(&input, false)?;
    Ok(output(&input, snapshot))
}

/// Step 11 and the answer, from what steps 2 to 10 read and judged. The run
/// command's report (its step 14) is made here too, from a snapshot judged
/// again after the ledgers are read again.
fn output(input: &Input, snapshot: Snapshot) -> Value {
    let Snapshot {
        not_served,
        obligations,
        intents,
        read,
        judged,
        report,
    } = snapshot;
    // Step 11.
    let coverage = coverage(&intents.judged, input.min_hard_gates);
    // What could hide a failure the report does not show, in the contract's order and words.
    let required_with_children = input.required.iter().any(|r| {
        intents
            .judged
            .iter()
            .any(|(n, i)| n == r && !children_of(i).is_empty())
    });
    let doubts: Vec<&str> = [
        (!input.not_applied.is_empty(), "policy no status rule applies"),
        (
            required_with_children,
            "a required intent has children, and no status rule reads descendants yet",
        ),
        (
            !obligations.not_checkable.is_empty(),
            "obligations the provider could not make into checks",
        ),
        (
            intents.unread,
            "criteria declare what no status rule reads yet: a deferred gate's limit, runs that must agree, or evidence not applicable",
        ),
        (read.torn, "a ledger ends in an entry cut short"),
        (read.absent, "a ledger the site names does not exist"),
    ]
    .into_iter()
    .filter_map(|(holds, words)| holds.then_some(words))
    .collect();
    let stated = report
        .opt("project")
        .and_then(|p| p.text("status"))
        .unwrap_or("unknown")
        .to_owned();
    let project_status =
        if !doubts.is_empty() && matches!(stated.as_str(), "passed" | "nothing-required") {
            "unknown"
        } else {
            stated.as_str()
        };
    json::object(vec![
        ("judged", judged),
        ("report", report),
        ("coverage", coverage),
        ("policy_source", json::string(&input.policy_source)),
        (
            "ledger",
            json::object(vec![
                ("entries", Value::Number(read.entries.len() as i64)),
                ("torn", Value::Bool(read.torn)),
            ]),
        ),
        (
            "not_served",
            Value::Array(
                not_served
                    .iter()
                    .map(|(b, c)| {
                        json::object(vec![
                            ("binding", json::string(b)),
                            ("capability", json::string(c)),
                        ])
                    })
                    .collect(),
            ),
        ),
        ("not_checkable", texts(&obligations.not_checkable)),
        ("policy_not_applied", texts(&input.not_applied)),
        (
            "project_doubts",
            Value::Array(doubts.into_iter().map(json::string).collect()),
        ),
        ("project_status", json::string(project_status)),
    ])
}

#[cfg(test)]
mod run_cli_tests {
    use super::*;

    // The probe is this test program, run in the case's temporary project.
    // A relative marker avoids modifying process-wide environment from a test.
    #[test]
    #[ignore = "the probe a run test starts; not a test of its own"]
    fn leave_a_mark() {
        assert!(Path::new("probe-root").is_file());
        fs::write("probe-started", b"started").unwrap();
    }
    fn probe() -> Vec<String> {
        vec![
            std::env::current_exe().unwrap().to_str().unwrap().to_owned(),
            "--ignored".to_owned(),
            "--exact".to_owned(),
            "project_status::run_cli_tests::leave_a_mark".to_owned(),
            "--quiet".to_owned(),
        ]
    }
    fn strings_of(items: &[String]) -> Value {
        Value::Array(items.iter().map(|s| json::string(s)).collect())
    }
    fn v(s: &str) -> Value {
        json::parse(s.as_bytes()).unwrap()
    }
    fn scratch(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("dodona-run-cli-{}-{name}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }
    /// A status input for `root`, its one provider started as `provider`.
    fn status_input(root: &Path, provider: &[String]) -> Vec<(String, Value)> {
        let site = json::object(vec![
            ("platform", v(r#"{"os":"linux","arch":"x86_64"}"#)),
            ("writer", json::string("w")),
            ("runner", json::string("r")),
            ("tools", Value::Array(vec![])),
            (
                "providers",
                json::object(vec![(
                    "p",
                    json::object(vec![("command", strings_of(provider)), ("code", Value::Array(vec![]))]),
                )]),
            ),
            ("deadline_ms", Value::Number(5000)),
        ]);
        vec![
            ("root", json::string(root.to_str().unwrap())),
            ("project", json::string("dodona.toml")),
            ("site", site),
            ("policy", v(r#"{"required":[],"min_hard_gates":1,"floors":{},"not_applied":[]}"#)),
            ("policy_source", json::string("test")),
            ("ledgers", v(r#"["l/run.ledger"]"#)),
            ("owner_ledger", json::string("records/owner.ledger")),
        ]
        .into_iter()
        .map(|(k, v)| (k.to_owned(), v))
        .collect()
    }
    fn bytes(fields: &[(String, Value)]) -> Vec<u8> {
        json::encode(&Value::Object(fields.to_vec())).into_bytes()
    }

    #[test]
    fn a_run_refused_at_step_1_starts_no_process() {
        let root = scratch("refused");
        let mark = root.join("probe-started");
        fs::write(root.join("probe-root"), b"").unwrap();
        // Control: the probe leaves a mark when started in the project.
        let p = probe();
        assert!(std::process::Command::new(&p[0])
            .args(&p[1..])
            .current_dir(&root)
            .status()
            .unwrap()
            .success());
        assert!(mark.exists());
        fs::remove_file(&mark).unwrap();
        // A project whose one binding would start the probe as its provider.
        fs::write(
            root.join("dodona.toml"),
            "[[binding]]\nname = \"b\"\nprovider = \"p\"\ncapabilities = [\"obligation.enumerate\"]\nmatch = [\"*.txt\"]\n",
        )
        .unwrap();
        fs::write(root.join("a.txt"), b"a").unwrap();
        // Step 1 refuses: the run's ledger is not one of `ledgers`.
        let mut fields = status_input(&root, &p);
        fields.push(("ledger".to_owned(), json::string("l/other.ledger")));
        fields.push(("executor".to_owned(), strings_of(&p)));
        let answer = run_answer(&bytes(&fields));
        assert_eq!(answer.text("refused"), Some("bad-input"));
        assert_eq!(answer.object().len(), 2);
        assert!(answer.text("detail").is_some());
        // Neither the provider nor the executor was started.
        assert!(!mark.exists());
        // Input that is not JSON at all is refused the same way, never a crash.
        assert_eq!(run_answer(b"not json").text("refused"), Some("bad-input"));
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn a_run_with_nothing_to_check_reports_as_status_does_and_starts_nothing() {
        let root = scratch("nothing");
        let mark = root.join("probe-started");
        fs::write(root.join("probe-root"), b"").unwrap();
        let p = probe();
        // A project with no binding: nothing to enumerate, nothing to check.
        fs::write(root.join("dodona.toml"), "[project]\nname = \"empty\"\n").unwrap();
        let status = status_input(&root, &p);
        let mut fields = status.clone();
        fields.push(("ledger".to_owned(), json::string("l/run.ledger")));
        fields.push(("executor".to_owned(), strings_of(&p)));
        fields.push(("transcript".to_owned(), json::string("t.json")));
        let answer = run_answer(&bytes(&fields));
        assert!(answer.opt("refused").is_none(), "{}", json::encode(&answer));
        // Every count is 0, and no executor and no provider was started.
        for (_, n) in answer.get("counts").object() {
            assert_eq!(n.number(), 0);
        }
        assert!(!mark.exists());
        // Nothing to record: no ledger written.
        assert!(!root.join("l").exists());
        // The report is what `status` reports straight afterwards.
        let mut without_counts = answer.clone();
        if let Value::Object(f) = &mut without_counts {
            f.retain(|(k, _)| k != "counts");
        }
        assert_eq!(json::encode(&without_counts), json::encode(&answer_of(&bytes(&status))));
        // The transcript is a new file holding every message: none here.
        assert_eq!(fs::read(root.join("t.json")).unwrap(), b"[]");
        let _ = fs::remove_dir_all(&root);
    }
    fn answer_of(input: &[u8]) -> Value {
        answer(input)
    }
}

/// The run command (conformance/README.md, "How a project's run is judged"):
/// its input, plan, checks, batches, record, report and transcript. `main`
/// reaches it through `run_answer` alone.
#[cfg_attr(not(test), allow(dead_code))]
mod run_input {
    use super::*;
    use crate::unicode;
    use crate::unicode_tables::FOLD;

    /// The status command's input, with what the run command takes beyond it.
    pub(super) struct RunInput {
        pub(super) status: Input,
        /// The ledger verdicts are appended to: one of `status.ledgers`.
        pub(super) ledger: String,
        pub(super) executor: Vec<String>,
        pub(super) transcript: Option<String>,
        pub(super) batch_wait_floor: Duration,
    }

    /// Full case folding, one character at a time, with no normalization.
    fn casefold(s: &str) -> String {
        let mut out = String::new();
        for c in s.chars() {
            match FOLD.binary_search_by_key(&(c as u32), |x| x.0) {
                Ok(i) => out.extend(FOLD[i].1.iter().filter_map(|&v| char::from_u32(v))),
                Err(_) => out.push(c),
            }
        }
        out
    }

    /// A path as a disk that ignores case and Unicode normalization compares
    /// names: the NFC of the case-folded NFC.
    fn disk_name(p: &str) -> String {
        unicode::nfc(&casefold(&unicode::nfc(p)))
    }

    /// Step 1 of the run command. The run's own fields are checked first,
    /// before the status command's checks of step 1, and so before any file
    /// is read or any provider started; those of them that look at files only
    /// when `root` is a directory. Every rule broken is `bad-input`.
    pub(super) fn read(raw: &[u8]) -> Step<RunInput> {
        let bad = |why: &str| stop("bad-input", why);
        let v = match framed(raw) {
            Some(v) => v,
            None => return bad("the input is not one JSON object alone, read strictly"),
        };
        // A status field of the wrong type is the status checks' to refuse:
        // here it only names nothing.
        let ledgers = strings(v.opt("ledgers")).unwrap_or_default();
        let owner = v.text("owner_ledger");
        let ledger = match v.text("ledger") {
            Some(l) if relative(l) => l.to_owned(),
            _ => return bad("ledger must be a relative path"),
        };
        if !ledgers.contains(&ledger) {
            return bad("ledger must be one of ledgers, so that what this run records the next run reads");
        }
        if owner.is_some_and(|o| disk_name(o) == disk_name(&ledger)) {
            return bad("ledger is the owner's ledger, as a disk that ignores case and normalization compares names");
        }
        let executor = match strings(v.opt("executor")) {
            Some(e) if !e.is_empty() && !e.iter().any(|a| a.contains('\0')) => e,
            _ => return bad("executor must be a non-empty list of strings, none holding a NUL"),
        };
        let batch_wait_floor = match v.opt("batch_wait_floor_ms") {
            None => Duration::ZERO,
            Some(Value::Number(n)) if (1..=MAX_DEADLINE_MS).contains(n) => Duration::from_millis(*n as u64),
            _ => return bad("batch_wait_floor_ms must be an integer from 1 to 86400000"),
        };
        let transcript = match v.opt("transcript") {
            None => None,
            Some(Value::String(t)) if relative(t) => Some(t.clone()),
            Some(_) => return bad("transcript must be a relative path"),
        };
        // A disk that drops the dots and spaces a name ends in would take such a
        // path for another: the ledger and the owner's ledger always, and, when
        // a transcript is written, every path it must not land on. Judged on the
        // spelling alone, before any file is looked at.
        let aliased = |p: &str| {
            relative(p) && p.split('/').any(|s| s.ends_with('.') || s.ends_with(' '))
        };
        let mut spelt: Vec<&str> = vec![ledger.as_str()];
        spelt.extend(owner);
        if let Some(t) = &transcript {
            spelt.push(t.as_str());
            spelt.extend(ledgers.iter().map(String::as_str));
            spelt.extend(v.text("project"));
        }
        if let Some(p) = spelt.into_iter().find(|p| aliased(*p)) {
            return stop(
                "bad-input",
                format!("{p:?}: a segment ends in a dot or a space, which a disk may take for another name"),
            );
        }
        if let Some(t) = &transcript {
            let name = disk_name(t);
            let taken = ledgers
                .iter()
                .map(String::as_str)
                .chain(owner)
                .flat_map(|l| [l.to_owned(), format!("{l}.lock")])
                .chain(v.text("project").map(str::to_owned))
                .any(|p| disk_name(&p) == name);
            if taken {
                return bad("transcript names a ledger, a ledger's lock or the project file");
            }
        }
        let root = v
            .text("root")
            .map(PathBuf::from)
            .filter(|r| fs::metadata(r).is_ok_and(|m| m.is_dir()));
        if let Some(root) = root {
            if link_on_the_way(&root, &ledger) {
                return bad("ledger is reached through a link");
            }
            if owner.is_some_and(|o| relative(o) && same_file(&root.join(&ledger), &root.join(o))) {
                return bad("ledger is the owner's ledger, as the operating system identifies files");
            }
            if let Some(t) = &transcript {
                if link_on_the_way(&root, t) {
                    return bad("transcript is reached through a link");
                }
                let path = root.join(t);
                // No step below root is a link (above), so this follows none.
                let folder = path.parent().unwrap_or(root.as_path());
                if !fs::metadata(folder).is_ok_and(|m| m.is_dir()) {
                    return bad("transcript's folder is not there");
                }
                match fs::symlink_metadata(&path) {
                    Err(e) if e.kind() == ErrorKind::NotFound => {}
                    _ => return bad("transcript is there already, or cannot be looked at"),
                }
            }
        }
        let status = read_input(raw)?;
        Ok(RunInput {
            status,
            ledger,
            executor,
            transcript,
            batch_wait_floor,
        })
    }

    /// What step 10 of the run command plans, and what the counts of step 14
    /// will be made from.
    pub(super) struct Plan {
        /// To be checked: every listed obligation whose status is not a current
        /// result, as (binding, name), sorted by binding and then name.
        pub(super) to_check: Vec<(String, String)>,
        /// Reused: listed obligations that are `passed`, `failed` or `conflict`,
        /// sorted the same way. Nothing is sent for them.
        pub(super) reused: Vec<(String, String)>,
        /// How many obligations the providers listed. A name both listed and
        /// rejected is listed; a name only rejected is not one.
        pub(super) obligations: usize,
        /// How many names are not checkable, those both listed and rejected included.
        pub(super) not_checkable: usize,
    }

    /// Step 10. The status of each obligation is the report's, from the status
    /// rules applied to the scenario of the status command's step 10; this
    /// applies no rule of its own. Only `passed`, `failed` and `conflict` are
    /// current results: anything else, `unknown` above all, is checked.
    pub(super) fn plan(listed: &[(String, String)], not_checkable: &[String], report: &Value) -> Plan {
        let status = |name: &str| {
            report
                .opt("obligations")
                .and_then(|o| o.opt(name))
                .and_then(|o| o.text("status"))
        };
        let mut sorted = listed.to_vec();
        sorted.sort_by(|a, b| order(&a.0, &b.0).then_with(|| order(&a.1, &b.1)));
        let (reused, to_check): (Vec<_>, Vec<_>) = sorted.into_iter().partition(|(_, name)| {
            matches!(status(name.as_str()), Some("passed" | "failed" | "conflict"))
        });
        Plan {
            to_check,
            reused,
            obligations: listed.len(),
            not_checkable: not_checkable.len(),
        }
    }

    /// Steps 1 to 10 of the run command: the run's input, the project as the
    /// status command reads it with the sessions of step 5 kept for checks,
    /// and the plan. Every kept session, that of a binding with nothing to
    /// check included, stays open in the snapshot for the whole run (step 11):
    /// when each is shut down is part of what a transcript records. They are
    /// closed when the snapshot is dropped, at the end of the run or on a
    /// refusal. Not served: nothing after step 10 is done.
    pub(super) fn prepare(raw: &[u8]) -> Step<(RunInput, Snapshot, Plan)> {
        let mut input = read(raw)?;
        // Every session from here notes its messages, if a transcript is kept.
        if input.transcript.is_some() {
            input.status.recorder = Some(Recorder::default());
        }
        let snapshot = snapshot(&input.status, true)?;
        let plan = plan(
            &snapshot.obligations.listed,
            &snapshot.obligations.not_checkable,
            &snapshot.report,
        );
        Ok((input, snapshot, plan))
    }

    // Step 11. Checks, up to where a run is handed to the executor.

    /// One connection to a provider as checks use it: each request carries the
    /// connection's own next id, and each message read has its own deadline.
    /// A kept `Session` is one; tests give a scripted one.
    pub(super) trait Channel {
        /// Send an `obligation.check` request with this body; the id it carried.
        fn send_check(&mut self, body: Value) -> Result<String, &'static str>;
        /// The next message, read strictly.
        fn read(&mut self) -> Result<Value, &'static str>;
    }

    impl Channel for Session {
        fn send_check(&mut self, body: Value) -> Result<String, &'static str> {
            let (id, request) = self.request("obligation.check", body);
            self.peer.send(&request, Instant::now() + self.wait)?;
            self.note("provider", &request);
            Ok(id)
        }
        fn read(&mut self) -> Result<Value, &'static str> {
            let m = self.peer.read(Instant::now() + self.wait)?;
            self.note("kernel", &m);
            Ok(m)
        }
    }

    /// The reasons that say a session itself broke: every check on it is in
    /// doubt, so the whole run is refused with the reason and nothing is recorded.
    pub(super) const SESSION_BROKE: [&str; 13] = [
        "deadline",
        "closed",
        "framing",
        "too-long",
        "encoding",
        "malformed",
        "not-an-integer",
        "duplicate-key",
        "too-deep",
        "wrong-id",
        "wrong-capability",
        "unexpected",
        "provider-error",
    ];

    /// Whether a check can be asked of its binding's session at all: there is
    /// one (the binding lists `obligation.check`) and its manifest offers the
    /// check. Otherwise the obligation is counted as `refused`, and nothing is sent.
    pub(super) fn can_check(offers_check: Option<bool>) -> bool {
        offers_check == Some(true)
    }

    /// One check under way: what the host rules judge it against, and its runs.
    pub(super) struct Check {
        pub(super) binding: String,
        pub(super) name: String,
        given: host::Given,
        /// The obligation and inputs as the check was started: a run key is made from them.
        obligation: Value,
        inputs: Value,
        /// The id of the `start` request: each `run.result` names it.
        pub(super) start_id: String,
        /// The id of the request whose answer is awaited.
        awaited: String,
        /// How many runs have been handed on.
        pub(super) runs: usize,
    }

    /// What one answer to a check gives.
    #[derive(Debug)]
    pub(super) enum Answer {
        /// A run for the executor, numbered from 1, with its key.
        Run {
            number: usize,
            run_key: String,
            run: Value,
        },
        /// A verdict from a `final` that every rule accepts, with the final's
        /// `strength` as the provider gave it (null when it gave none). For
        /// `passed` and `failed`, `host::final_verdict` has bounded it by the
        /// manifest's class and rank; step 13 records it with the verdict.
        Verdict { verdict: String, strength: Value },
        /// The check ends with no verdict, and is counted as `refused`.
        Refused(&'static str),
    }
    /// Runs are the same when their canonical encodings are.
    impl PartialEq for Answer {
        fn eq(&self, other: &Answer) -> bool {
            match (self, other) {
                (
                    Answer::Run { number: a, run_key: k, run: r },
                    Answer::Run { number: b, run_key: l, run: s },
                ) => a == b && k == l && json::encode(r) == json::encode(s),
                (
                    Answer::Verdict { verdict: a, strength: s },
                    Answer::Verdict { verdict: b, strength: t },
                ) => a == b && json::encode(s) == json::encode(t),
                (Answer::Refused(a), Answer::Refused(b)) => a == b,
                _ => false,
            }
        }
    }

    /// Start the check of `c` on `ch`, as the host checks start one. An error
    /// is a session that broke, which refuses the whole run.
    pub(super) fn start(
        ch: &mut dyn Channel,
        c: &Checkable,
        declared: &[String],
        ceiling: &host::Ceiling,
    ) -> Result<Check, &'static str> {
        let body = c.start();
        let id = ch.send_check(body.clone())?;
        Ok(Check {
            binding: c.binding.clone(),
            name: c.name.clone(),
            given: c.given(declared, ceiling),
            obligation: body.get("obligation").clone(),
            inputs: body.get("inputs").clone(),
            start_id: id.clone(),
            awaited: id,
            runs: 0,
        })
    }

    /// Read and judge the answer to the request the check awaits: the host
    /// checks' rules, in their order. `root` is where attachments are found.
    pub(super) fn answer(
        ch: &mut dyn Channel,
        check: &mut Check,
        root: &Path,
    ) -> Result<Answer, &'static str> {
        let a = ch.read()?;
        if let Some(fault) = crate::session::answer_fault(&a, &check.awaited, "obligation.check") {
            return Err(fault);
        }
        let body = a.opt("body");
        if !is_object(body) {
            return Err("unexpected");
        }
        let (next, fin) = (body.and_then(|b| b.opt("next")), body.and_then(|b| b.opt("final")));
        let run = match (next, fin) {
            (Some(run), None) => run,
            (None, Some(f)) => {
                return Ok(match host::final_verdict(&check.given, check.runs, f, root) {
                    Ok(verdict) => Answer::Verdict {
                        verdict,
                        strength: f.opt("strength").cloned().unwrap_or(Value::Null),
                    },
                    Err(reason) => Answer::Refused(reason),
                })
            }
            _ => return Ok(Answer::Refused("neither-or-both")),
        };
        if let Some(fault) = host::run_fault(&check.given, check.runs, run) {
            return Ok(Answer::Refused(fault));
        }
        check.runs += 1;
        Ok(Answer::Run {
            number: check.runs,
            run_key: host::run_key(&check.obligation, &check.inputs, check.runs, run),
            run: run.clone(),
        })
    }

    /// Pass an executor's report for run `number` back to the check's provider,
    /// on the same session, under the session's next id.
    pub(super) fn pass_back(
        ch: &mut dyn Channel,
        check: &mut Check,
        number: usize,
        report: Value,
    ) -> Result<(), &'static str> {
        let body = json::object(vec![
            ("op", json::string("run.result")),
            ("check", json::string(&check.start_id)),
            ("run", Value::Number(number as i64)),
            ("report", report),
        ]);
        check.awaited = ch.send_check(body)?;
        Ok(())
    }

    // Steps 11 and 12 together: the checks of the plan, and the batches their runs form.

    /// What an executor did with one batch, as far as the process goes. The
    /// answer it printed is judged by `fates`.
    pub(super) enum Batch {
        /// It could not start, exited with a status other than 0, or printed
        /// no first line that can be read strictly as one object.
        Failed,
        /// It was not done within the wait.
        TimedOut,
        /// The object it printed as its first line.
        Answered(Value),
    }

    /// The site's executor, given one batch, `{"runs": [...]}`, and how long it
    /// may take. The real one starts the executor command in `root`; tests give
    /// a scripted one.
    pub(super) trait Executor {
        fn batch(&mut self, runs: &Value, wait: Duration) -> Batch;
    }

    /// What a batch gives one of its runs: a verdict that ends its check, or a
    /// report to read as the host checks read one.
    #[derive(Debug)]
    pub(super) enum Fate {
        Verdict(&'static str),
        Report(Value),
    }

    /// Step 12, for each run of a batch, given by its key in the batch's order.
    /// The batch as a whole first: not answered in time, `error` for every run;
    /// failed, or an answer that is not an object with `ended` true and a list
    /// `reports`, `unavailable` for every run; an item that is not an object
    /// with a string `run_key` of the batch and a `report`, or a key given
    /// twice, `error` for every run. Then each run: no report, or a report that
    /// is not an object, `error` for its own check.
    pub(super) fn fates(batch: &Batch, keys: &[String]) -> Vec<Fate> {
        let all = |v: &'static str| -> Vec<Fate> { keys.iter().map(|_| Fate::Verdict(v)).collect() };
        let answer = match batch {
            Batch::TimedOut => return all("error"),
            Batch::Failed => return all("unavailable"),
            Batch::Answered(a) => a,
        };
        let reports = match (answer.opt("ended"), list(answer.opt("reports"))) {
            (Some(Value::Bool(true)), Some(r)) if is_object(Some(answer)) => r,
            _ => return all("unavailable"),
        };
        let mut seen: Vec<&str> = Vec::new();
        for item in reports {
            let key = item.text("run_key");
            let fits = is_object(Some(item))
                && item.opt("report").is_some()
                && key.is_some_and(|k| keys.iter().any(|x| x == k) && !seen.contains(&k));
            if !fits {
                return all("error");
            }
            seen.extend(key);
        }
        keys.iter()
            .map(|k| {
                let report = reports
                    .iter()
                    .find(|r| r.text("run_key") == Some(k.as_str()))
                    .map(|r| r.get("report"));
                match report {
                    Some(r @ Value::Object(_)) => Fate::Report(r.clone()),
                    _ => Fate::Verdict("error"),
                }
            })
            .collect()
    }

    /// One binding's session as the checks use it, with what its manifest declared.
    pub(super) struct Lane<'a> {
        pub(super) binding: String,
        pub(super) channel: &'a mut dyn Channel,
        pub(super) offers_check: bool,
        pub(super) declared: Vec<String>,
        pub(super) ceiling: host::Ceiling,
    }

    /// How a planned check ended.
    #[derive(Debug)]
    pub(super) enum Ended {
        /// A verdict, from the provider's `final` or from the executor, with
        /// the final's strength as the rules accepted it (null otherwise).
        Verdict { verdict: String, strength: Value },
        /// No verdict: counted as `refused`.
        Refused(&'static str),
    }

    /// One planned check, ended: everything step 13 records it from.
    pub(super) struct Finished {
        pub(super) binding: String,
        pub(super) name: String,
        /// How many runs were handed to the executor.
        pub(super) runs: usize,
        pub(super) ended: Ended,
    }

    /// A check with a run waiting for the next batch.
    struct Open {
        plan: usize,
        lane: usize,
        check: Check,
        number: usize,
        run_key: String,
        run: Value,
    }

    /// What one answer leaves: a check still open, or how it ended.
    fn settle(answer: Answer, plan: usize, lane: usize, check: Check) -> Result<Open, (usize, Ended, usize)> {
        match answer {
            Answer::Run { number, run_key, run } => Ok(Open { plan, lane, check, number, run_key, run }),
            Answer::Verdict { verdict, strength } => {
                Err((plan, Ended::Verdict { verdict, strength }, check.runs))
            }
            Answer::Refused(reason) => Err((plan, Ended::Refused(reason), check.runs)),
        }
    }

    /// Steps 11 and 12: take every planned check, in the plan's order, on its
    /// binding's own session, each started and its first answer read before
    /// the next is started; send the runs all open checks ask for as one batch,
    /// in the order the checks were started; pass each report back in that
    /// order, reading each provider's answer before the next report is sent;
    /// and again, until no check is open. The host rules bound each check to
    /// eight runs. An error is a session that broke: the whole run is refused
    /// with it, nothing more is sent, and nothing is recorded.
    pub(super) fn schedule(
        lanes: &mut [Lane],
        to_check: &[(String, String)],
        checks: &[Checkable],
        executor: &mut dyn Executor,
        root: &Path,
        batch_wait_floor: Duration,
    ) -> Result<Vec<Finished>, &'static str> {
        let mut ended: Vec<Option<(Ended, usize)>> = to_check.iter().map(|_| None).collect();
        let mut open: Vec<Open> = Vec::new();
        for (i, (binding, name)) in to_check.iter().enumerate() {
            let lane = lanes.iter().position(|l| &l.binding == binding);
            let checkable = checks.iter().find(|c| &c.binding == binding && &c.name == name);
            let (l, c) = match (lane, checkable) {
                (Some(l), Some(c)) if can_check(Some(lanes[l].offers_check)) => (l, c),
                _ => {
                    ended[i] = Some((Ended::Refused("not-offered"), 0));
                    continue;
                }
            };
            let lane = &mut lanes[l];
            let mut check = start(&mut *lane.channel, c, &lane.declared, &lane.ceiling)?;
            let a = answer(&mut *lane.channel, &mut check, root)?;
            match settle(a, i, l, check) {
                Ok(o) => open.push(o),
                Err((p, e, runs)) => ended[p] = Some((e, runs)),
            }
        }
        while !open.is_empty() {
            let runs = Value::Array(
                open.iter()
                    .map(|o| {
                        json::object(vec![
                            ("number", Value::Number(o.number as i64)),
                            ("run_key", json::string(&o.run_key)),
                            ("run", o.run.clone()),
                        ])
                    })
                    .collect(),
            );
            let wait = open
                .iter()
                .map(|o| host::executor_wait(&o.run))
                .max()
                .unwrap_or_default()
                .max(batch_wait_floor);
            let keys: Vec<String> = open.iter().map(|o| o.run_key.clone()).collect();
            let batch = executor.batch(&json::object(vec![("runs", runs)]), wait);
            let mut next = Vec::new();
            for (mut o, fate) in std::mem::take(&mut open).into_iter().zip(fates(&batch, &keys)) {
                let report = match fate {
                    Fate::Verdict(v) => {
                        let e = Ended::Verdict { verdict: v.to_owned(), strength: Value::Null };
                        ended[o.plan] = Some((e, o.check.runs));
                        continue;
                    }
                    Fate::Report(r) => r,
                };
                // Read as the host checks read a report, before the provider sees it.
                if let Some(v) = host::report_fault(&o.run, Some(&report)) {
                    let e = Ended::Verdict { verdict: v.to_owned(), strength: Value::Null };
                    ended[o.plan] = Some((e, o.check.runs));
                    continue;
                }
                let channel = &mut *lanes[o.lane].channel;
                pass_back(channel, &mut o.check, o.number, report)?;
                let a = answer(channel, &mut o.check, root)?;
                match settle(a, o.plan, o.lane, o.check) {
                    Ok(still) => next.push(still),
                    Err((p, e, runs)) => ended[p] = Some((e, runs)),
                }
            }
            open = next;
        }
        Ok(to_check
            .iter()
            .zip(ended)
            .map(|((binding, name), e)| {
                let (ended, runs) = e.unwrap_or((Ended::Refused("not-offered"), 0));
                Finished { binding: binding.clone(), name: name.clone(), runs, ended }
            })
            .collect())
    }

    // Step 12. The site's executor, run as a process.

    use std::io::{Read as IoRead, Write as IoWrite};
    use std::sync::mpsc;

    /// A started executor as a batch waits for it: whether it has exited, and
    /// if so whether with status 0; and ending it with all it started.
    pub(super) trait Started {
        fn exit_status(&mut self) -> Option<bool>;
        fn end_tree(&mut self);
    }
    impl Started for Tree {
        fn exit_status(&mut self) -> Option<bool> {
            match self.child.try_wait() {
                Ok(Some(status)) => Some(status.success()),
                Ok(None) => None,
                Err(_) => Some(false),
            }
        }
        fn end_tree(&mut self) {
            self.end();
        }
    }

    /// The first line of what a reader gives, without its line feed, read to
    /// the end: what follows the first line is read and dropped, never parsed
    /// or kept, so an executor that writes more is not stopped from exiting.
    /// The first line is kept whole, however long. None when there is no line
    /// feed at all or reading fails.
    pub(super) fn first_line_of(mut out: impl IoRead) -> Option<Vec<u8>> {
        let mut line = Vec::new();
        let mut found = false;
        let mut buf = [0u8; 8192];
        loop {
            match out.read(&mut buf) {
                Ok(0) => break,
                Ok(n) if !found => match buf[..n].iter().position(|b| *b == b'\n') {
                    Some(p) => {
                        line.extend_from_slice(&buf[..p]);
                        found = true;
                    }
                    None => line.extend_from_slice(&buf[..n]),
                },
                Ok(_) => {}
                Err(e) if e.kind() == std::io::ErrorKind::Interrupted => {}
                Err(_) => return None,
            }
        }
        found.then_some(line)
    }

    /// What an executor that exited and closed its output answered: one JSON
    /// object, read strictly, as its first line, ended by a line feed alone,
    /// with no byte-order mark. Anything else, or a status other than 0, is
    /// `Failed`, which the batch reads as `unavailable`.
    pub(super) fn judge_output(success: bool, line: Option<&[u8]>) -> Batch {
        let line = match (success, line) {
            (true, Some(l)) => l,
            _ => return Batch::Failed,
        };
        if line.is_empty() || line.ends_with(b"\r") || line.starts_with(b"\xEF\xBB\xBF") {
            return Batch::Failed;
        }
        match std::str::from_utf8(line).ok().map(wire::strict) {
            Some(Ok(v @ Value::Object(_))) => Batch::Answered(v),
            _ => Batch::Failed,
        }
    }

    /// Give a started executor its input and wait, under one deadline for all
    /// of it, for both its own exit and the end of its output. Writing the
    /// input and reading the output run beside the wait, so neither can hold
    /// it past `until`: an executor that does not read, or a process it
    /// started that keeps its output open, ends the batch as `TimedOut`. On
    /// every way out the executor is ended with everything it started, and
    /// nothing else.
    pub(super) fn await_batch(
        started: &mut dyn Started,
        stdin: Option<Box<dyn IoWrite + Send>>,
        stdout: Box<dyn IoRead + Send>,
        input: Vec<u8>,
        until: Instant,
    ) -> Batch {
        await_batch_reaped(started, stdin, stdout, input, until, REAP_LIMIT).0
    }

    /// How long, once the executor's own group or job has been ended, the
    /// threads that wrote its input and read its output are waited for. Ending
    /// the group or job closes every end of the two pipes its processes held,
    /// so each thread then finishes at once: its write fails or its read ends.
    /// One still blocked after this means a process that left the group or job
    /// holds a pipe, which the contract puts beyond what a host can promise to
    /// end; waiting for it could last for ever, so the thread is left to finish
    /// on its own. It owns only its pipe end and a sender nobody reads.
    const REAP_LIMIT: Duration = Duration::from_secs(2);

    /// Wait up to `limit` for every worker, and join each that has finished.
    /// Whether all of them were joined.
    fn reap(workers: Vec<std::thread::JoinHandle<()>>, limit: Duration) -> bool {
        let until = Instant::now() + limit;
        while workers.iter().any(|w| !w.is_finished()) && Instant::now() < until {
            std::thread::sleep(Duration::from_millis(2));
        }
        let mut all = true;
        for w in workers {
            if w.is_finished() {
                let _ = w.join();
            } else {
                all = false;
            }
        }
        all
    }

    /// `await_batch`, and whether every worker thread was joined.
    ///
    /// A batch is answered only when, all observed no later than `until`:
    /// the whole input was written and the executor's input closed; the
    /// executor exited; and its output ended. A write that fails is `Failed`
    /// (the executor did not get its batch, whatever it printed); anything not
    /// all observed by `until` is `TimedOut`, even if it happened while the
    /// wait was between two looks.
    fn await_batch_reaped(
        started: &mut dyn Started,
        stdin: Option<Box<dyn IoWrite + Send>>,
        stdout: Box<dyn IoRead + Send>,
        input: Vec<u8>,
        until: Instant,
        limit: Duration,
    ) -> (Batch, bool) {
        let mut workers = Vec::new();
        let (wtx, wrx) = mpsc::channel();
        match stdin {
            Some(mut w) => workers.push(std::thread::spawn(move || {
                let written = w.write_all(&input).and_then(|_| w.flush()).is_ok();
                // Dropped before the receipt, so the executor has seen its input end.
                drop(w);
                let _ = wtx.send(written);
            })),
            // No way to give the input: the receipt can never come.
            None => drop(wtx),
        }
        let (otx, orx) = mpsc::channel();
        workers.push(std::thread::spawn(move || {
            let _ = otx.send(first_line_of(stdout));
        }));
        let mut written: Option<bool> = None;
        let mut status: Option<bool> = None;
        let mut line: Option<Option<Vec<u8>>> = None;
        let outcome = loop {
            if written.is_none() {
                match wrx.try_recv() {
                    Ok(ok) => written = Some(ok),
                    // No input to give, or a writer that ended without a receipt.
                    Err(mpsc::TryRecvError::Disconnected) => written = Some(false),
                    Err(mpsc::TryRecvError::Empty) => {}
                }
            }
            if status.is_none() {
                status = started.exit_status();
            }
            if line.is_none() {
                match orx.try_recv() {
                    Ok(l) => line = Some(l),
                    Err(mpsc::TryRecvError::Disconnected) => line = Some(None),
                    Err(mpsc::TryRecvError::Empty) => {}
                }
            }
            // What was seen counts only if it was seen by the deadline.
            let seen_at = Instant::now();
            if seen_at > until {
                break Batch::TimedOut;
            }
            if written == Some(false) {
                break Batch::Failed;
            }
            if let (Some(true), Some(success), Some(l)) = (written, status, &line) {
                break judge_output(success, l.as_deref());
            }
            std::thread::sleep(Duration::from_millis(5).min(until - seen_at));
        };
        started.end_tree();
        (outcome, reap(workers, limit))
    }

    /// The executor command, started once per batch in `root`, in a process
    /// group (Unix) or job (Windows) of its own.
    pub(super) struct Native<'a> {
        pub(super) command: &'a [String],
        pub(super) root: &'a Path,
    }
    impl Executor for Native<'_> {
        fn batch(&mut self, runs: &Value, wait: Duration) -> Batch {
            let until = Instant::now() + wait;
            let (program, args) = match self.command.split_first() {
                Some(p) => p,
                None => return Batch::Failed,
            };
            let spawned = Tree::spawn(
                Command::new(program)
                    .args(args)
                    .current_dir(self.root)
                    .stdin(Stdio::piped())
                    .stdout(Stdio::piped())
                    .stderr(Stdio::null()),
            );
            // One that cannot start, or could not be confined and has been
            // ended, answers nothing: `unavailable`.
            let mut tree = match spawned {
                Ok(t) => t,
                Err(_) => return Batch::Failed,
            };
            let stdin = tree
                .child
                .stdin
                .take()
                .map(|w| Box::new(w) as Box<dyn IoWrite + Send>);
            let stdout = match tree.child.stdout.take() {
                Some(r) => r,
                None => return Batch::Failed, // `tree` is ended as it is dropped
            };
            let input = json::encode(runs).into_bytes();
            await_batch(&mut tree, stdin, Box::new(stdout), input, until)
        }
    }

    // Step 13. What a run records.

    /// The level an evidence record states, from the rank of the final's
    /// strength, read as the host checks read it.
    pub(super) fn level_of(strength: &Value) -> Option<&'static str> {
        match strength.text("rank")? {
            "documented" => Some("asserted"),
            "sampled" => Some("sampled"),
            "bounded" => Some("bounded"),
            "exhaustive" => Some("proven"),
            _ => None,
        }
    }

    /// Step 13, before anything is written. For each ended check, in the order
    /// the checks were started, whose verdict is `passed` or `failed`: every
    /// input file is read again (`identity_of` gives a path's identity now, or
    /// None if it cannot be read), and each must still have the identity it
    /// was keyed with. A check one of whose inputs changed or cannot be read
    /// becomes `error`, with no strength, and is not recorded. The evidence
    /// bodies of the others, in that order. No other verdict is recorded.
    pub(super) fn evidence(
        finished: &mut [Finished],
        checks: &[Checkable],
        platform: &str,
        writer: &str,
        identity_of: &mut dyn FnMut(&str) -> Option<String>,
    ) -> Vec<Value> {
        let mut bodies = Vec::new();
        for f in finished.iter_mut() {
            let (verdict, strength) = match &f.ended {
                Ended::Verdict { verdict, strength } if verdict == "passed" || verdict == "failed" => {
                    (verdict.clone(), strength.clone())
                }
                _ => continue,
            };
            let checkable = checks.iter().find(|c| c.binding == f.binding && c.name == f.name);
            let kept = checkable.filter(|c| {
                c.inputs
                    .iter()
                    .all(|(path, id)| identity_of(path.as_str()).as_deref() == Some(id.as_str()))
            });
            let (c, level) = match (kept, level_of(&strength)) {
                (Some(c), Some(level)) => (c, level),
                _ => {
                    f.ended = Ended::Verdict { verdict: "error".to_owned(), strength: Value::Null };
                    continue;
                }
            };
            bodies.push(json::object(vec![
                ("obligation", json::string(&f.name)),
                ("preimage", c.preimage.clone()),
                ("core_key", json::string(&canonical::identity(&c.preimage))),
                ("platform", json::string(platform)),
                ("verdict", json::string(&verdict)),
                ("writer", json::string(writer)),
                ("strength", strength),
                ("level", json::string(level)),
            ]));
        }
        bodies
    }

    /// The identity of a file under `root` as it is now, following links, as
    /// an input is read again before recording.
    pub(super) fn reread(root: &Path) -> impl FnMut(&str) -> Option<String> + '_ {
        // Looked at before it is opened: a pipe or a device could block a read,
        // and is no file a check read; it is unreadable.
        move |path: &str| {
            let path = root.join(path);
            if !fs::metadata(&path).is_ok_and(|m| m.is_file()) {
                return None;
            }
            fs::read(&path).ok().map(|bytes| file_identity(&bytes))
        }
    }

    /// How long the run waits for the ledger's lock.
    pub(super) const LEDGER_WAIT: Duration = Duration::from_secs(60);

    /// Append the bodies to the run's ledger as entries of kind `evidence`, all
    /// in one append. With none, nothing is touched. Any failure is
    /// `ledger-not-written`, after which nothing is done: nothing was written,
    /// and the next run checks those obligations again.
    ///
    /// Once the ledger's lock is held, `still_permitted` is asked again before
    /// the ledger is read: a ledger that has become the owner's, or is now
    /// reached through a link, is not written. A write that fails is undone
    /// under the same lock; one whose undoing cannot be confirmed says so in
    /// the detail.
    pub(super) fn record(
        root: &Path,
        ledger: &str,
        owner: &str,
        bodies: &[Value],
        wait: Duration,
    ) -> Step<Vec<String>> {
        if bodies.is_empty() {
            return Ok(Vec::new());
        }
        let path = root.join(ledger);
        let Some(text) = path.to_str() else {
            return stop("ledger-not-written", format!("{ledger}: a path that is not UTF-8"));
        };
        let permitted = || still_permitted(root, ledger, owner);
        crate::ledger::append_entries_if(text, "evidence", bodies, wait, &permitted).or_else(|e| {
            let why = match e {
                crate::ledger::NotWritten::Unconfirmed(d) => {
                    format!("{d}; the ledger may hold part of this run's entries")
                }
                other => format!("{other:?}"),
            };
            stop("ledger-not-written", format!("{ledger}: {why}"))
        })
    }

    // Steps 11 to 14 together.

    /// Whether the run's ledger is still one it may write, checked again just
    /// before the write, with the checks step 1 made: reached without a link,
    /// and not the owner's ledger by name or, where both exist, as one file.
    /// Between this and the append nothing more is looked at: a link made in
    /// that moment is not seen.
    ///
    /// The owner's ledger is walked the same way. That is the status
    /// command's own rule for it (step 8: reached without a link at any step,
    /// a regular file if it exists, unreadable if a folder on its way cannot
    /// be entered), which step 14 applies again after the write; this only
    /// makes the run refuse before writing rather than after.
    fn still_permitted(root: &Path, ledger: &str, owner: &str) -> bool {
        disk_name(ledger) != disk_name(owner)
            && !link_on_the_way(root, ledger)
            && absent_or_regular(root, ledger)
            && absent_or_regular(root, owner)
            && surely_distinct(&root.join(ledger), &root.join(owner))
    }

    /// `rel` walked from `root` one step at a time, following no link: every
    /// step but the last a folder, and the last a regular file; or the walk
    /// ending, plainly, at a step that is not there, so nothing is there. A
    /// link or anything else at any step, or a step that cannot be looked at
    /// for any other reason, and the answer is no: a ledger is not written.
    fn absent_or_regular(root: &Path, rel: &str) -> bool {
        let steps: Vec<&str> = rel.split('/').collect();
        let mut here = root.to_path_buf();
        for (i, step) in steps.iter().enumerate() {
            here.push(step);
            match fs::symlink_metadata(&here) {
                Ok(m) if i + 1 == steps.len() => return m.file_type().is_file(),
                Ok(m) if m.file_type().is_dir() => {}
                Ok(_) => return false,
                Err(e) => return e.kind() == ErrorKind::NotFound,
            }
        }
        false
    }

    /// Whether two paths are surely not one file: one of them is plainly not
    /// there, or both are and the system says they are different files. If
    /// either cannot be looked at for another reason, no.
    fn surely_distinct(a: &Path, b: &Path) -> bool {
        let acceptable = |observed: &std::io::Result<fs::Metadata>| match observed {
            Ok(metadata) => metadata.is_file(),
            Err(error) => error.kind() == ErrorKind::NotFound,
        };
        let (left, right) = (fs::metadata(a), fs::metadata(b));
        if !acceptable(&left) || !acceptable(&right) {
            return false;
        }
        let (Ok(left), Ok(right)) = (left, right) else {
            return true;
        };
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            (left.dev(), left.ino()) != (right.dev(), right.ino())
        }
        #[cfg(windows)]
        {
            let _ = (left, right);
            file_id::same(a, b) == Some(false)
        }
        #[cfg(not(any(unix, windows)))]
        {
            let _ = (left, right);
            false
        }
    }

    /// Steps 11 to 13: every planned check on its binding's session, the runs
    /// to the executor in batches, and the verdicts that stand appended to the
    /// run's ledger. A session that breaks refuses the run before anything is
    /// written. The re-reading of inputs is `identity_of` (`reread` in a run).
    pub(super) fn finish(
        run: &RunInput,
        plan: &Plan,
        checks: &[Checkable],
        lanes: &mut [Lane],
        executor: &mut dyn Executor,
        identity_of: &mut dyn FnMut(&str) -> Option<String>,
    ) -> Step<Vec<Finished>> {
        let input = &run.status;
        let root = input.root.as_path();
        let mut finished = schedule(lanes, &plan.to_check, checks, executor, root, run.batch_wait_floor)
            .or_else(|reason| stop(reason, "a session broke during the checks: nothing is recorded"))?;
        let bodies = evidence(&mut finished, checks, &input.platform, &input.writer, identity_of);
        if !bodies.is_empty() && !still_permitted(root, &run.ledger, &input.owner_ledger) {
            return stop(
                "ledger-not-written",
                format!("{}: no longer a ledger this run may write", run.ledger),
            );
        }
        record(root, &run.ledger, &input.owner_ledger, &bodies, LEDGER_WAIT)?;
        Ok(finished)
    }

    /// The counts of step 14. `reused` and `checked` add up to `obligations`,
    /// and the verdicts and `refused` to `checked`.
    pub(super) fn counts(plan: &Plan, finished: &[Finished]) -> Value {
        let verdicts = |v: &str| {
            finished
                .iter()
                .filter(|f| matches!(&f.ended, Ended::Verdict { verdict, .. } if verdict == v))
                .count()
        };
        let refused = finished
            .iter()
            .filter(|f| matches!(f.ended, Ended::Refused(_)))
            .count();
        let n = |k: usize| Value::Number(k as i64);
        json::object(vec![
            ("obligations", n(plan.obligations)),
            ("reused", n(plan.reused.len())),
            ("checked", n(plan.to_check.len())),
            ("passed", n(verdicts("passed"))),
            ("failed", n(verdicts("failed"))),
            ("error", n(verdicts("error"))),
            ("unavailable", n(verdicts("unavailable"))),
            ("unsupported", n(verdicts("unsupported"))),
            ("refused", n(refused)),
            ("not_checkable", n(plan.not_checkable)),
        ])
    }

    /// Step 14's reading: the ledgers read again as in step 8, and J judged
    /// again with their entries. Nothing is asked of a provider. A refusal here
    /// leaves what step 13 appended where it is.
    pub(super) fn rejudge(input: &Input, mut s: Snapshot) -> Step<Snapshot> {
        let read = ledgers(input)?;
        if let Some(steps) = s.judged.opt_mut("steps") {
            *steps = steps_of(&read.entries);
        }
        s.report = status::run(&s.judged).pop().unwrap_or(Value::Null);
        s.read = read;
        Ok(s)
    }

    /// Steps 11 to 14 on what `prepare` gave. The sessions kept in the
    /// snapshot stay open until the report is made, and are closed as it is
    /// dropped, on every way out.
    pub(super) fn complete(
        run: &RunInput,
        mut snapshot: Snapshot,
        plan: &Plan,
        executor: &mut dyn Executor,
    ) -> Step<Value> {
        let root = run.status.root.clone();
        let finished = {
            let mut lanes: Vec<Lane> = snapshot
                .obligations
                .kept
                .iter_mut()
                .map(|k| Lane {
                    binding: k.binding.clone(),
                    channel: &mut k.session,
                    offers_check: k.offers_check,
                    declared: k.declared.clone(),
                    ceiling: k.ceiling.clone(),
                })
                .collect();
            let mut now = reread(&root);
            finish(run, plan, &snapshot.obligations.checks, &mut lanes, executor, &mut now)?
        };
        let counts = counts(plan, &finished);
        let snapshot = rejudge(&run.status, snapshot)?;
        // The snapshot goes with the report: every kept session is closed, its
        // `shutdown` noted, before the transcript is written.
        let mut answer = output(&run.status, snapshot);
        if let Value::Object(fields) = &mut answer {
            fields.push(("counts".to_owned(), counts));
        }
        if let (Some(rel), Some(recorder)) = (&run.transcript, &run.status.recorder) {
            let messages = recorder.borrow().clone();
            write_transcript(&run.status.root, rel, &messages)?;
        }
        Ok(answer)
    }

    /// Write the transcript as a new file: never over one that is there, and
    /// not through a link. It comes after the verdicts are recorded, so a
    /// transcript that cannot be written is `transcript-not-written` and the
    /// verdicts stay recorded. A file this made and could not finish is removed.
    pub(super) fn write_transcript(root: &Path, rel: &str, messages: &[Value]) -> Step<()> {
        let not_written = |why: String| stop("transcript-not-written", format!("{rel}: {why}"));
        if link_on_the_way(root, rel) {
            return not_written("now reached through a link".to_owned());
        }
        let path = root.join(rel);
        let mut f = match fs::OpenOptions::new().write(true).create_new(true).open(&path) {
            Ok(f) => f,
            Err(e) => return not_written(e.to_string()),
        };
        let text = json::encode(&Value::Array(messages.to_vec()));
        match f.write_all(text.as_bytes()).and_then(|_| f.sync_all()) {
            Ok(()) => Ok(()),
            Err(e) => {
                drop(f);
                let _ = fs::remove_file(&path);
                not_written(e.to_string())
            }
        }
    }

    /// A whole run with the site's executor, writing the transcript when the
    /// input names one: what `run_answer` answers.
    pub(super) fn run_native(raw: &[u8]) -> Step<Value> {
        let (run, snapshot, plan) = prepare(raw)?;
        let mut executor = Native {
            command: &run.executor,
            root: &run.status.root,
        };
        complete(&run, snapshot, &plan, &mut executor)
    }

    #[cfg(test)]
    mod record_tests {
        use super::*;

        const A: &str = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        const B: &str = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
        const OWNER: &str = "records/owner.ledger";

        fn v(s: &str) -> Value {
            json::parse(s.as_bytes()).unwrap()
        }
        fn checkable(name: &str, inputs: &[(&str, &str)]) -> Checkable {
            Checkable {
                binding: "t".to_owned(),
                name: name.to_owned(),
                obligation: Value::Object(vec![]),
                inputs: inputs.iter().map(|(p, i)| (p.to_string(), i.to_string())).collect(),
                tools: Value::Array(vec![]),
                platform: Value::Object(vec![]),
                preimage: v(&format!(r#"{{"obligation":"key-of-{name}","kind":"check"}}"#)),
            }
        }
        fn ended(name: &str, e: Ended) -> Finished {
            Finished { binding: "t".to_owned(), name: name.to_owned(), runs: 1, ended: e }
        }
        fn verdict(v: &str, strength: Value) -> Ended {
            Ended::Verdict { verdict: v.to_owned(), strength }
        }
        /// Every check of the scripted run, ended every way a check can end.
        fn run() -> (Vec<Finished>, Vec<Checkable>) {
            let finished = vec![
                ended("o1", verdict("passed", v(r#"{"class":"model","rank":"bounded","note":"n"}"#))),
                ended("o2", verdict("failed", v(r#"{"class":"model","rank":"documented"}"#))),
                ended("o3", Ended::Refused("neither-or-both")),
                ended("o4", verdict("error", Value::Null)),
                ended("o5", verdict("unavailable", Value::Null)),
                ended("o6", verdict("unsupported", Value::Null)),
            ];
            let checks = ["o1", "o2", "o3", "o4", "o5", "o6"]
                .iter()
                .map(|n| checkable(n, &[("a.txt", A), ("b.txt", B)]))
                .collect();
            (finished, checks)
        }
        /// The files as they are now.
        fn files<'a>(now: &'a [(&'a str, Option<&'a str>)]) -> impl FnMut(&str) -> Option<String> + 'a {
            move |path: &str| {
                now.iter()
                    .find(|(p, _)| *p == path)
                    .and_then(|(_, i)| i.map(str::to_owned))
            }
        }
        fn verdict_of(f: &Finished) -> &str {
            match &f.ended {
                Ended::Verdict { verdict, .. } => verdict,
                Ended::Refused(r) => r,
            }
        }
        fn scratch(name: &str) -> PathBuf {
            let dir = std::env::temp_dir().join(format!("dodona-record-{}-{name}", std::process::id()));
            let _ = fs::remove_dir_all(&dir);
            fs::create_dir_all(&dir).unwrap();
            dir
        }
        fn read_back(path: &Path) -> Value {
            let asked = json::object(vec![("ledger", json::string(path.to_str().unwrap()))]);
            crate::ledger::read(&asked).unwrap()
        }

        #[test]
        fn only_final_passed_and_failed_verdicts_become_evidence() {
            let (mut finished, checks) = run();
            let mut now = files(&[("a.txt", Some(A)), ("b.txt", Some(B))]);
            let bodies = evidence(&mut finished, &checks, "linux/x86_64", "w", &mut now);
            assert_eq!(bodies.len(), 2);
            let (first, second) = (&bodies[0], &bodies[1]);
            assert_eq!(first.text("obligation"), Some("o1"));
            assert_eq!(second.text("obligation"), Some("o2"));
            // The key the check was measured under, and its own identity.
            assert_eq!(json::encode(first.get("preimage")), json::encode(&checks[0].preimage));
            assert_eq!(first.text("core_key"), Some(canonical::identity(&checks[0].preimage).as_str()));
            assert_eq!(first.text("platform"), Some("linux/x86_64"));
            assert_eq!(first.text("writer"), Some("w"));
            assert_eq!(first.text("verdict"), Some("passed"));
            // The provider's strength exactly, and the level read from its rank.
            assert_eq!(first.get("strength").text("note"), Some("n"));
            assert_eq!(first.text("level"), Some("bounded"));
            assert_eq!(second.text("verdict"), Some("failed"));
            assert_eq!(second.text("level"), Some("asserted"));
            // Exactly these fields.
            let fields: Vec<&str> = first.object().iter().map(|(k, _)| k.as_str()).collect();
            assert_eq!(
                fields,
                ["obligation", "preimage", "core_key", "platform", "verdict", "writer", "strength", "level"]
            );
            // Nothing else changed its verdict.
            let left: Vec<&str> = finished.iter().map(verdict_of).collect();
            assert_eq!(left, ["passed", "failed", "neither-or-both", "error", "unavailable", "unsupported"]);
        }

        #[test]
        fn an_input_changed_or_unreadable_since_the_check_is_an_error_and_is_not_recorded() {
            let (mut finished, checks) = run();
            // b.txt changed: neither verdict stands.
            let mut changed = files(&[("a.txt", Some(A)), ("b.txt", Some(A))]);
            assert!(evidence(&mut finished, &checks, "p", "w", &mut changed).is_empty());
            assert_eq!(verdict_of(&finished[0]), "error");
            assert_eq!(verdict_of(&finished[1]), "error");
            assert!(matches!(&finished[0].ended, Ended::Verdict { strength: Value::Null, .. }));
            // a.txt cannot be read.
            let (mut finished, checks) = run();
            let mut gone = files(&[("a.txt", None), ("b.txt", Some(B))]);
            assert!(evidence(&mut finished, &checks, "p", "w", &mut gone).is_empty());
            assert_eq!(verdict_of(&finished[0]), "error");
            // With nothing to record, nothing is touched: not even the ledger's folder.
            let root = scratch("nothing");
            assert_eq!(record(&root, "l/run.ledger", OWNER, &[], Duration::from_millis(10)).ok(), Some(vec![]));
            assert!(!root.join("l").exists());
            let _ = fs::remove_dir_all(&root);
        }

        #[test]
        fn verdicts_are_appended_in_one_append_under_one_lock() {
            let (mut finished, checks) = run();
            let mut now = files(&[("a.txt", Some(A)), ("b.txt", Some(B))]);
            let bodies = evidence(&mut finished, &checks, "linux/x86_64", "w", &mut now);
            let root = scratch("two");
            let ids = match record(&root, "l/run.ledger", OWNER, &bodies, Duration::from_millis(100)) {
                Ok(ids) => ids,
                Err(s) => panic!("{} {}", s.reason, s.detail),
            };
            let read = read_back(&root.join("l/run.ledger"));
            let entries = read.get("entries").array();
            assert_eq!(entries.len(), 2);
            assert!(matches!(read.get("torn"), Value::Bool(false)));
            for (entry, body) in entries.iter().zip(&bodies) {
                assert_eq!(entry.text("kind"), Some("evidence"));
                assert_eq!(json::encode(entry.get("body")), json::encode(body));
            }
            // Chained in order, and the identities given back are theirs.
            assert_eq!(entries[1].text("previous"), Some(canonical::identity(&entries[0]).as_str()));
            assert_eq!(ids, entries.iter().map(canonical::identity).collect::<Vec<_>>());
            // The lock was released.
            assert!(!root.join("l/run.ledger.lock").exists());
            let _ = fs::remove_dir_all(&root);
        }

        #[test]
        fn a_torn_ending_is_cut_off_and_older_entries_keep_their_order() {
            let root = scratch("torn");
            let ledger = root.join("run.ledger");
            let path = ledger.to_str().unwrap();
            let first = crate::ledger::append_entries(path, "note", &[v(r#"{"n":1}"#)], Duration::ZERO).unwrap();
            let mut bytes = fs::read(&ledger).unwrap();
            bytes.extend_from_slice(b"dodona1 99 abc {\"previ");
            fs::write(&ledger, &bytes).unwrap();
            assert!(matches!(read_back(&ledger).get("torn"), Value::Bool(true)));
            record(&root, "run.ledger", OWNER, &[v(r#"{"n":2}"#), v(r#"{"n":3}"#)], Duration::ZERO).ok().unwrap();
            let read = read_back(&ledger);
            let entries = read.get("entries").array();
            assert!(matches!(read.get("torn"), Value::Bool(false)));
            assert_eq!(entries.len(), 3);
            assert_eq!(canonical::identity(&entries[0]), first[0]);
            assert_eq!(entries[0].text("kind"), Some("note"));
            assert_eq!(entries[1].text("previous"), Some(first[0].as_str()));
            let _ = fs::remove_dir_all(&root);
        }

        #[test]
        fn a_corrupt_ledger_is_not_written() {
            let root = scratch("corrupt");
            let ledger = root.join("run.ledger");
            fs::write(&ledger, b"garbage\n").unwrap();
            let got = record(&root, "run.ledger", OWNER, &[v("{}")], Duration::ZERO);
            assert_eq!(got.err().map(|s| s.reason), Some("ledger-not-written"));
            assert_eq!(fs::read(&ledger).unwrap(), b"garbage\n");
            assert!(!root.join("run.ledger.lock").exists());
            assert_eq!(
                crate::ledger::append_entries(ledger.to_str().unwrap(), "evidence", &[v("{}")], Duration::ZERO),
                Err(crate::ledger::NotWritten::Corrupt(1))
            );
            let _ = fs::remove_dir_all(&root);
        }

        #[test]
        fn a_lock_held_by_another_is_waited_for_and_left_alone() {
            let root = scratch("locked");
            let lock = root.join("run.ledger.lock");
            fs::write(&lock, b"").unwrap();
            let begun = Instant::now();
            let got = record(&root, "run.ledger", OWNER, &[v("{}")], Duration::from_millis(50));
            assert_eq!(got.err().map(|s| s.reason), Some("ledger-not-written"));
            assert!(begun.elapsed() >= Duration::from_millis(50));
            // Nothing written, and the other holder's lock still there.
            assert!(!root.join("run.ledger").exists());
            assert!(lock.exists());
            let _ = fs::remove_dir_all(&root);
        }

        /// A disk standing in for the ledger file, failing as it is told.
        struct Disk {
            data: Vec<u8>,
            /// An append writes only this many bytes and then fails.
            short_write: Option<usize>,
            /// How many syncs fail, from the first.
            failing_syncs: usize,
            /// Cutting the file fails once anything has been appended.
            cut_fails_after_write: bool,
            wrote: bool,
        }
        impl crate::ledger::LedgerFile for Disk {
            fn set_len(&mut self, len: u64) -> std::io::Result<()> {
                if self.wrote && self.cut_fails_after_write {
                    return Err(std::io::ErrorKind::Other.into());
                }
                self.data.truncate(len as usize);
                Ok(())
            }
            fn append(&mut self, bytes: &[u8]) -> std::io::Result<()> {
                self.wrote = true;
                match self.short_write {
                    Some(k) => {
                        self.data.extend_from_slice(&bytes[..k.min(bytes.len())]);
                        Err(std::io::ErrorKind::WriteZero.into())
                    }
                    None => {
                        self.data.extend_from_slice(bytes);
                        Ok(())
                    }
                }
            }
            fn sync(&mut self) -> std::io::Result<()> {
                if self.failing_syncs > 0 {
                    self.failing_syncs -= 1;
                    return Err(std::io::ErrorKind::Other.into());
                }
                Ok(())
            }
        }
        /// A ledger of one whole entry and a torn ending.
        fn disk() -> Disk {
            Disk {
                data: b"AAA\nTORN".to_vec(),
                short_write: None,
                failing_syncs: 0,
                cut_fails_after_write: false,
                wrote: false,
            }
        }
        const LINES: &[u8] = b"L1\nL2\n";

        #[test]
        fn a_write_that_fails_leaves_none_of_its_entries() {
            use crate::ledger::{write_lines, NotWritten};
            // Control: a write that succeeds cuts the torn ending and adds both lines.
            let mut ok = disk();
            assert_eq!(write_lines(&mut ok, 4, LINES), Ok(()));
            assert_eq!(ok.data, b"AAA\nL1\nL2\n");
            // A short write: cut back to the last whole entry before this append.
            let mut short = Disk { short_write: Some(4), ..disk() };
            assert!(matches!(write_lines(&mut short, 4, LINES), Err(NotWritten::Failed(_))));
            assert_eq!(short.data, b"AAA\n");
            // Everything written but the sync fails: cut back too, and synced.
            let mut unsynced = Disk { failing_syncs: 1, ..disk() };
            assert!(matches!(write_lines(&mut unsynced, 4, LINES), Err(NotWritten::Failed(_))));
            assert_eq!(unsynced.data, b"AAA\n");
            // Red: when cutting back fails too, a complete first entry of this
            // append stays, which is what the cut-back above prevents; and the
            // answer says the ledger's state is not known.
            let mut stuck = Disk { short_write: Some(4), cut_fails_after_write: true, ..disk() };
            assert!(matches!(write_lines(&mut stuck, 4, LINES), Err(NotWritten::Unconfirmed(_))));
            assert_eq!(stuck.data, b"AAA\nL1\nL");
            // And when the sync after cutting back fails, it is not confirmed either.
            let mut twice = Disk { failing_syncs: 2, ..disk() };
            assert!(matches!(write_lines(&mut twice, 4, LINES), Err(NotWritten::Unconfirmed(_))));
        }

        #[test]
        fn the_ledger_is_judged_again_once_its_lock_is_held() {
            use crate::ledger::{append_entries_if, NotWritten};
            let root = scratch("in-lock");
            let ledger = root.join("run.ledger");
            let path = ledger.to_str().unwrap().to_owned();
            let lock = format!("{path}.lock");
            // The check is asked while the lock is held.
            let asked_under_lock = std::cell::Cell::new(false);
            let ids = append_entries_if(&path, "evidence", &[v("{}")], Duration::ZERO, &|| {
                asked_under_lock.set(Path::new(&lock).exists());
                true
            });
            assert_eq!(ids.map(|i| i.len()), Ok(1));
            assert!(asked_under_lock.get());
            // A check that fails under the lock: nothing read or written, lock released.
            let before = fs::read(&ledger).unwrap();
            let refused = append_entries_if(&path, "evidence", &[v("{}")], Duration::ZERO, &|| false);
            assert_eq!(refused, Err(NotWritten::NotPermitted));
            assert_eq!(fs::read(&ledger).unwrap(), before);
            assert!(!Path::new(&lock).exists());
            // Through `record`: a run's ledger that is the owner's by name is refused under the lock.
            let got = record(&root, "run.ledger", "Run.Ledger", &[v("{}")], Duration::ZERO);
            assert_eq!(got.err().map(|s| s.reason), Some("ledger-not-written"));
            assert_eq!(fs::read(&ledger).unwrap(), before);
            let _ = fs::remove_dir_all(&root);
        }

        #[test]
        fn only_an_absent_or_regular_ledger_is_written() {
            let root = scratch("kinds");
            // Both absent, or both regular and distinct: permitted.
            assert!(still_permitted(&root, "l/run.ledger", OWNER));
            fs::create_dir_all(root.join("l")).unwrap();
            fs::create_dir_all(root.join("records")).unwrap();
            fs::write(root.join("l/run.ledger"), b"").unwrap();
            fs::write(root.join(OWNER), b"").unwrap();
            assert!(still_permitted(&root, "l/run.ledger", OWNER));
            // A folder where the run's ledger or the owner's should be: not.
            fs::create_dir_all(root.join("l/dir.ledger")).unwrap();
            assert!(!still_permitted(&root, "l/dir.ledger", OWNER));
            fs::create_dir_all(root.join("records/dir.ledger")).unwrap();
            assert!(!still_permitted(&root, "l/run.ledger", "records/dir.ledger"));
            // A file where a folder on the way should be: the walk finds it
            // before asking for the path beyond, on every system.
            fs::write(root.join("flat"), b"").unwrap();
            assert!(!still_permitted(&root, "flat/run.ledger", OWNER));
            assert!(!still_permitted(&root, "l/run.ledger", "flat/owner.ledger"));
            // A step that is plainly not there: nothing is there.
            assert!(still_permitted(&root, "new/deeper/run.ledger", OWNER));
            // Through `record`, a folder at the ledger's path is not written.
            let got = record(&root, "l/dir.ledger", OWNER, &[v("{}")], Duration::ZERO);
            assert_eq!(got.err().map(|s| s.reason), Some("ledger-not-written"));
            assert!(!root.join("l/dir.ledger.lock").exists());
            let _ = fs::remove_dir_all(&root);
        }

        #[cfg(unix)]
        #[test]
        fn an_owners_ledger_reached_through_a_link_stops_the_write() {
            // Status step 8 refuses an owner's ledger reached through a link
            // (`owner-ledger-link`), and step 14 would refuse after the write;
            // the run refuses before it instead.
            let root = scratch("owner-link");
            fs::write(root.join("elsewhere.ledger"), b"").unwrap();
            fs::create_dir_all(root.join("records")).unwrap();
            std::os::unix::fs::symlink(root.join("elsewhere.ledger"), root.join(OWNER)).unwrap();
            assert!(!still_permitted(&root, "l/run.ledger", OWNER));
            let _ = fs::remove_dir_all(&root);
        }

        #[test]
        fn shutdown_is_noted_only_when_it_was_written() {
            let recorder = Recorder::default();
            note_to(Some(&recorder), "provider", &v(r#"{"type":"request"}"#));
            note_to(Some(&recorder), "kernel", &v(r#"{"type":"result"}"#));
            note_shutdown(Some(&recorder), false);
            assert_eq!(recorder.borrow().len(), 2);
            note_shutdown(Some(&recorder), true);
            let kept = recorder.borrow();
            assert_eq!(kept.len(), 3);
            // In the order noted, the shutdown last, as sent.
            let to: Vec<&str> = kept.iter().map(|e| e.text("to").unwrap()).collect();
            assert_eq!(to, ["provider", "kernel", "provider"]);
            assert_eq!(kept[2].get("message").text("type"), Some("shutdown"));
            // With no recorder, nothing is kept and nothing fails.
            note_shutdown(None, true);
        }

        #[cfg(unix)]
        #[test]
        fn a_ledger_that_is_a_link_to_nothing_is_not_absent() {
            let root = scratch("dangling");
            std::os::unix::fs::symlink(root.join("nowhere"), root.join("run.ledger")).unwrap();
            assert!(!still_permitted(&root, "run.ledger", OWNER));
            let _ = fs::remove_dir_all(&root);
        }

        #[test]
        fn an_input_that_is_not_a_regular_file_is_unreadable() {
            let root = scratch("reread");
            fs::write(root.join("a.txt"), b"data").unwrap();
            fs::create_dir_all(root.join("folder")).unwrap();
            let mut now = reread(&root);
            assert_eq!(now("a.txt"), Some(file_identity(b"data")));
            assert_eq!(now("folder"), None);
            assert_eq!(now("missing"), None);
            let _ = fs::remove_dir_all(&root);
        }

        #[test]
        fn a_transcript_is_written_once_as_a_new_file() {
            let root = scratch("transcript");
            let said = vec![
                v(r#"{"to":"provider","message":{"type":"shutdown"}}"#),
                v(r#"{"to":"kernel","message":{"type":"manifest"}}"#),
            ];
            assert!(write_transcript(&root, "t.json", &said).is_ok());
            let kept = json::parse(&fs::read(root.join("t.json")).unwrap()).unwrap();
            assert_eq!(kept.array().len(), 2);
            assert_eq!(kept.array()[0].text("to"), Some("provider"));
            // Never over a file that is there; that file is left as it was.
            let again = write_transcript(&root, "t.json", &[]);
            assert_eq!(again.err().map(|s| s.reason), Some("transcript-not-written"));
            assert_eq!(json::parse(&fs::read(root.join("t.json")).unwrap()).unwrap().array().len(), 2);
            let _ = fs::remove_dir_all(&root);
        }

        #[cfg(unix)]
        #[test]
        fn a_transcript_now_behind_a_link_is_not_written() {
            let root = scratch("transcript-link");
            fs::create_dir_all(root.join("real")).unwrap();
            std::os::unix::fs::symlink(root.join("real"), root.join("lk")).unwrap();
            let got = write_transcript(&root, "lk/t.json", &[]);
            assert_eq!(got.err().map(|s| s.reason), Some("transcript-not-written"));
            assert!(!root.join("real/t.json").exists());
            let _ = fs::remove_dir_all(&root);
        }
    }

    #[cfg(test)]
    mod executor_tests {
        use super::*;
        use std::sync::atomic::{AtomicBool, Ordering as AtomicOrdering};
        use std::sync::{Arc, Mutex};

        /// Opened when the fake tree is ended, as ending a real tree closes
        /// the pipe ends its processes held: what waits on it is let go.
        #[derive(Clone)]
        struct Gate(Arc<(Mutex<bool>, std::sync::Condvar)>);
        impl Gate {
            fn new() -> Gate {
                Gate(Arc::new((Mutex::new(false), std::sync::Condvar::new())))
            }
            fn open(&self) {
                *self.0 .0.lock().unwrap() = true;
                self.0 .1.notify_all();
            }
            fn wait(&self) {
                let mut open = self.0 .0.lock().unwrap();
                while !*open {
                    open = self.0 .1.wait(open).unwrap();
                }
            }
        }
        /// A started executor, scripted: it exits at a set time, or never.
        struct Fake {
            exits: Option<(Instant, bool)>,
            ended: Arc<AtomicBool>,
            gate: Gate,
        }
        impl Started for Fake {
            fn exit_status(&mut self) -> Option<bool> {
                self.exits.filter(|(at, _)| Instant::now() >= *at).map(|(_, ok)| ok)
            }
            fn end_tree(&mut self) {
                self.ended.store(true, AtomicOrdering::SeqCst);
                self.gate.open();
            }
        }
        fn fake(exits: Option<(Duration, bool)>) -> (Fake, Arc<AtomicBool>, Gate) {
            let ended = Arc::new(AtomicBool::new(false));
            let gate = Gate::new();
            let f = Fake {
                exits: exits.map(|(after, ok)| (Instant::now() + after, ok)),
                ended: ended.clone(),
                gate: gate.clone(),
            };
            (f, ended, gate)
        }
        /// Output that gives some bytes and then does not end until the tree
        /// is ended: a process the executor started still holds it open.
        struct HeldOpen {
            first: Vec<u8>,
            gate: Gate,
        }
        impl IoRead for HeldOpen {
            fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
                if !self.first.is_empty() {
                    let n = self.first.len().min(buf.len());
                    buf[..n].copy_from_slice(&self.first[..n]);
                    self.first.drain(..n);
                    return Ok(n);
                }
                self.gate.wait();
                Ok(0)
            }
        }
        fn held_open(first: &[u8], gate: &Gate) -> Box<dyn IoRead + Send> {
            Box::new(HeldOpen { first: first.to_vec(), gate: gate.clone() })
        }
        /// Input nobody reads: a write blocks until the tree is ended, and then
        /// fails, as a write to a pipe whose reader is gone does.
        struct NeverRead(Gate);
        impl IoWrite for NeverRead {
            fn write(&mut self, _: &[u8]) -> std::io::Result<usize> {
                self.0.wait();
                Err(std::io::ErrorKind::BrokenPipe.into())
            }
            fn flush(&mut self) -> std::io::Result<()> {
                Ok(())
            }
        }
        /// Input whose reader is already gone: every write fails at once.
        struct Broken;
        impl IoWrite for Broken {
            fn write(&mut self, _: &[u8]) -> std::io::Result<usize> {
                Err(std::io::ErrorKind::BrokenPipe.into())
            }
            fn flush(&mut self) -> std::io::Result<()> {
                Ok(())
            }
        }
        fn writer(w: impl IoWrite + Send + 'static) -> Option<Box<dyn IoWrite + Send>> {
            Some(Box::new(w))
        }
        fn kept() -> (Option<Box<dyn IoWrite + Send>>, Arc<Mutex<Vec<u8>>>) {
            let bytes = Arc::new(Mutex::new(Vec::new()));
            (writer(Kept(bytes.clone())), bytes)
        }
        const ANSWER: &[u8] = b"{\"ended\":true,\"reports\":[]}\n";
        /// The batch, with whether every worker was joined in the reap limit.
        fn awaited(
            f: &mut Fake,
            stdin: Option<Box<dyn IoWrite + Send>>,
            stdout: Box<dyn IoRead + Send>,
            input: &[u8],
            until: Instant,
        ) -> (String, bool) {
            let (b, joined) = await_batch_reaped(f, stdin, stdout, input.to_vec(), until, REAP_LIMIT);
            (kind(&b), joined)
        }
        /// Input that keeps what it is given.
        struct Kept(Arc<Mutex<Vec<u8>>>);
        impl IoWrite for Kept {
            fn write(&mut self, b: &[u8]) -> std::io::Result<usize> {
                self.0.lock().unwrap().extend_from_slice(b);
                Ok(b.len())
            }
            fn flush(&mut self) -> std::io::Result<()> {
                Ok(())
            }
        }
        /// A reader that gives one byte at a time, so a line feed can fall anywhere.
        struct Trickle(std::io::Cursor<Vec<u8>>);
        impl IoRead for Trickle {
            fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
                let n = 1.min(buf.len());
                self.0.read(&mut buf[..n])
            }
        }
        fn out(bytes: &[u8]) -> Box<dyn IoRead + Send> {
            Box::new(std::io::Cursor::new(bytes.to_vec()))
        }
        fn soon() -> Instant {
            Instant::now() + Duration::from_millis(300)
        }
        fn kind(b: &Batch) -> String {
            match b {
                Batch::Failed => "failed".into(),
                Batch::TimedOut => "timed-out".into(),
                Batch::Answered(v) => json::encode(v),
            }
        }

        #[test]
        fn the_first_line_is_kept_and_the_rest_is_drained_unread() {
            let text = b"{\"ended\":true,\"reports\":[]}\nnot json {{{ \xff\nmore";
            assert_eq!(first_line_of(&text[..]).as_deref(), Some(&b"{\"ended\":true,\"reports\":[]}"[..]));
            let trickled = first_line_of(Trickle(std::io::Cursor::new(text.to_vec())));
            assert_eq!(trickled.as_deref(), Some(&b"{\"ended\":true,\"reports\":[]}"[..]));
            // No line feed at all: no answer.
            assert_eq!(first_line_of(&b"{\"ended\":true}"[..]), None);
            // A first line of any length is kept whole.
            let long = format!("{{\"ended\":true,\"pad\":\"{}\"}}\n", "x".repeat(200_000));
            assert_eq!(first_line_of(long.as_bytes()).map(|l| l.len()), Some(long.len() - 1));
        }

        #[test]
        fn only_a_strict_object_line_after_a_clean_exit_is_an_answer() {
            fn judged(success: bool, line: &[u8]) -> String {
                kind(&judge_output(success, Some(line)))
            }
            let ok = br#"{"ended":true,"reports":[]}"#;
            assert_eq!(judged(true, ok), r#"{"ended":true,"reports":[]}"#);
            // An exit status other than 0, whatever was printed.
            assert_eq!(judged(false, ok), "failed");
            // No line, an empty line, a carriage return, a byte-order mark.
            assert_eq!(kind(&judge_output(true, None)), "failed");
            assert_eq!(judged(true, b""), "failed");
            assert_eq!(judged(true, b"{\"ended\":true,\"reports\":[]}\r"), "failed");
            assert_eq!(judged(true, b"\xEF\xBB\xBF{\"ended\":true,\"reports\":[]}"), "failed");
            // Read strictly: a key twice, a fraction, not an object, not UTF-8.
            assert_eq!(judged(true, br#"{"ended":true,"ended":true,"reports":[]}"#), "failed");
            assert_eq!(judged(true, br#"{"ended":true,"reports":[],"n":1.0}"#), "failed");
            assert_eq!(judged(true, b"[]"), "failed");
            assert_eq!(judged(true, b"{\"a\":\"\xff\"}"), "failed");
        }

        #[test]
        fn a_batch_ends_when_its_input_is_written_the_executor_exits_and_its_output_ends() {
            // Trailing output after the answer is drained, not read.
            let (mut f, ended, _) = fake(Some((Duration::ZERO, true)));
            let (stdin, given) = kept();
            let (b, joined) = awaited(
                &mut f,
                stdin,
                out(b"{\"ended\":true,\"reports\":[]}\ntrailing, not json\n"),
                b"{\"runs\":[]}",
                soon(),
            );
            assert_eq!(b, r#"{"ended":true,"reports":[]}"#);
            // The receipt came before the answer counted, so the input is all there.
            assert_eq!(given.lock().unwrap().as_slice(), b"{\"runs\":[]}");
            assert!(ended.load(AtomicOrdering::SeqCst));
            assert!(joined);
        }

        #[test]
        fn an_answer_does_not_count_while_the_input_is_still_being_written() {
            // The executor exits 0 and its output ends with a good answer, but
            // the write of its input has not completed: no answer, and when the
            // deadline passes the batch is an error; ending the tree lets the
            // blocked writer go, and it is joined.
            let (mut f, ended, gate) = fake(Some((Duration::ZERO, true)));
            let (b, joined) = awaited(&mut f, writer(NeverRead(gate)), out(ANSWER), &[b'x'; 64], soon());
            assert_eq!(b, "timed-out");
            assert!(ended.load(AtomicOrdering::SeqCst));
            assert!(joined);
        }

        #[test]
        fn a_failed_write_is_not_an_answer() {
            let (mut f, ended, _) = fake(Some((Duration::ZERO, true)));
            let (b, joined) = awaited(&mut f, writer(Broken), out(ANSWER), b"{\"runs\":[]}", soon());
            assert_eq!(b, "failed");
            assert!(ended.load(AtomicOrdering::SeqCst) && joined);
            // No way to give the input at all is the same.
            let (mut f, _, _) = fake(Some((Duration::ZERO, true)));
            assert_eq!(awaited(&mut f, None, out(ANSWER), b"{}", soon()).0, "failed");
            assert!(matches!(fates(&Batch::Failed, &["k".to_owned()])[0], Fate::Verdict("unavailable")));
        }

        #[test]
        fn a_completion_first_seen_after_the_deadline_does_not_count() {
            // Everything is ready, but the deadline has already passed when it
            // is first looked at.
            let (mut f, ended, _) = fake(Some((Duration::ZERO, true)));
            let (stdin, _) = kept();
            let past = Instant::now();
            std::thread::sleep(Duration::from_millis(20));
            let (b, joined) = awaited(&mut f, stdin, out(ANSWER), b"{}", past);
            assert_eq!(b, "timed-out");
            assert!(ended.load(AtomicOrdering::SeqCst) && joined);
        }

        #[test]
        fn an_exit_status_other_than_0_is_unavailable() {
            let (mut f, ended, _) = fake(Some((Duration::ZERO, false)));
            let (stdin, _) = kept();
            let (b, joined) = awaited(&mut f, stdin, out(ANSWER), b"{}", soon());
            assert_eq!(b, "failed");
            assert!(ended.load(AtomicOrdering::SeqCst) && joined);
        }

        #[test]
        fn an_executor_that_does_not_exit_in_time_is_an_error_for_the_batch() {
            let (mut f, ended, _) = fake(None);
            let (stdin, _) = kept();
            let (b, joined) = awaited(&mut f, stdin, out(ANSWER), b"{}", soon());
            assert_eq!(b, "timed-out");
            assert!(ended.load(AtomicOrdering::SeqCst) && joined);
            assert!(matches!(fates(&Batch::TimedOut, &["k".to_owned()])[0], Fate::Verdict("error")));
        }

        #[test]
        fn a_process_left_holding_the_output_keeps_the_batch_waiting_until_the_deadline() {
            // The executor has exited with 0, its input was written and it
            // printed a good answer, but a process it started holds its output
            // open: no end of output by the deadline, so the batch is an error.
            // Ending the tree closes the output, and the reader is joined.
            let (mut f, ended, gate) = fake(Some((Duration::ZERO, true)));
            let (stdin, _) = kept();
            let begun = Instant::now();
            let (b, joined) = awaited(&mut f, stdin, held_open(ANSWER, &gate), b"{}", soon());
            assert_eq!(b, "timed-out");
            assert!(begun.elapsed() >= Duration::from_millis(250));
            assert!(ended.load(AtomicOrdering::SeqCst) && joined);
        }

        #[test]
        fn an_executor_that_never_reads_its_input_cannot_hold_the_batch() {
            let (mut f, ended, gate) = fake(None);
            let (b, joined) = awaited(
                &mut f,
                writer(NeverRead(gate.clone())),
                held_open(b"", &gate),
                &vec![b'x'; 1 << 20],
                soon(),
            );
            assert_eq!(b, "timed-out");
            assert!(ended.load(AtomicOrdering::SeqCst) && joined);
        }

        #[test]
        fn a_worker_kept_blocked_by_an_escaped_process_is_not_waited_for_without_end() {
            // A gate nobody opens: a process outside the tree holds the pipe.
            // The batch still ends at its deadline, and the reap gives up after
            // its limit rather than waiting for ever.
            let (mut f, _, _) = fake(None);
            let escaped = Gate::new();
            let begun = Instant::now();
            let (b, joined) = await_batch_reaped(
                &mut f,
                writer(Kept(Arc::new(Mutex::new(Vec::new())))),
                held_open(b"", &escaped),
                b"{}".to_vec(),
                Instant::now() + Duration::from_millis(50),
                Duration::from_millis(100),
            );
            assert_eq!(kind(&b), "timed-out");
            assert!(!joined);
            assert!(begun.elapsed() < Duration::from_secs(2));
            // Let the one worker this test leaves go, so it does not outlive the test.
            escaped.open();
        }

        #[test]
        fn an_executor_that_cannot_start_is_unavailable() {
            let empty: [String; 0] = [];
            let mut none = Native { command: &empty, root: Path::new(".") };
            let b = none.batch(&json::object(vec![("runs", Value::Array(vec![]))]), Duration::from_millis(100));
            assert_eq!(kind(&b), "failed");
        }
    }

    #[cfg(test)]
    mod check_tests {
        use super::*;

        /// A provider's side of a session, scripted: what it was sent, and what it answers.
        struct Scripted {
            ids: RequestIds,
            sent: Vec<Value>,
            replies: Vec<Result<Value, &'static str>>,
        }
        impl Scripted {
            /// A session on which `obligation.enumerate` has already used id "1".
            fn after_enumerate(replies: Vec<Result<Value, &'static str>>) -> Scripted {
                let mut ids = RequestIds::new();
                ids.take();
                Scripted { ids, sent: vec![], replies: replies.into_iter().rev().collect() }
            }
        }
        impl Channel for Scripted {
            fn send_check(&mut self, body: Value) -> Result<String, &'static str> {
                let id = self.ids.take();
                self.sent.push(json::object(vec![("id", json::string(&id)), ("body", body)]));
                Ok(id)
            }
            fn read(&mut self) -> Result<Value, &'static str> {
                self.replies.pop().unwrap_or(Err("closed"))
            }
        }

        const A: &str = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        const C: &str = "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";

        fn v(s: &str) -> Value {
            json::parse(s.as_bytes()).unwrap()
        }
        /// The site's platform as given: more than os and arch, in no canonical order.
        fn platform() -> Value {
            v(r#"{"os":"linux","emulated_on":"aarch64","arch":"x86_64","libc":"musl"}"#)
        }
        fn checkable(binding: &str, name: &str) -> Checkable {
            Checkable {
                binding: binding.to_owned(),
                name: name.to_owned(),
                obligation: v(&format!(
                    r#"{{"binding":"{binding}","name":"{name}","kind":"k","specified_by":["a.txt"],"targets":[],"expect":"holds","config":{{}}}}"#
                )),
                inputs: vec![("a.txt".to_owned(), A.to_owned())],
                tools: v(&format!(r#"[{{"name":"checker","version":"2.1","digest":"{C}"}}]"#)),
                platform: platform(),
                preimage: Value::Object(vec![]),
            }
        }
        fn declared() -> Vec<String> {
            vec!["checker".to_owned()]
        }
        fn ceiling() -> host::Ceiling {
            Some(("model".to_owned(), "bounded".to_owned()))
        }
        fn reply(id: &str, body: &str) -> Result<Value, &'static str> {
            Ok(v(&format!(
                r#"{{"type":"result","id":"{id}","capability":"obligation.check","body":{body}}}"#
            )))
        }
        /// A run every host rule accepts, on the platform written in another order.
        fn good_run() -> String {
            format!(
                r#"{{"program":{{"tool":"checker","path":"bin/checker"}},"args":["a.txt"],
                   "inputs":[{{"path":"a.txt","identity":"{A}"}}],"outputs":[],
                   "platform":{{"libc":"musl","arch":"x86_64","emulated_on":"aarch64","os":"linux"}},
                   "tools":[{{"name":"checker","digest":"{C}"}}]}}"#
            )
        }

        #[test]
        fn a_start_carries_the_platform_and_tools_as_given() {
            let mut ch = Scripted::after_enumerate(vec![]);
            let check = start(&mut ch, &checkable("t.check", "o1"), &declared(), &ceiling()).unwrap();
            // The first check on the session that enumerated is its request "2".
            assert_eq!(check.start_id, "2");
            let body = ch.sent[0].get("body");
            assert_eq!(body.text("op"), Some("start"));
            // The whole platform, libc and emulated_on included, with the same identity.
            let sent = body.get("platform");
            assert_eq!(sent.text("libc"), Some("musl"));
            assert_eq!(sent.text("emulated_on"), Some("aarch64"));
            assert_eq!(canonical::identity(sent), canonical::identity(&platform()));
            // The tool with its version; the obligation with its binding and no inputs.
            assert_eq!(body.get("tools").array()[0].text("version"), Some("2.1"));
            assert_eq!(body.get("obligation").text("binding"), Some("t.check"));
            assert!(body.get("obligation").opt("inputs").is_none());
        }

        #[test]
        fn two_bindings_number_their_requests_apart() {
            let mut a = Scripted::after_enumerate(vec![]);
            let mut b = Scripted::after_enumerate(vec![]);
            let first = start(&mut a, &checkable("a.check", "o1"), &declared(), &ceiling()).unwrap();
            let second = start(&mut a, &checkable("a.check", "o2"), &declared(), &ceiling()).unwrap();
            let other = start(&mut b, &checkable("b.check", "o3"), &declared(), &ceiling()).unwrap();
            assert_eq!((first.start_id.as_str(), second.start_id.as_str()), ("2", "3"));
            assert_eq!(other.start_id, "2");
            assert_eq!((a.sent.len(), b.sent.len()), (2, 1));
            assert_eq!(other.binding, "b.check");
        }

        #[test]
        fn a_run_is_numbered_keyed_and_judged_by_the_host_rules() {
            let mut ch = Scripted::after_enumerate(vec![reply("2", &format!(r#"{{"next":{}}}"#, good_run()))]);
            let mut check = start(&mut ch, &checkable("t.check", "o1"), &declared(), &ceiling()).unwrap();
            match answer(&mut ch, &mut check, Path::new(".")).unwrap() {
                Answer::Run { number, run_key, run } => {
                    assert_eq!(number, 1);
                    let started = ch.sent[0].get("body");
                    let key = host::run_key(started.get("obligation"), started.get("inputs"), 1, &run);
                    assert_eq!(run_key, key);
                }
                other => panic!("{other:?}"),
            }
            // The report goes back under the session's next id, naming the start.
            pass_back(&mut ch, &mut check, 1, Value::Object(vec![])).unwrap();
            let sent = &ch.sent[1];
            assert_eq!(sent.text("id"), Some("3"));
            assert_eq!(sent.get("body").text("check"), Some("2"));
            assert_eq!(check.awaited, "3");
        }

        #[test]
        fn a_final_after_a_run_gives_its_verdict() {
            let fin = r#"{"final":{"verdict":"passed","strength":{"class":"model","rank":"bounded"}}}"#;
            let mut ch = Scripted::after_enumerate(vec![
                reply("2", &format!(r#"{{"next":{}}}"#, good_run())),
                reply("3", fin),
            ]);
            let mut check = start(&mut ch, &checkable("t.check", "o1"), &declared(), &ceiling()).unwrap();
            assert!(matches!(answer(&mut ch, &mut check, Path::new(".")), Ok(Answer::Run { .. })));
            pass_back(&mut ch, &mut check, 1, Value::Object(vec![])).unwrap();
            // The verdict keeps the strength the rules bounded, for step 13 to record.
            let strength = v(r#"{"class":"model","rank":"bounded"}"#);
            assert_eq!(
                answer(&mut ch, &mut check, Path::new(".")),
                Ok(Answer::Verdict { verdict: "passed".into(), strength })
            );
        }

        #[test]
        fn the_strength_kept_is_the_one_the_rules_accepted() {
            let after_one_run = |fin: &str| {
                let mut ch = Scripted::after_enumerate(vec![
                    reply("2", &format!(r#"{{"next":{}}}"#, good_run())),
                    reply("3", fin),
                ]);
                let mut check = start(&mut ch, &checkable("t", "o1"), &declared(), &ceiling()).unwrap();
                answer(&mut ch, &mut check, Path::new(".")).unwrap();
                pass_back(&mut ch, &mut check, 1, Value::Object(vec![])).unwrap();
                answer(&mut ch, &mut check, Path::new("."))
            };
            // A rank below the ceiling is kept exactly, fields the rules do not read included.
            let lower = r#"{"final":{"verdict":"failed","strength":{"class":"model","rank":"sampled","note":"n"}}}"#;
            match after_one_run(lower) {
                Ok(Answer::Verdict { verdict, strength }) => {
                    assert_eq!(verdict, "failed");
                    assert_eq!(strength.text("rank"), Some("sampled"));
                    assert_eq!(strength.text("class"), Some("model"));
                    assert_eq!(strength.text("note"), Some("n"));
                }
                other => panic!("{other:?}"),
            }
            // A strength the rules refuse gives no verdict, so none is kept.
            let above = r#"{"final":{"verdict":"passed","strength":{"class":"model","rank":"exhaustive"}}}"#;
            assert_eq!(after_one_run(above), Ok(Answer::Refused("strength-above-ceiling")));
            let other_class = r#"{"final":{"verdict":"passed","strength":{"class":"test","rank":"bounded"}}}"#;
            assert_eq!(after_one_run(other_class), Ok(Answer::Refused("strength-class-mismatch")));
            // A verdict that is never recorded may come with no strength.
            let error = r#"{"final":{"verdict":"error"}}"#;
            assert_eq!(
                after_one_run(error),
                Ok(Answer::Verdict { verdict: "error".into(), strength: Value::Null })
            );
        }

        #[test]
        fn a_rule_broken_by_a_check_refuses_that_check_only() {
            let refused = |body: &str| {
                let mut ch = Scripted::after_enumerate(vec![reply("2", body)]);
                let mut check = start(&mut ch, &checkable("t", "o1"), &declared(), &ceiling()).unwrap();
                answer(&mut ch, &mut check, Path::new("."))
            };
            assert_eq!(refused("{}"), Ok(Answer::Refused("neither-or-both")));
            let both = format!(r#"{{"next":{},"final":{{"verdict":"passed"}}}}"#, good_run());
            assert_eq!(refused(&both), Ok(Answer::Refused("neither-or-both")));
            let fin = r#"{"final":{"verdict":"passed","strength":{"class":"model","rank":"bounded"}}}"#;
            assert_eq!(refused(fin), Ok(Answer::Refused("verdict-without-run")));
            let other_platform = good_run().replace(r#""libc":"musl","#, "");
            assert_eq!(
                refused(&format!(r#"{{"next":{other_platform}}}"#)),
                Ok(Answer::Refused("platform-mismatch"))
            );
            for reason in ["neither-or-both", "verdict-without-run", "platform-mismatch"] {
                assert!(!SESSION_BROKE.contains(&reason));
            }
        }

        #[test]
        fn a_broken_session_refuses_the_whole_run() {
            let broke = |r: Result<Value, &'static str>| {
                let mut ch = Scripted::after_enumerate(vec![r]);
                let mut check = start(&mut ch, &checkable("t", "o1"), &declared(), &ceiling()).unwrap();
                answer(&mut ch, &mut check, Path::new("."))
            };
            // The connection ends, or a line is no message.
            assert_eq!(broke(Err("closed")), Err("closed"));
            assert_eq!(broke(Err("malformed")), Err("malformed"));
            // An answer to another request, an error, or no object body.
            assert_eq!(broke(reply("1", r#"{"final":{}}"#)), Err("wrong-id"));
            let error = v(r#"{"type":"error","id":"2","error":{"code":"x","message":"m"}}"#);
            assert_eq!(broke(Ok(error)), Err("provider-error"));
            assert_eq!(broke(reply("2", "[]")), Err("unexpected"));
            let other = v(r#"{"type":"result","id":"2","capability":"obligation.enumerate","body":{}}"#);
            assert_eq!(broke(Ok(other)), Err("wrong-capability"));
            for reason in ["closed", "malformed", "wrong-id", "provider-error", "unexpected", "wrong-capability"] {
                assert!(SESSION_BROKE.contains(&reason), "{reason}");
            }
        }

        #[test]
        fn only_an_offered_check_is_asked() {
            // A binding that lists only enumeration has no kept session; a
            // manifest that does not offer the check gets none sent.
            assert!(can_check(Some(true)));
            assert!(!can_check(Some(false)));
            assert!(!can_check(None));
        }

        // The scheduler, with a scripted executor: no process is started.

        struct FakeExecutor {
            /// Every batch it was given, in order.
            sent: Vec<Value>,
            waits: Vec<Duration>,
            /// What it does with each batch in turn; once these run out, it
            /// answers every run with a report of a run that exited as described.
            scripted: Vec<Batch>,
        }
        impl FakeExecutor {
            fn new(scripted: Vec<Batch>) -> FakeExecutor {
                FakeExecutor { sent: vec![], waits: vec![], scripted }
            }
        }
        fn report_for(run: &Value) -> Value {
            json::object(vec![
                ("end", json::string("exited")),
                ("platform", run.get("platform").clone()),
                ("tools_ran", run.get("tools").clone()),
            ])
        }
        /// An ended batch with a good report for each run whose position `keep` allows.
        fn answered(runs: &Value, keep: impl Fn(usize) -> bool) -> Batch {
            let reports = runs
                .get("runs")
                .array()
                .iter()
                .enumerate()
                .filter(|(i, _)| keep(*i))
                .map(|(_, r)| {
                    json::object(vec![
                        ("run_key", r.get("run_key").clone()),
                        ("report", report_for(r.get("run"))),
                    ])
                })
                .collect();
            Batch::Answered(json::object(vec![
                ("ended", Value::Bool(true)),
                ("reports", Value::Array(reports)),
            ]))
        }
        impl Executor for FakeExecutor {
            fn batch(&mut self, runs: &Value, wait: Duration) -> Batch {
                self.sent.push(runs.clone());
                self.waits.push(wait);
                if self.scripted.is_empty() {
                    answered(runs, |_| true)
                } else {
                    self.scripted.remove(0)
                }
            }
        }
        fn lane<'a>(binding: &str, ch: &'a mut Scripted) -> Lane<'a> {
            Lane {
                binding: binding.to_owned(),
                channel: ch,
                offers_check: true,
                declared: declared(),
                ceiling: ceiling(),
            }
        }
        fn pair(b: &str, n: &str) -> (String, String) {
            (b.to_owned(), n.to_owned())
        }
        fn next() -> String {
            format!(r#"{{"next":{}}}"#, good_run())
        }
        const PASS: &str = r#"{"final":{"verdict":"passed","strength":{"class":"model","rank":"bounded"}}}"#;
        const FAIL: &str = r#"{"final":{"verdict":"failed","strength":{"class":"model","rank":"sampled"}}}"#;
        fn verdict(f: &Finished) -> (&str, Option<&str>) {
            match &f.ended {
                Ended::Verdict { verdict, strength } => (verdict.as_str(), strength.text("rank")),
                Ended::Refused(r) => (*r, None),
            }
        }
        fn runs_of(batch: &Value) -> Vec<(i64, String)> {
            batch
                .get("runs")
                .array()
                .iter()
                .map(|r| (r.get("number").number(), r.get("run_key").str().to_owned()))
                .collect()
        }

        #[test]
        fn the_site_can_extend_the_batch_wait_without_changing_the_run() {
            let no_limit = v(&good_run());
            let Value::Object(mut fields) = no_limit.clone() else { panic!("the run fixture must be an object") };
            fields.push(("limits".to_owned(), v(r#"{"wall_ms":1800000}"#)));
            let limited = Value::Object(fields);
            let long = Duration::from_secs(3660);
            for (run, floor, expected) in [
                (&limited, long, long),
                (&limited, Duration::from_millis(1), Duration::from_secs(1860)),
                (&no_limit, long, Duration::from_secs(86400)),
            ] {
                let offered = format!(r#"{{"next":{}}}"#, json::encode(run));
                let mut channel = Scripted::after_enumerate(vec![reply("2", &offered), reply("3", PASS)]);
                let mut lanes = [lane("a", &mut channel)];
                let mut executor = FakeExecutor::new(vec![]);
                schedule(
                    &mut lanes,
                    &[pair("a", "o1")],
                    &[checkable("a", "o1")],
                    &mut executor,
                    Path::new("."),
                    floor,
                ).unwrap();
                assert_eq!(executor.waits, [expected]);
                let sent_run = executor.sent[0].get("runs").array()[0].get("run");
                assert_eq!(json::encode(sent_run), json::encode(run));
            }
        }

        #[test]
        fn two_bindings_share_batches_in_the_order_checks_were_started() {
            let mut a = Scripted::after_enumerate(vec![reply("2", &next()), reply("3", &next()), reply("4", FAIL)]);
            let mut b = Scripted::after_enumerate(vec![reply("2", &next()), reply("3", PASS)]);
            let mut ex = FakeExecutor::new(vec![]);
            let plan = [pair("a", "o1"), pair("b", "o2")];
            let checks = [checkable("a", "o1"), checkable("b", "o2")];
            let done = {
                let mut lanes = vec![lane("a", &mut a), lane("b", &mut b)];
                schedule(&mut lanes, &plan, &checks, &mut ex, Path::new("."), Duration::ZERO).unwrap()
            };
            // Batch 1 holds both first runs, a's before b's; batch 2 only a's second.
            assert_eq!(ex.sent.len(), 2);
            let first = runs_of(&ex.sent[0]);
            assert_eq!(first.iter().map(|r| r.0).collect::<Vec<_>>(), vec![1, 1]);
            let started = a.sent[0].get("body");
            let run = ex.sent[0].get("runs").array()[0].get("run");
            assert_eq!(first[0].1, host::run_key(started.get("obligation"), started.get("inputs"), 1, run));
            assert_ne!(first[0].1, first[1].1);
            assert_eq!(runs_of(&ex.sent[1]).iter().map(|r| r.0).collect::<Vec<_>>(), vec![2]);
            // Each provider got its own reports, naming its own start, under its own ids.
            let ids = |s: &Scripted| s.sent.iter().map(|m| m.text("id").unwrap().to_owned()).collect::<Vec<_>>();
            assert_eq!(ids(&a), vec!["2", "3", "4"]);
            assert_eq!(ids(&b), vec!["2", "3"]);
            assert!(a.sent[1..].iter().all(|m| m.get("body").text("check") == Some("2")));
            assert_eq!(a.sent[2].get("body").get("run").number(), 2);
            // The results, in plan order, with the strength the rules accepted.
            assert_eq!((done[0].name.as_str(), verdict(&done[0]), done[0].runs), ("o1", ("failed", Some("sampled")), 2));
            assert_eq!((done[1].name.as_str(), verdict(&done[1]), done[1].runs), ("o2", ("passed", Some("bounded")), 1));
        }

        #[test]
        fn a_batch_is_judged_whole_and_then_run_by_run() {
            let keys = ["k1".to_owned(), "k2".to_owned()];
            let named = |b: Batch| -> Vec<String> {
                fates(&b, &keys)
                    .into_iter()
                    .map(|f| match f {
                        Fate::Verdict(v) => v.to_owned(),
                        Fate::Report(_) => "report".to_owned(),
                    })
                    .collect()
            };
            let answer = |s: &str| Batch::Answered(v(s));
            assert_eq!(named(Batch::TimedOut), ["error", "error"]);
            assert_eq!(named(Batch::Failed), ["unavailable", "unavailable"]);
            assert_eq!(named(answer(r#"{"ended":false,"reports":[]}"#)), ["unavailable", "unavailable"]);
            assert_eq!(named(answer(r#"{"ended":true}"#)), ["unavailable", "unavailable"]);
            assert_eq!(named(answer(r#"{"ended":"true","reports":[]}"#)), ["unavailable", "unavailable"]);
            // A malformed item, a key not of the batch, or one given twice: the whole batch.
            assert_eq!(named(answer(r#"{"ended":true,"reports":[1]}"#)), ["error", "error"]);
            assert_eq!(named(answer(r#"{"ended":true,"reports":[{"run_key":"k9","report":{}}]}"#)), ["error", "error"]);
            assert_eq!(named(answer(r#"{"ended":true,"reports":[{"run_key":"k1"}]}"#)), ["error", "error"]);
            let twice = r#"{"ended":true,"reports":[{"run_key":"k1","report":{}},{"run_key":"k1","report":{}}]}"#;
            assert_eq!(named(answer(twice)), ["error", "error"]);
            // A run with no report, or a report that is not an object: that run's check alone.
            assert_eq!(named(answer(r#"{"ended":true,"reports":[{"run_key":"k1","report":{}}]}"#)), ["report", "error"]);
            let not_object = r#"{"ended":true,"reports":[{"run_key":"k2","report":"x"},{"run_key":"k1","report":{}}]}"#;
            assert_eq!(named(answer(not_object)), ["report", "error"]);
        }

        #[test]
        fn a_missing_report_is_an_error_for_its_own_check_only() {
            let mut a = Scripted::after_enumerate(vec![reply("2", &next()), reply("3", PASS)]);
            let mut b = Scripted::after_enumerate(vec![reply("2", &next())]);
            /// An executor whose ended batch reports the first run only.
            struct FirstOnly;
            impl Executor for FirstOnly {
                fn batch(&mut self, runs: &Value, _wait: Duration) -> Batch {
                    answered(runs, |i| i == 0)
                }
            }
            let mut ex = FirstOnly;
            let plan = [pair("a", "o1"), pair("b", "o2")];
            let checks = [checkable("a", "o1"), checkable("b", "o2")];
            let done = {
                let mut lanes = vec![lane("a", &mut a), lane("b", &mut b)];
                schedule(&mut lanes, &plan, &checks, &mut ex, Path::new("."), Duration::ZERO).unwrap()
            };
            assert_eq!(verdict(&done[0]), ("passed", Some("bounded")));
            assert_eq!((verdict(&done[1]), done[1].runs), (("error", None), 1));
            // b's provider is never handed a report that did not come.
            assert_eq!(b.sent.len(), 1);
        }

        #[test]
        fn checks_refused_on_their_own_leave_the_run_going() {
            let mut not_offered = Scripted::after_enumerate(vec![]);
            let mut a = Scripted::after_enumerate(vec![reply("2", "{}"), reply("3", &next()), reply("4", PASS)]);
            let mut ex = FakeExecutor::new(vec![]);
            let plan = [pair("list", "o0"), pair("noffer", "o1"), pair("a", "o2"), pair("a", "o3")];
            let checks = [checkable("list", "o0"), checkable("noffer", "o1"), checkable("a", "o2"), checkable("a", "o3")];
            let done = {
                // "list" lists only enumeration, so it has no lane at all.
                let mut off = lane("noffer", &mut not_offered);
                off.offers_check = false;
                let mut lanes = vec![off, lane("a", &mut a)];
                schedule(&mut lanes, &plan, &checks, &mut ex, Path::new("."), Duration::ZERO).unwrap()
            };
            assert_eq!(verdict(&done[0]), ("not-offered", None));
            assert_eq!(verdict(&done[1]), ("not-offered", None));
            assert!(not_offered.sent.is_empty());
            assert_eq!(verdict(&done[2]), ("neither-or-both", None));
            assert_eq!(verdict(&done[3]), ("passed", Some("bounded")));
            assert_eq!(ex.sent.len(), 1);
        }

        #[test]
        fn a_session_that_breaks_refuses_the_whole_run_at_once() {
            let mut a = Scripted::after_enumerate(vec![reply("2", &next()), reply("9", PASS)]);
            let mut b = Scripted::after_enumerate(vec![reply("2", &next()), reply("3", PASS)]);
            let mut ex = FakeExecutor::new(vec![]);
            let plan = [pair("a", "o1"), pair("b", "o2")];
            let checks = [checkable("a", "o1"), checkable("b", "o2")];
            let got = {
                let mut lanes = vec![lane("a", &mut a), lane("b", &mut b)];
                schedule(&mut lanes, &plan, &checks, &mut ex, Path::new("."), Duration::ZERO).map(|_| ())
            };
            assert_eq!(got, Err("wrong-id"));
            // Nothing more is sent once a session has broken: b never gets its report.
            assert_eq!(b.sent.len(), 1);
        }

        #[test]
        fn a_check_gets_at_most_eight_runs() {
            let replies = (2..=10).map(|id| reply(&id.to_string(), &next())).collect();
            let mut a = Scripted::after_enumerate(replies);
            let mut ex = FakeExecutor::new(vec![]);
            let done = {
                let mut lanes = vec![lane("a", &mut a)];
                schedule(&mut lanes, &[pair("a", "o1")], &[checkable("a", "o1")], &mut ex, Path::new("."), Duration::ZERO).unwrap()
            };
            assert_eq!(ex.sent.len(), 8);
            assert_eq!((verdict(&done[0]), done[0].runs), (("too-many-runs", None), 8));
        }

        // Steps 11 to 14 composed, with the executor and the re-reading of inputs
        // injected; the ledgers are real files under a folder of the test's own.

        fn scratch_root(name: &str) -> PathBuf {
            let dir = std::env::temp_dir().join(format!("dodona-compose-{}-{name}", std::process::id()));
            let _ = fs::remove_dir_all(&dir);
            fs::create_dir_all(&dir).unwrap();
            dir
        }
        fn run_input_at(root: &Path, ledgers: &[&str], ledger: &str) -> RunInput {
            let site = v(r#"{"platform":{"os":"linux","arch":"x86_64"},"writer":"w","runner":"r","tools":[],"providers":{},"deadline_ms":1000}"#);
            let policy = v(r#"{"required":[],"min_hard_gates":1,"floors":{},"not_applied":[]}"#);
            let input = json::object(vec![
                ("root", json::string(root.to_str().unwrap())),
                ("project", json::string("dodona.toml")),
                ("site", site),
                ("policy", policy),
                ("policy_source", json::string("test")),
                ("ledgers", Value::Array(ledgers.iter().map(|l| json::string(l)).collect())),
                ("owner_ledger", json::string("records/owner.ledger")),
                ("ledger", json::string(ledger)),
                ("executor", Value::Array(vec![json::string("x")])),
            ]);
            match read(json::encode(&input).as_bytes()) {
                Ok(r) => r,
                Err(s) => panic!("refused: {} {}", s.reason, s.detail),
            }
        }
        fn two_checks() -> (Plan, [Checkable; 2]) {
            let plan = Plan {
                to_check: vec![pair("a", "o1"), pair("b", "o2")],
                reused: vec![pair("a", "o0")],
                obligations: 3,
                not_checkable: 0,
            };
            (plan, [checkable("a", "o1"), checkable("b", "o2")])
        }
        /// Two bindings' sessions, each taking its check through one run to a final.
        fn two_sessions() -> (Scripted, Scripted) {
            (
                Scripted::after_enumerate(vec![reply("2", &next()), reply("3", PASS)]),
                Scripted::after_enumerate(vec![reply("2", &next()), reply("3", FAIL)]),
            )
        }
        fn finished_with(
            run: &RunInput,
            identity_of: &mut dyn FnMut(&str) -> Option<String>,
        ) -> (Step<Vec<Finished>>, Plan) {
            let (plan, checks) = two_checks();
            let (mut a, mut b) = two_sessions();
            let mut ex = FakeExecutor::new(vec![]);
            let mut lanes = vec![lane("a", &mut a), lane("b", &mut b)];
            let done = finish(run, &plan, &checks, &mut lanes, &mut ex, identity_of);
            (done, plan)
        }
        fn unchanged(path: &str) -> Option<String> {
            (path == "a.txt").then(|| A.to_owned())
        }
        fn entries_in(root: &Path, rel: &str) -> Vec<Value> {
            let asked = json::object(vec![("ledger", json::string(root.join(rel).to_str().unwrap()))]);
            crate::ledger::read(&asked).unwrap().get("entries").array().to_vec()
        }

        #[test]
        fn a_run_records_its_verdicts_and_its_counts_add_up() {
            let root = scratch_root("two");
            let run = run_input_at(&root, &["l/run.ledger"], "l/run.ledger");
            let (done, plan) = finished_with(&run, &mut unchanged);
            let done = match done {
                Ok(d) => d,
                Err(s) => panic!("refused: {} {}", s.reason, s.detail),
            };
            let entries = entries_in(&root, "l/run.ledger");
            let recorded: Vec<(&str, &str)> = entries
                .iter()
                .map(|e| (e.get("body").text("obligation").unwrap(), e.get("body").text("verdict").unwrap()))
                .collect();
            assert_eq!(recorded, [("o1", "passed"), ("o2", "failed")]);
            assert_eq!(entries[0].get("body").text("platform"), Some("linux/x86_64"));
            assert_eq!(entries[0].get("body").text("writer"), Some("w"));
            let c = counts(&plan, &done);
            let n = |k: &str| c.get(k).number();
            assert_eq!((n("obligations"), n("reused"), n("checked")), (3, 1, 2));
            assert_eq!((n("passed"), n("failed"), n("refused")), (1, 1, 0));
            assert_eq!(n("reused") + n("checked"), n("obligations"));
            let ended = ["passed", "failed", "error", "unavailable", "unsupported", "refused"];
            assert_eq!(ended.iter().map(|k| n(*k)).sum::<i64>(), n("checked"));
            let _ = fs::remove_dir_all(&root);
        }

        #[test]
        fn an_input_changed_before_recording_is_counted_as_an_error_and_nothing_is_written() {
            let root = scratch_root("changed");
            let run = run_input_at(&root, &["l/run.ledger"], "l/run.ledger");
            let mut changed = |_: &str| Some("sha256:changed".to_owned());
            let (done, plan) = finished_with(&run, &mut changed);
            let done = done.ok().unwrap();
            let c = counts(&plan, &done);
            assert_eq!((c.get("error").number(), c.get("passed").number(), c.get("failed").number()), (2, 0, 0));
            // Nothing to record: not the ledger, not its folder.
            assert!(!root.join("l").exists());
            let _ = fs::remove_dir_all(&root);
        }

        #[cfg(any(unix, windows))]
        #[test]
        fn a_ledger_that_has_become_the_owners_is_not_written() {
            let root = scratch_root("owner");
            let run = run_input_at(&root, &["l/run.ledger"], "l/run.ledger");
            // After step 1, the run's ledger becomes another name for the owner's.
            fs::create_dir_all(root.join("records")).unwrap();
            fs::create_dir_all(root.join("l")).unwrap();
            fs::write(root.join("records/owner.ledger"), b"").unwrap();
            fs::hard_link(root.join("records/owner.ledger"), root.join("l/run.ledger")).unwrap();
            let (done, _) = finished_with(&run, &mut unchanged);
            assert_eq!(done.err().map(|s| s.reason), Some("ledger-not-written"));
            assert_eq!(fs::read(root.join("records/owner.ledger")).unwrap(), b"");
            assert!(!root.join("l/run.ledger.lock").exists());
            let _ = fs::remove_dir_all(&root);
        }

        #[cfg(unix)]
        #[test]
        fn a_ledger_now_reached_through_a_link_is_not_written() {
            let root = scratch_root("link");
            let run = run_input_at(&root, &["lk/run.ledger"], "lk/run.ledger");
            fs::create_dir_all(root.join("real")).unwrap();
            std::os::unix::fs::symlink(root.join("real"), root.join("lk")).unwrap();
            let (done, _) = finished_with(&run, &mut unchanged);
            assert_eq!(done.err().map(|s| s.reason), Some("ledger-not-written"));
            assert!(!root.join("real/run.ledger").exists());
            assert!(!root.join("real/run.ledger.lock").exists());
            let _ = fs::remove_dir_all(&root);
        }

        fn empty_snapshot() -> Snapshot {
            Snapshot {
                not_served: vec![],
                obligations: Obligations {
                    found: vec![],
                    listed: vec![],
                    not_checkable: vec![],
                    kept: vec![],
                    checks: vec![],
                },
                intents: Intents { judged: vec![], unread: false },
                read: Ledgers { entries: vec![], torn: false, absent: false },
                judged: v(r#"{"kind":"status","name":"this-project","self":{"writer":"w","platform":"linux/x86_64"},"policy":{"min_hard_gates":1,"required":[],"trusted_writers":[],"floors":{},"attestors":{},"makes":[]},"obligations":{},"intents":{},"steps":[]}"#),
                report: Value::Null,
            }
        }

        #[test]
        fn a_refusal_after_recording_keeps_what_was_appended() {
            let root = scratch_root("after");
            let run = run_input_at(&root, &["l/run.ledger", "l/other.ledger"], "l/run.ledger");
            let (done, _) = finished_with(&run, &mut unchanged);
            assert!(done.is_ok());
            // Another listed ledger turns out corrupt when step 14 reads them again.
            fs::write(root.join("l/other.ledger"), b"garbage\n").unwrap();
            let got = rejudge(&run.status, empty_snapshot());
            assert_eq!(got.err().map(|s| s.reason), Some("corrupt-ledger"));
            assert_eq!(entries_in(&root, "l/run.ledger").len(), 2);
            // Read again without it, the recorded entries are what is judged.
            fs::remove_file(root.join("l/other.ledger")).unwrap();
            let s = match rejudge(&run.status, empty_snapshot()) {
                Ok(s) => s,
                Err(e) => panic!("refused: {} {}", e.reason, e.detail),
            };
            assert_eq!(s.read.entries.len(), 2);
            assert!(s.read.absent);
            assert_eq!(s.judged.get("steps").array().len(), 3);
            assert!(s.report.opt("obligations").is_some());
            let _ = fs::remove_dir_all(&root);
        }

        #[test]
        fn a_transcript_that_cannot_be_written_leaves_the_verdicts_recorded() {
            let root = scratch_root("late-transcript");
            let run = run_input_at(&root, &["l/run.ledger"], "l/run.ledger");
            let (done, _) = finished_with(&run, &mut unchanged);
            assert!(done.is_ok());
            // The transcript's path is taken after step 1 checked it.
            fs::write(root.join("t.json"), b"someone else's").unwrap();
            let got = write_transcript(&root, "t.json", &[v(r#"{"to":"kernel","message":{}}"#)]);
            assert_eq!(got.err().map(|s| s.reason), Some("transcript-not-written"));
            // The verdicts stay recorded, and the other file is left as it was.
            assert_eq!(entries_in(&root, "l/run.ledger").len(), 2);
            assert_eq!(fs::read(root.join("t.json")).unwrap(), b"someone else's");
            let _ = fs::remove_dir_all(&root);
        }
    }

    #[cfg(test)]
    mod plan_tests {
        use super::*;

        fn pair(b: &str, n: &str) -> (String, String) {
            (b.to_owned(), n.to_owned())
        }

        /// A report giving each name its status, as the status rules write one.
        fn report(statuses: &[(&str, &str)]) -> Value {
            let obligations = statuses
                .iter()
                .map(|(n, s)| (n.to_string(), json::object(vec![("status", json::string(s))])))
                .collect();
            json::object(vec![("obligations", Value::Object(obligations))])
        }

        #[test]
        fn nothing_listed_plans_nothing() {
            // As in the cases where the executor is sent nothing.
            let p = plan(&[], &[], &report(&[]));
            assert!(p.to_check.is_empty() && p.reused.is_empty());
            assert_eq!((p.obligations, p.not_checkable), (0, 0));
        }

        #[test]
        fn current_results_are_reused_and_unknown_is_checked() {
            let listed = [
                pair("t.check", "o4"),
                pair("b", "o9"),
                pair("t.check", "o1"),
                pair("t.check", "o2"),
                pair("t.check", "o3"),
                pair("t.check", "o5"),
            ];
            let r = report(&[
                ("o1", "passed"),
                ("o2", "failed"),
                ("o3", "conflict"),
                ("o4", "unknown"),
                ("o9", "unknown"),
            ]);
            let p = plan(&listed, &["o5".to_owned()], &r);
            assert_eq!(p.reused, vec![pair("t.check", "o1"), pair("t.check", "o2"), pair("t.check", "o3")]);
            // Sorted by binding, then name; o5, absent from the report, is no current result.
            assert_eq!(p.to_check, vec![pair("b", "o9"), pair("t.check", "o4"), pair("t.check", "o5")]);
            assert_eq!(p.reused.len() + p.to_check.len(), p.obligations);
            // A name listed and rejected is checked as listed, and counted as not checkable.
            assert_eq!((p.obligations, p.not_checkable), (6, 1));
        }

        #[test]
        fn a_planted_selection_is_caught() {
            // Two wrong readings of "current": only `passed`, or anything not
            // `failed`. Each misplaces an obligation the test above places.
            let r = report(&[("o1", "passed"), ("o2", "failed"), ("o3", "conflict"), ("o4", "unknown")]);
            let listed = [pair("t", "o1"), pair("t", "o2"), pair("t", "o3"), pair("t", "o4")];
            let right = plan(&listed, &[], &r).to_check;
            let only_passed: Vec<_> = listed
                .iter()
                .filter(|(_, n)| r.get("obligations").get(n).text("status") != Some("passed"))
                .cloned()
                .collect();
            let not_failed: Vec<_> = listed
                .iter()
                .filter(|(_, n)| r.get("obligations").get(n).text("status") == Some("failed"))
                .cloned()
                .collect();
            assert_eq!(right, vec![pair("t", "o4")]);
            assert_ne!(right, only_passed);
            assert_ne!(right, not_failed);
        }

        #[test]
        fn an_empty_ledger_plans_every_listed_obligation() {
            // The real status rules on a scenario with no ledger entries:
            // every obligation is unknown, never-run, so every one is checked.
            let judged = json::object(vec![
                ("kind", json::string("status")),
                ("name", json::string("this-project")),
                (
                    "self",
                    json::object(vec![
                        ("writer", json::string("w")),
                        ("platform", json::string("linux/x86_64")),
                    ]),
                ),
                (
                    "policy",
                    json::object(vec![
                        ("min_hard_gates", Value::Number(1)),
                        ("required", Value::Array(vec![])),
                        ("trusted_writers", Value::Array(vec![])),
                        ("floors", Value::Object(vec![])),
                        ("attestors", Value::Object(vec![])),
                        ("makes", Value::Array(vec![])),
                    ]),
                ),
                (
                    "obligations",
                    json::object(vec![
                        ("o1", json::object(vec![("preimage", Value::Object(vec![]))])),
                        ("o2", json::object(vec![("preimage", Value::Object(vec![]))])),
                    ]),
                ),
                ("intents", Value::Object(vec![])),
                (
                    "steps",
                    Value::Array(vec![json::object(vec![(
                        "do",
                        json::object(vec![(
                            "set_gate",
                            json::object(vec![
                                ("intent", json::string("")),
                                ("criterion", json::string("")),
                                ("to", json::string("hard")),
                            ]),
                        )]),
                    )])]),
                ),
            ]);
            let report = status::run(&judged).pop().unwrap();
            assert_eq!(report.get("obligations").get("o1").text("status"), Some("unknown"));
            let p = plan(&[pair("t", "o2"), pair("t", "o1")], &[], &report);
            assert_eq!(p.to_check, vec![pair("t", "o1"), pair("t", "o2")]);
            assert!(p.reused.is_empty());
        }
    }

    #[cfg(test)]
    mod verdict_tests {
        use super::*;

        fn pair(b: &str, n: &str) -> (String, String) {
            (b.to_owned(), n.to_owned())
        }

        /// A status scenario as the status command's step 10 makes one.
        fn scenario(obligations: Vec<(&str, Value)>, appends: Vec<Value>) -> Value {
            let mut steps: Vec<Value> = appends
                .into_iter()
                .map(|body| {
                    json::object(vec![(
                        "do",
                        json::object(vec![(
                            "append",
                            json::object(vec![("kind", json::string("evidence")), ("body", body)]),
                        )]),
                    )])
                })
                .collect();
            let neutral_step = json::object(vec![(
                "do",
                json::object(vec![(
                    "set_gate",
                    json::object(vec![
                        ("intent", json::string("")),
                        ("criterion", json::string("")),
                        ("to", json::string("hard")),
                    ]),
                )]),
            )]);
            steps.push(neutral_step);
            json::object(vec![
                ("kind", json::string("status")),
                ("name", json::string("this-project")),
                (
                    "self",
                    json::object(vec![
                        ("writer", json::string("w")),
                        ("platform", json::string("linux/x86_64")),
                    ]),
                ),
                (
                    "policy",
                    json::object(vec![
                        ("min_hard_gates", Value::Number(1)),
                        ("required", Value::Array(vec![])),
                        ("trusted_writers", Value::Array(vec![])),
                        ("floors", Value::Object(vec![])),
                        ("attestors", Value::Object(vec![])),
                        ("makes", Value::Array(vec![])),
                    ]),
                ),
                (
                    "obligations",
                    json::object(
                        obligations
                            .into_iter()
                            .map(|(n, p)| (n, json::object(vec![("preimage", p)])))
                            .collect(),
                    ),
                ),
                ("intents", Value::Object(vec![])),
                ("steps", Value::Array(steps)),
            ])
        }

        #[test]
        fn listed_and_rejected_keeps_its_verdict_and_rejected_only_is_not_planned() {
            let preimage = json::object(vec![
                ("obligation", json::string("o2-key")),
                ("kind", json::string("check")),
            ]);
            let record = json::object(vec![
                ("obligation", json::string("o2")),
                ("preimage", preimage.clone()),
                ("core_key", json::string(&canonical::identity(&preimage))),
                ("platform", json::string("linux/x86_64")),
                ("verdict", json::string("passed")),
                ("writer", json::string("w")),
            ]);
            let judged = scenario(
                vec![("o1", Value::Object(vec![])), ("o2", preimage)],
                vec![record],
            );
            // The verdict comes from the status rules, not from this test.
            let report = status::run(&judged).pop().unwrap();
            let status_of = |n: &str| report.get("obligations").get(n).text("status").map(str::to_owned);
            assert_eq!(status_of("o2").as_deref(), Some("passed"));
            assert_eq!(status_of("o1").as_deref(), Some("unknown"));
            // o2 is listed and rejected; o7 is rejected only.
            let not_checkable = ["o2".to_owned(), "o7".to_owned()];
            let p = plan(&[pair("t", "o2"), pair("t", "o1")], &not_checkable, &report);
            assert_eq!(p.reused, vec![pair("t", "o2")]);
            assert_eq!(p.to_check, vec![pair("t", "o1")]);
            assert!(!p.to_check.iter().chain(&p.reused).any(|(_, n)| n == "o7"));
            assert_eq!((p.obligations, p.not_checkable), (2, 2));
            // With no record, the listed-and-rejected name is checked as listed.
            let empty = status::run(&scenario(vec![("o2", Value::Object(vec![]))], vec![]))
                .pop()
                .unwrap();
            let p = plan(&[pair("t", "o2")], &not_checkable, &empty);
            assert_eq!(p.to_check, vec![pair("t", "o2")]);
        }
    }

    #[cfg(test)]
    mod kept_tests {
        use super::*;

        #[test]
        fn each_session_numbers_its_own_requests() {
            let (mut a, mut b) = (RequestIds::new(), RequestIds::new());
            // The enumeration is "1"; the first check on the same session is "2".
            assert_eq!(a.take(), "1");
            assert_eq!(a.take(), "2");
            // Another session starts again from "1".
            assert_eq!(b.take(), "1");
            assert_eq!(a.take(), "3");
        }

        fn obligation() -> Value {
            json::object(vec![
                ("name", json::string("o1")),
                ("kind", json::string("model")),
                ("specified_by", Value::Array(vec![json::string("spec/a.tla")])),
                ("targets", Value::Array(vec![])),
                ("expect", json::string("holds")),
                ("config", json::object(vec![("depth", Value::Number(3))])),
                ("defect_of", json::string("o0")),
                ("inputs", Value::Array(vec![json::string("spec/a.tla")])),
            ])
        }

        #[test]
        fn a_check_is_started_with_the_obligation_as_enumerated() {
            let o = as_checked(&obligation(), "t.check");
            assert!(o.opt("inputs").is_none());
            assert_eq!(o.text("binding"), Some("t.check"));
            // Every other field as the provider gave it, `defect_of` and `config` included.
            for k in ["name", "kind", "specified_by", "targets", "expect", "config", "defect_of"] {
                assert_eq!(
                    o.opt(k).map(json::encode),
                    obligation().opt(k).map(json::encode),
                    "{k}"
                );
            }
            // A provider's own `binding` does not stand in for the binding.
            let mut forged = obligation();
            if let Value::Object(m) = &mut forged {
                m.push(("binding".to_owned(), json::string("other")));
            }
            assert_eq!(as_checked(&forged, "t.check").text("binding"), Some("t.check"));
        }

        #[test]
        fn what_was_measured_is_what_a_check_starts_with() {
            let tool = json::object(vec![
                ("name", json::string("checker")),
                ("version", json::string("2.1")),
                ("digest", json::string("sha256:cc")),
            ]);
            let c = Checkable {
                binding: "t.check".to_owned(),
                name: "o1".to_owned(),
                obligation: as_checked(&obligation(), "t.check"),
                inputs: vec![("spec/a.tla".to_owned(), "sha256:aa".to_owned())],
                tools: Value::Array(vec![tool]),
                platform: json::object(vec![
                    ("os", json::string("linux")),
                    ("arch", json::string("x86_64")),
                ]),
                preimage: Value::Object(vec![]),
            };
            let start = c.start();
            assert_eq!(start.text("op"), Some("start"));
            let inputs = start.get("inputs").array();
            assert_eq!(inputs.len(), 1);
            assert_eq!(inputs[0].text("path"), Some("spec/a.tla"));
            assert_eq!(inputs[0].text("identity"), Some("sha256:aa"));
            // The full triple, version included, and the platform as given.
            assert_eq!(start.get("tools").array()[0].text("version"), Some("2.1"));
            assert_eq!(start.get("platform").text("os"), Some("linux"));
            assert_eq!(start.get("platform").text("arch"), Some("x86_64"));
            // The host rules see the same files and tools, keyed by digest.
            let ceiling = Some(("model".to_owned(), "bounded".to_owned()));
            let g = c.given(&["checker".to_owned()], &ceiling);
            assert_eq!(g.inputs, c.inputs);
            assert_eq!(g.tools, vec![("checker".to_owned(), "sha256:cc".to_owned())]);
            assert_eq!(g.named(), vec!["spec/a.tla".to_owned()]);
            assert_eq!(g.ceiling, ceiling);
        }

        #[test]
        fn only_a_manifest_listing_the_check_offers_it() {
            let manifest = |caps: &[&str]| {
                json::object(vec![(
                    "capabilities",
                    Value::Array(
                        caps.iter()
                            .map(|c| json::object(vec![("capability", json::string(c))]))
                            .collect(),
                    ),
                )])
            };
            assert!(offers_check(&manifest(&["obligation.enumerate", "obligation.check"])));
            assert!(!offers_check(&manifest(&["obligation.enumerate"])));
            assert!(!offers_check(&json::object(vec![])));
        }
    }

    #[cfg(test)]
    mod tests {
        use super::*;

        /// A folder of the test's own: tests run in parallel.
        fn scratch(name: &str) -> PathBuf {
            let dir = std::env::temp_dir()
                .join(format!("dodona-run-input-{}-{name}", std::process::id()));
            let _ = fs::remove_dir_all(&dir);
            fs::create_dir_all(&dir).unwrap();
            dir
        }

        /// An input both step 1s accept, as fields to edit.
        fn fields(root: &Path) -> Vec<(String, Value)> {
            let site = json::object(vec![
                (
                    "platform",
                    json::object(vec![
                        ("os", json::string("linux")),
                        ("arch", json::string("x86_64")),
                    ]),
                ),
                ("writer", json::string("w")),
                ("runner", json::string("r")),
                ("tools", Value::Array(vec![])),
                ("providers", Value::Object(vec![])),
                ("deadline_ms", Value::Number(1000)),
            ]);
            let policy = json::object(vec![
                ("required", Value::Array(vec![])),
                ("min_hard_gates", Value::Number(1)),
                ("floors", Value::Object(vec![])),
                ("not_applied", Value::Array(vec![])),
            ]);
            let list = |items: &[&str]| Value::Array(items.iter().map(|s| json::string(s)).collect());
            vec![
                ("root", json::string(root.to_str().unwrap())),
                ("project", json::string("dodona.toml")),
                ("site", site),
                ("policy", policy),
                ("policy_source", json::string("test")),
                ("ledgers", list(&["l/run.ledger"])),
                ("owner_ledger", json::string("records/owner.ledger")),
                ("ledger", json::string("l/run.ledger")),
                ("executor", list(&["executor", "batch"])),
            ]
            .into_iter()
            .map(|(k, v)| (k.to_owned(), v))
            .collect()
        }

        fn with(mut f: Vec<(String, Value)>, key: &str, value: Value) -> Vec<(String, Value)> {
            f.retain(|(k, _)| k != key);
            f.push((key.to_owned(), value));
            f
        }

        /// The reason step 1 gives, or `ok`.
        fn reason(f: Vec<(String, Value)>) -> (&'static str, String) {
            match read(json::encode(&Value::Object(f)).as_bytes()) {
                Ok(_) => ("ok", String::new()),
                Err(s) => (s.reason, s.detail),
            }
        }

        fn strs(items: &[&str]) -> Value {
            Value::Array(items.iter().map(|s| json::string(s)).collect())
        }

        #[test]
        fn a_well_formed_input_is_accepted() {
            let root = scratch("accepted");
            fs::create_dir_all(root.join("out")).unwrap();
            let f = with(fields(&root), "transcript", json::string("out/t.json"));
            let got = read(json::encode(&Value::Object(f)).as_bytes());
            let got = match got {
                Ok(r) => r,
                Err(s) => panic!("refused: {} {}", s.reason, s.detail),
            };
            assert_eq!(got.ledger, "l/run.ledger");
            assert_eq!(got.executor, vec!["executor", "batch"]);
            assert_eq!(got.transcript.as_deref(), Some("out/t.json"));
            assert_eq!(got.status.owner_ledger, "records/owner.ledger");
            // No transcript is a run without one.
            assert_eq!(reason(fields(&root)).0, "ok");
            let _ = fs::remove_dir_all(&root);
        }

        #[test]
        fn a_name_a_disk_may_shorten_is_refused_by_its_spelling() {
            let root = scratch("aliases");
            let shortened = "ends in a dot or a space";
            let refused = |f: Vec<(String, Value)>| {
                let (why, detail) = reason(f);
                assert_eq!(why, "bad-input");
                assert!(detail.contains(shortened), "{detail}");
            };
            let run_ledger = |l: &str| {
                let f = with(fields(&root), "ledgers", strs(&[l]));
                with(f, "ledger", json::string(l))
            };
            // The run's ledger and the owner's, always.
            refused(run_ledger("l/run.ledger."));
            refused(run_ledger("l/run.ledger "));
            refused(run_ledger("l./run.ledger"));
            refused(run_ledger("l /run.ledger"));
            refused(with(fields(&root), "owner_ledger", json::string("records/owner.ledger.")));
            refused(with(fields(&root), "owner_ledger", json::string("records /owner.ledger")));
            // Dots and spaces inside a name, or a name starting with a dot, are not shortened.
            assert_eq!(reason(run_ledger("l/run.v1.ledger")).0, "ok");
            assert_eq!(reason(run_ledger("l/.run ledger")).0, "ok");
            // Without a transcript, other listed ledgers and the project file are
            // the status command's to read as they are spelt.
            let others = |f: Vec<(String, Value)>| {
                let f = with(f, "ledgers", strs(&["l/run.ledger", "x/other.ledger."]));
                with(f, "project", json::string("dodona.toml "))
            };
            assert_eq!(reason(others(fields(&root))).0, "ok");
            // With one, every path the transcript must not land on is judged too.
            let t = |f: Vec<(String, Value)>, p: &str| with(f, "transcript", json::string(p));
            refused(t(others(fields(&root)), "t.json"));
            refused(t(with(fields(&root), "ledgers", strs(&["l/run.ledger", "x/other.ledger."])), "t.json"));
            refused(t(with(fields(&root), "project", json::string("dodona.toml.")), "t.json"));
            refused(t(fields(&root), "t.json."));
            refused(t(fields(&root), "out /t.json"));
            assert_eq!(reason(t(fields(&root), "t.json")).0, "ok");
            // Judged before any file is looked at: a root that is not there is not reached.
            let missing = root.join("not-there");
            let f = with(fields(&missing), "owner_ledger", json::string("records/owner.ledger."));
            refused(f);
            let _ = fs::remove_dir_all(&root);
        }

        #[test]
        fn the_platform_is_kept_whole_and_the_status_platform_is_unchanged() {
            let root = scratch("platform");
            let mut f = fields(&root);
            let site = f.iter_mut().find(|(k, _)| k == "site").map(|(_, s)| s).unwrap();
            if let Some(p) = site.opt_mut("platform") {
                *p = json::parse(br#"{"libc":"gnu","arch":"x86_64","os":"linux"}"#).unwrap();
            }
            let got = match read(json::encode(&Value::Object(f)).as_bytes()) {
                Ok(r) => r,
                Err(s) => panic!("refused: {} {}", s.reason, s.detail),
            };
            // What status judges and records is OS + "/" + ARCH, as before.
            assert_eq!(got.status.platform, "linux/x86_64");
            // What a check is started on is the object as the site gave it.
            assert_eq!(got.status.platform_given.text("libc"), Some("gnu"));
            assert_eq!(
                json::encode(&got.status.platform_given),
                r#"{"arch":"x86_64","libc":"gnu","os":"linux"}"#
            );
            let _ = fs::remove_dir_all(&root);
        }

        #[test]
        fn the_ledger_must_be_listed() {
            // Case: "a ledger not listed among the ledgers".
            let root = scratch("unlisted");
            let f = with(fields(&root), "ledger", json::string("l/other.ledger"));
            assert_eq!(reason(f).0, "bad-input");
            // Case: "ledgers that are not a list": refused, never a crash.
            let f = with(fields(&root), "ledgers", Value::Number(5));
            assert_eq!(reason(f).0, "bad-input");
            for bad in [Value::Null, Value::Number(1), json::string(""), json::string("/abs"), json::string("a/../b")] {
                assert_eq!(reason(with(fields(&root), "ledger", bad)).0, "bad-input");
            }
            let _ = fs::remove_dir_all(&root);
        }

        #[test]
        fn the_executor_is_a_command() {
            let root = scratch("executor");
            // Cases: "an executor that is no command", "an executor command holding a NUL".
            for bad in [strs(&[]), strs(&["prog\0x"]), strs(&["prog", "a\0"]), json::string("prog"), Value::Null] {
                assert_eq!(reason(with(fields(&root), "executor", bad)).0, "bad-input");
            }
            let f: Vec<_> = fields(&root).into_iter().filter(|(k, _)| k != "executor").collect();
            assert_eq!(reason(f).0, "bad-input");
            let _ = fs::remove_dir_all(&root);
        }

        #[test]
        fn the_owners_ledger_is_never_the_runs() {
            let root = scratch("owner");
            let as_owner = |owner: &str, ledger: &str| {
                let f = with(fields(&root), "owner_ledger", json::string(owner));
                let f = with(f, "ledgers", strs(&[ledger]));
                reason(with(f, "ledger", json::string(ledger))).0
            };
            // Cases: "the owner's ledger as the run's ledger" and "..., not yet
            // written, ...": no file is there in this test.
            assert_eq!(as_owner("records/owner.ledger", "records/owner.ledger"), "bad-input");
            // Case: "the owner's ledger spelt with other case".
            assert_eq!(as_owner("records/owner.ledger", "Records/owner.ledger"), "bad-input");
            // Case: "the owner's ledger in the other Unicode form".
            assert_eq!(as_owner("records/own\u{e9}r.ledger", "records/owne\u{301}r.ledger"), "bad-input");
            assert_eq!(as_owner("records/owne\u{301}r.ledger", "records/own\u{e9}r.ledger"), "bad-input");
            assert_eq!(as_owner("records/stra\u{df}e.ledger", "records/STRASSE.ledger"), "bad-input");
            // Another name is another ledger.
            assert_eq!(as_owner("records/owner.ledger", "records/other.ledger"), "ok");
            let _ = fs::remove_dir_all(&root);
        }

        /// The name rule is not plain equality or lower case: each of these
        /// would let the cases above through.
        #[test]
        fn a_planted_name_comparison_would_miss_them() {
            let pairs = [
                ("records/owner.ledger", "Records/owner.ledger"),
                ("records/own\u{e9}r.ledger", "records/owne\u{301}r.ledger"),
                ("records/stra\u{df}e.ledger", "records/STRASSE.ledger"),
            ];
            for (a, b) in pairs {
                assert_eq!(disk_name(a), disk_name(b), "{a} {b}");
            }
            assert!(pairs.iter().all(|(a, b)| a != b));
            assert!(pairs[1..].iter().all(|(a, b)| a.to_lowercase() != b.to_lowercase()));
            assert_ne!(unicode::nfc(pairs[0].0), unicode::nfc(pairs[0].1));
            assert_ne!(unicode::nfc(pairs[2].0), unicode::nfc(pairs[2].1));
            assert_ne!(disk_name("records/owner.ledger"), disk_name("records/owner.ledgers"));
        }

        #[test]
        fn a_transcript_is_a_new_file_and_names_nothing_else() {
            let root = scratch("transcript");
            fs::write(root.join("notes.txt"), b"there").unwrap();
            let t = |p: &str| reason(with(fields(&root), "transcript", json::string(p)));
            // Each refusal by the rule it is for: the details tell them apart,
            // so a rule taken away is not hidden by a later one.
            let refused = |p: &str, rule: &str| {
                let (why, detail) = t(p);
                assert_eq!(why, "bad-input", "{p}");
                assert!(detail.contains(rule), "{p}: {detail}");
            };
            // Case: "a transcript path holding a NUL".
            refused("trans\0cript.json", "relative path");
            refused("/abs.json", "relative path");
            // Case: "a transcript written over a ledger".
            refused("l/run.ledger", "names a ledger");
            // Case: "a transcript named like a ledger in other case".
            refused("L/Run.Ledger", "names a ledger");
            // Cases: "a transcript at a ledger's lock", "... at the owner's ledger's lock".
            refused("l/run.ledger.lock", "names a ledger");
            refused("records/owner.ledger.lock", "names a ledger");
            refused("records/owner.ledger", "names a ledger");
            // The project file, compared the same way.
            refused("Dodona.toml", "names a ledger");
            // Case: "a transcript over a file that is there", on a file no other rule names.
            refused("notes.txt", "there already");
            // Case: "a transcript in a folder that is not there".
            refused("nowhere/t.json", "folder");
            assert_eq!(reason(with(fields(&root), "transcript", Value::Number(1))).0, "bad-input");
            assert_eq!(t("t.json").0, "ok");
            let _ = fs::remove_dir_all(&root);
        }

        #[cfg(unix)]
        #[test]
        fn links_on_the_way_are_refused() {
            let root = scratch("links");
            fs::create_dir_all(root.join("real")).unwrap();
            std::os::unix::fs::symlink(root.join("real"), root.join("lk")).unwrap();
            // Case: "the run's ledger behind a link".
            let f = with(fields(&root), "ledgers", strs(&["lk/run.ledger"]));
            assert_eq!(reason(with(f, "ledger", json::string("lk/run.ledger"))).0, "bad-input");
            // Case: "a transcript behind a link".
            let f = with(fields(&root), "transcript", json::string("lk/t.json"));
            assert_eq!(reason(f).0, "bad-input");
            // The same paths through the folder itself are accepted.
            let f = with(fields(&root), "ledgers", strs(&["real/run.ledger"]));
            assert_eq!(reason(with(f, "ledger", json::string("real/run.ledger"))).0, "ok");
            let f = with(fields(&root), "transcript", json::string("real/t.json"));
            assert_eq!(reason(f).0, "ok");
            let _ = fs::remove_dir_all(&root);
        }

        // Hard links and `same_file` exist on both; only links of the other
        // kind need privileges on Windows.
        #[cfg(any(unix, windows))]
        #[test]
        fn a_hard_link_to_the_owners_ledger_is_the_owners() {
            // Case: "the run's ledger a hard link to the owner's". The names
            // differ, so only the same-file rule can refuse it.
            let root = scratch("hardlink");
            fs::create_dir_all(root.join("records")).unwrap();
            fs::create_dir_all(root.join("l")).unwrap();
            fs::write(root.join("records/owner.ledger"), b"").unwrap();
            assert_ne!(disk_name("l/run.ledger"), disk_name("records/owner.ledger"));
            assert_eq!(reason(fields(&root)).0, "ok");
            fs::hard_link(root.join("records/owner.ledger"), root.join("l/run.ledger")).unwrap();
            assert_eq!(reason(fields(&root)).0, "bad-input");
            let _ = fs::remove_dir_all(&root);
        }

        #[test]
        fn the_runs_fields_are_judged_first() {
            // A root that names no folder is the status checks' bad-input; a
            // bad executor is found before it, and no file check is made.
            let root = scratch("first");
            let missing = root.join("not-there");
            let f = with(fields(&missing), "executor", strs(&[]));
            let (why, detail) = reason(f);
            assert_eq!(why, "bad-input");
            assert!(detail.contains("executor"), "{detail}");
            let (why, detail) = reason(fields(&missing));
            assert_eq!(why, "bad-input");
            assert!(detail.contains("root"), "{detail}");
            // An empty root names no folder, whatever folder the test runs in.
            let f = with(fields(&root), "root", json::string(""));
            assert_eq!(reason(f).0, "bad-input");
            let _ = fs::remove_dir_all(&root);
        }
    }
}
