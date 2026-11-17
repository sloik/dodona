use crate::{
    canonical,
    json::{self, Value},
};
/// The separation levels, least first.
pub const LEVELS: [&str; 6] = [
    "self",
    "helper",
    "apart",
    "tested",
    "cross-make",
    "credentialed",
];
pub fn rank(level: &str) -> Option<usize> {
    LEVELS.iter().position(|x| *x == level)
}
/// What grading an act record gives, as positions in `LEVELS`.
#[derive(Debug, PartialEq, Eq)]
pub struct Grade {
    pub claims: usize,
    pub level: usize,
}
fn hmac(key: &[u8], msg: &[u8]) -> String {
    let mut k = if key.len() > 64 {
        canonical::digest(key).to_vec()
    } else {
        key.to_vec()
    };
    k.resize(64, 0);
    let mut inner: Vec<u8> = k.iter().map(|b| b ^ 0x36).collect();
    inner.extend_from_slice(msg);
    let mut outer: Vec<u8> = k.iter().map(|b| b ^ 0x5c).collect();
    outer.extend(canonical::digest(&inner));
    canonical::sha256(&outer)
}
pub fn text<'a>(v: &'a Value, k: &str) -> Option<&'a str> {
    match v.opt(k) {
        Some(Value::String(s)) => Some(s),
        _ => None,
    }
}
fn list(v: Option<&Value>) -> &[Value] {
    match v {
        Some(Value::Array(a)) => a,
        _ => &[],
    }
}
fn yes(v: &Value, k: &str) -> bool {
    matches!(v.opt(k), Some(Value::Bool(true)))
}
fn owner(v: &Value, k: &str) -> bool {
    matches!(text(v, k), Some("kernel" | "owner"))
}
/// The level the facts in the record would support if they were all true.
fn claims(r: &Value, p: &Value) -> usize {
    let none = Value::Null;
    let a = r.opt("actor").unwrap_or(&none);
    let w = r.opt("worker").unwrap_or(&none);
    let distinct = text(a, "id") != text(w, "id") && text(a, "session") != text(w, "session");
    let started = text(a, "started_by").is_some() && text(a, "started_by") != text(w, "id");
    let given = list(r.opt("given"));
    let valid_given = !given.is_empty()
        && given.iter().all(|x| {
            matches!(
                text(x, "role"),
                Some("work" | "criteria" | "brief" | "known-wrong" | "known-right")
            )
        });
    let apart = distinct
        && started
        && r.opt("brief").is_some_and(|b| owner(b, "issued_by"))
        && valid_given
        && yes(r, "fresh_context")
        && r.opt("transcript").is_some();
    let examples = [("known-wrong", "wrong"), ("known-right", "right")];
    let tested = apart
        && r.opt("known_bad").is_some_and(|b| {
            owner(b, "supplied_by")
                && yes(b, "rejected_wrong")
                && yes(b, "accepted_right")
                && examples.iter().all(|(role, field)| {
                    given.iter().any(|x| {
                        text(x, "role") == Some(*role)
                            && text(x, "content").is_some()
                            && text(x, "content") == text(b, field)
                    })
                })
        });
    let group = |person: &Value| -> Option<usize> {
        let m = person.opt("make")?;
        let name = format!("{}/{}", text(m, "vendor")?, text(m, "family")?);
        list(p.opt("makes")).iter().position(|g| {
            list(Some(g))
                .iter()
                .any(|x| matches!(x, Value::String(s) if *s == name))
        })
    };
    let cross = tested && matches!((group(a), group(w)), (Some(x), Some(y)) if x != y);
    if cross {
        4
    } else if tested {
        3
    } else if apart {
        2
    } else if distinct {
        1
    } else {
        0
    }
}
/// The fields of the record a harness the policy names has vouched for.
fn covered<'a>(r: &'a Value, p: &Value) -> Vec<&'a str> {
    let Some(att) = r.opt("attestation") else {
        return Vec::new();
    };
    let (Some(keyname), Some(mac), Some(Value::Array(covers))) =
        (text(att, "key"), text(att, "mac"), att.opt("covers"))
    else {
        return Vec::new();
    };
    let key = p.opt("attestors").and_then(|a| text(a, keyname));
    let Some(key) = key.and_then(canonical::unhex).filter(|k| !k.is_empty()) else {
        return Vec::new();
    };
    let mut names = Vec::new();
    let mut fields: Vec<(String, Value)> = Vec::new();
    for c in covers {
        let Value::String(name) = c else {
            return Vec::new();
        };
        names.push(name.as_str());
        if let Some(v) = r.opt(name) {
            if !fields.iter().any(|(k, _)| k == name) {
                fields.push((name.clone(), v.clone()));
            }
        }
    }
    let payload = json::object(vec![
        ("covers", Value::Array(covers.clone())),
        ("fields", Value::Object(fields)),
    ]);
    if hmac(&key, json::encode(&payload).as_bytes()) == mac {
        names
    } else {
        Vec::new()
    }
}
/// Grade an act record under a policy. This is the one grading rule: acts
/// scenarios report it and status scenarios count with it.
pub fn grade(r: &Value, p: &Value) -> Grade {
    let claims = claims(r, p);
    let covered = covered(r, p);
    let vouched = |names: &[&str]| names.iter().all(|n| covered.iter().any(|x| x == n));
    // What the facts of each level above `helper` read, in order.
    let reads: [&[&str]; 3] = [
        &[
            "actor",
            "worker",
            "brief",
            "given",
            "fresh_context",
            "transcript",
        ],
        &["known_bad", "given"],
        &["actor", "worker"],
    ];
    let mut level = claims.min(1);
    for (i, fields) in reads.iter().enumerate() {
        if level == i + 1 && claims >= i + 2 && vouched(fields) {
            level = i + 2;
        }
    }
    Grade { claims, level }
}
pub fn run(v: &Value) -> Vec<Value> {
    v.get("steps")
        .array()
        .iter()
        .map(|s| {
            let g = grade(s.get("do").get("grade"), v.get("policy"));
            json::object(vec![
                ("claims", json::string(LEVELS[g.claims])),
                ("level", json::string(LEVELS[g.level])),
                (
                    "source",
                    json::string(if g.level > 1 { "attested" } else { "declared" }),
                ),
            ])
        })
        .collect()
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rfc4231() {
        assert_eq!(
            hmac(&[0x0b; 20], b"Hi There"),
            "b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7"
        );
        assert_eq!(
            hmac(b"Jefe", b"what do ya want for nothing?"),
            "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843"
        );
        // Case 6: a key longer than one block is hashed first.
        assert_eq!(
            hmac(
                &[0xaa; 131],
                b"Test Using Larger Than Block-Size Key - Hash Key First"
            ),
            "60e431591ee0b67f0d8a26aacbf5b77f8e0bc6213728c5140546040f0ee37f54"
        );
    }
    #[test]
    fn level_order() {
        assert_eq!(rank("self"), Some(0));
        assert!(rank("tested") > rank("apart"));
        assert_eq!(rank("credentialed"), Some(5));
        assert_eq!(rank("nobody"), None);
    }
    const POLICY: &str =
        r#"{"attestors":{"h":"6b6579","empty":""},"makes":[["v/a","v/a2"],["w/b"]]}"#;
    const KEY: &[u8] = b"key";
    const FULL: &str = r#"{
        "actor":{"id":"judge","session":"s2","started_by":"kernel","make":{"vendor":"w","family":"b"}},
        "worker":{"id":"worker","session":"s1","make":{"vendor":"v","family":"a"}},
        "brief":{"issued_by":"kernel","content":"b"},
        "given":[{"role":"work","content":"w"},{"role":"known-wrong","content":"bad"},{"role":"known-right","content":"good"}],
        "fresh_context":true,
        "transcript":"t",
        "known_bad":{"supplied_by":"owner","wrong":"bad","right":"good","rejected_wrong":true,"accepted_right":true}
    }"#;
    fn record(change: impl Fn(&mut Vec<(String, Value)>)) -> Value {
        let mut v = json::parse(FULL.as_bytes()).unwrap();
        if let Value::Object(fields) = &mut v {
            change(fields);
        }
        v
    }
    fn set(fields: &mut Vec<(String, Value)>, name: &str, to: &str) {
        fields.retain(|(k, _)| k != name);
        if !to.is_empty() {
            fields.push((name.into(), json::parse(to.as_bytes()).unwrap()));
        }
    }
    /// The record with an attestation over `covers`, signed with `key` under the name `keyname`.
    fn attested(mut r: Value, covers: &[&str], keyname: &str, key: &[u8]) -> Value {
        let covers = Value::Array(covers.iter().map(|c| json::string(c)).collect());
        let mut fields: Vec<(String, Value)> = Vec::new();
        for c in covers.array() {
            if let Some(v) = r.opt(c.str()) {
                if !fields.iter().any(|(k, _)| k == c.str()) {
                    fields.push((c.str().into(), v.clone()));
                }
            }
        }
        let payload = json::object(vec![
            ("covers", covers.clone()),
            ("fields", Value::Object(fields)),
        ]);
        let mac = hmac(key, json::encode(&payload).as_bytes());
        if let Value::Object(fields) = &mut r {
            fields.push((
                "attestation".into(),
                json::object(vec![
                    ("key", json::string(keyname)),
                    ("covers", covers),
                    ("mac", json::string(&mac)),
                ]),
            ));
        }
        r
    }
    fn graded(r: &Value) -> (&'static str, &'static str) {
        let g = grade(r, &json::parse(POLICY.as_bytes()).unwrap());
        (LEVELS[g.claims], LEVELS[g.level])
    }
    const APART: [&str; 6] = [
        "actor",
        "worker",
        "brief",
        "given",
        "fresh_context",
        "transcript",
    ];
    const ALL: [&str; 7] = [
        "actor",
        "worker",
        "brief",
        "given",
        "fresh_context",
        "transcript",
        "known_bad",
    ];
    #[test]
    fn claims_follow_the_facts() {
        assert_eq!(graded(&record(|_| ())), ("cross-make", "helper"));
        assert_eq!(graded(&json::parse(b"{}").unwrap()), ("self", "self"));
        let same_session = record(|f| set(f, "worker", r#"{"id":"worker","session":"s2"}"#));
        assert_eq!(graded(&same_session), ("self", "self"));
        let same_id = record(|f| set(f, "worker", r#"{"id":"judge","session":"s1"}"#));
        assert_eq!(graded(&same_id), ("self", "self"));
        let by_worker = record(|f| {
            set(
                f,
                "actor",
                r#"{"id":"judge","session":"s2","started_by":"worker"}"#,
            )
        });
        assert_eq!(graded(&by_worker), ("helper", "helper"));
        let unstarted = record(|f| set(f, "actor", r#"{"id":"judge","session":"s2"}"#));
        assert_eq!(graded(&unstarted), ("helper", "helper"));
        for (field, to) in [
            ("brief", r#"{"issued_by":"worker","content":"b"}"#),
            ("brief", ""),
            ("given", "[]"),
            ("given", ""),
            ("given", r#"[{"role":"other","content":"x"}]"#),
            ("given", r#""not a list""#),
            ("fresh_context", "false"),
            ("fresh_context", ""),
            ("transcript", ""),
        ] {
            let r = record(|f| set(f, field, to));
            assert_eq!(graded(&r), ("helper", "helper"), "{field} {to}");
        }
        for to in [
            "",
            r#"{"supplied_by":"worker","wrong":"bad","right":"good","rejected_wrong":true,"accepted_right":true}"#,
            r#"{"supplied_by":"owner","wrong":"bad","right":"good","rejected_wrong":false,"accepted_right":true}"#,
            r#"{"supplied_by":"owner","wrong":"bad","right":"good","rejected_wrong":true}"#,
            r#"{"supplied_by":"owner","wrong":"other","right":"good","rejected_wrong":true,"accepted_right":true}"#,
            r#"{"supplied_by":"owner","wrong":"good","right":"bad","rejected_wrong":true,"accepted_right":true}"#,
            r#"{"supplied_by":"owner","rejected_wrong":true,"accepted_right":true}"#,
        ] {
            let r = record(|f| set(f, "known_bad", to));
            assert_eq!(graded(&r), ("apart", "helper"), "{to}");
        }
        for worker in [
            r#"{"id":"worker","session":"s1","make":{"vendor":"w","family":"b"}}"#,
            r#"{"id":"worker","session":"s1","make":{"vendor":"v","family":"unlisted"}}"#,
            r#"{"id":"worker","session":"s1","make":{"vendor":"v"}}"#,
            r#"{"id":"worker","session":"s1"}"#,
        ] {
            let r = record(|f| set(f, "worker", worker));
            assert_eq!(graded(&r), ("tested", "helper"), "{worker}");
        }
    }
    #[test]
    fn levels_above_helper_need_a_voucher() {
        let full = || record(|_| ());
        assert_eq!(
            graded(&attested(full(), &ALL, "h", KEY)),
            ("cross-make", "cross-make")
        );
        assert_eq!(
            graded(&attested(full(), &APART, "h", KEY)),
            ("cross-make", "apart")
        );
        // Without the facts below it vouched for, a higher level is not reached.
        assert_eq!(
            graded(&attested(full(), &["known_bad", "given"], "h", KEY)),
            ("cross-make", "helper")
        );
        assert_eq!(
            graded(&attested(full(), &APART[1..], "h", KEY)),
            ("cross-make", "helper")
        );
        // The grant is never above the claim.
        let helper = record(|f| set(f, "transcript", ""));
        assert_eq!(
            graded(&attested(helper, &ALL, "h", KEY)),
            ("helper", "helper")
        );
        let apart = record(|f| set(f, "known_bad", ""));
        assert_eq!(graded(&attested(apart, &ALL, "h", KEY)), ("apart", "apart"));
        // A wrong key, a key the policy does not name, an empty key, a changed record.
        assert_eq!(
            graded(&attested(full(), &ALL, "h", b"other")),
            ("cross-make", "helper")
        );
        assert_eq!(
            graded(&attested(full(), &ALL, "stranger", KEY)),
            ("cross-make", "helper")
        );
        assert_eq!(
            graded(&attested(full(), &ALL, "empty", b"")),
            ("cross-make", "helper")
        );
        let mut changed = attested(full(), &ALL, "h", KEY);
        if let Value::Object(f) = &mut changed {
            set(f, "transcript", r#""another""#);
        }
        assert_eq!(graded(&changed), ("cross-make", "helper"));
        // Malformed attestations vouch for nothing and do not stop the kernel.
        for att in [
            r#"{"key":"h","mac":"00"}"#,
            r#"{"key":"h","mac":"00","covers":"actor"}"#,
            r#"{"key":"h","mac":"00","covers":[1]}"#,
            r#"{"key":7,"mac":"00","covers":[]}"#,
            "null",
        ] {
            let r = record(|f| set(f, "attestation", att));
            assert_eq!(graded(&r), ("cross-make", "helper"), "{att}");
        }
    }
}
