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

/// Relative: not empty, not starting with `/`, no `\` and no `:`, and no
/// segment that is empty, `.` or `..`.
fn relative(p: &str) -> bool {
    !p.is_empty()
        && !p.starts_with('/')
        && !p.contains('\\')
        && !p.contains(':')
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
    writer: String,
    runner: String,
    tools: Value,
    providers: Vec<(String, Provider)>,
    deadline_ms: u64,
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
    let tools = Value::Array(
        tools
            .iter()
            .map(|t| {
                json::object(vec![
                    ("name", t.get("name").clone()),
                    ("digest", t.get("digest").clone()),
                ])
            })
            .collect(),
    );
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
        writer,
        runner,
        tools,
        providers: read,
        deadline_ms,
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

struct Session {
    peer: Peer,
    log: Log,
    manifest: Value,
    wait: Duration,
    deadline_ms: u64,
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
        };
        match s.greet(binding) {
            Ok(()) => Ok(s),
            Err(reason) => {
                s.close();
                stop(reason, binding.provider.clone())
            }
        }
    }
    fn greet(&mut self, binding: &Binding) -> Result<(), &'static str> {
        self.peer.send(
            &hello(host::MAX_LINE, self.deadline_ms),
            Instant::now() + self.wait,
        )?;
        let m = self.peer.read(Instant::now() + self.wait)?;
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
    /// One request, and the body of its result.
    fn ask(&mut self, capability: &str, body: Value) -> Result<Value, &'static str> {
        let request = json::object(vec![
            ("type", json::string("request")),
            ("id", json::string("1")),
            ("deadline_ms", Value::Number(self.deadline_ms as i64)),
            ("capability", json::string(capability)),
            ("body", body),
        ]);
        self.peer.send(&request, Instant::now() + self.wait)?;
        let a = self.peer.read(Instant::now() + self.wait)?;
        if a.text("id") != Some("1") {
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
    fn close(&mut self) {
        let _ = self.peer.shutdown(Instant::now() + wire::SHUTDOWN_GRACE);
        self.peer.end();
        self.log.settle();
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
        Ok(body) => Ok((body, s.manifest)),
        Err(reason) => stop(reason, format!("{}: {capability}", binding.provider)),
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
    /// name -> {"preimage": P}, in the order found.
    found: Vec<(String, Value)>,
    /// Every obligation as {"binding", "name"}, sorted by binding and then name.
    listed: Vec<(String, String)>,
    not_checkable: Vec<String>,
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

fn obligations(
    input: &Input,
    bindings: &[Binding],
    claims: &[(String, Vec<(String, String)>)],
) -> Step<Obligations> {
    let mut out = Obligations {
        found: Vec::new(),
        listed: Vec::new(),
        not_checkable: Vec::new(),
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
        let (answer, manifest) = consult(input, binding, "obligation.enumerate", body)?;
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
            out.found
                .push((name.to_owned(), json::object(vec![("preimage", preimage)])));
            out.listed.push((binding.name.clone(), name.to_owned()));
        }
        out.not_checkable
            .extend(rejected.iter().map(|r| r.get("name").str().to_owned()));
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
/// Without a file index in the standard library, the same file is the same
/// path once every link is resolved. A hard link is not recognised.
#[cfg(not(unix))]
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

fn run(raw: &[u8]) -> Step<Value> {
    // Step 1.
    let input = read_input(raw)?;
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
    let obligations = obligations(&input, &bindings, &claims)?;
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
    let mut steps: Vec<Value> = read
        .entries
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
        ("obligations", sorted_object(obligations.found)),
        ("intents", sorted_object(intents.judged.clone())),
        ("steps", Value::Array(steps)),
    ]);
    // The report is what the status rules give for J, and nothing else.
    let report = status::run(&judged).pop().unwrap_or(Value::Null);
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
    Ok(json::object(vec![
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
    ]))
}
