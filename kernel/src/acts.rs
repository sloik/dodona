use crate::{
    canonical,
    json::{self, Value},
};
use std::cmp::Ordering;
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
    v.text(k)
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
    // A key is a non-empty, even number of lowercase hexadecimal digits. Anything else names no key.
    let key = p.opt("attestors").and_then(|a| text(a, keyname));
    let Some(key) = key.and_then(canonical::unhex).filter(|k| !k.is_empty()) else {
        return Vec::new();
    };
    // The list must already be in canonical order, with no name repeated.
    let in_order = covers.windows(2).all(|w| match (&w[0], &w[1]) {
        (Value::String(a), Value::String(b)) => json::key_order(a, b) == Ordering::Less,
        _ => false,
    });
    if !in_order {
        return Vec::new();
    }
    let mut names = Vec::new();
    let mut fields: Vec<(String, Value)> = Vec::new();
    for c in covers {
        let Value::String(name) = c else {
            return Vec::new();
        };
        names.push(name.as_str());
        // A covered field the record does not have is left out.
        if let Some(v) = r.opt(name) {
            fields.push((name.clone(), v.clone()));
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
/// What a check value must also cover before any level above `helper` is
/// granted, so that it binds what was judged.
const BOUND: &[&str] = &["kind", "target", "result", "lineage"];
/// Whether a record is malformed: `actor` or `worker` is not an object with a
/// string `id` and `session`, or a field that is present has the wrong type.
fn malformed(r: &Value) -> bool {
    let object = |v: &Value| matches!(v, Value::Object(_));
    let string = |v: &Value| matches!(v, Value::String(_));
    let has = |v: &Value, k: &str| v.text(k).is_some();
    let flag = |v: &Value, k: &str| matches!(v.opt(k), Some(Value::Bool(_)));
    let party = |name: &str| {
        r.opt(name)
            .is_some_and(|p| object(p) && has(p, "id") && has(p, "session"))
    };
    // Whether a field is present and does not satisfy `good`.
    let wrong = |name: &str, good: &dyn Fn(&Value) -> bool| r.opt(name).is_some_and(|v| !good(v));
    !party("actor")
        || !party("worker")
        || wrong("brief", &object)
        || wrong("given", &|g| match g {
            Value::Array(items) => items
                .iter()
                .all(|x| object(x) && has(x, "role") && has(x, "content")),
            _ => false,
        })
        || wrong("fresh_context", &|v| matches!(v, Value::Bool(_)))
        || wrong("transcript", &string)
        || wrong("known_bad", &|b| {
            object(b)
                && ["wrong", "right", "supplied_by"].iter().all(|k| has(b, k))
                && ["rejected_wrong", "accepted_right"]
                    .iter()
                    .all(|k| flag(b, k))
        })
        || wrong("attestation", &|a| {
            let covers = matches!(a.opt("covers"), Some(Value::Array(c)) if c.iter().all(string));
            object(a) && has(a, "key") && has(a, "mac") && covers
        })
        || ["kind", "target", "result"]
            .iter()
            .any(|k| wrong(k, &string))
        || wrong("lineage", &object)
}
/// Grade an act record under a policy. This is the one grading rule: acts
/// scenarios report it and status scenarios count with it.
pub fn grade(r: &Value, p: &Value) -> Grade {
    if malformed(r) {
        return Grade {
            claims: 0,
            level: 0,
        };
    }
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
    if !vouched(BOUND) {
        return Grade { claims, level };
    }
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
    const POLICY: &str = r#"{"attestors":{"h":"6b6579","empty":"","upper":"6B","odd":"6b6"},"makes":[["v/a","v/a2"],["w/b"]]}"#;
    const KEY: &[u8] = b"key";
    const FULL: &str = r#"{
        "actor":{"id":"judge","session":"s2","started_by":"kernel","make":{"vendor":"w","family":"b"}},
        "worker":{"id":"worker","session":"s1","make":{"vendor":"v","family":"a"}},
        "brief":{"issued_by":"kernel","content":"b"},
        "given":[{"role":"work","content":"w"},{"role":"known-wrong","content":"bad"},{"role":"known-right","content":"good"}],
        "fresh_context":true,
        "transcript":"t",
        "known_bad":{"supplied_by":"owner","wrong":"bad","right":"good","rejected_wrong":true,"accepted_right":true},
        "kind":"match-check","target":"sha256:00","result":"agreed","lineage":{"intent":"i"}
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
                fields.retain(|(k, _)| k != c.str());
                fields.push((c.str().into(), v.clone()));
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
    /// In canonical order, as a check value must list them.
    const APART: [&str; 10] = [
        "actor",
        "brief",
        "fresh_context",
        "given",
        "kind",
        "lineage",
        "result",
        "target",
        "transcript",
        "worker",
    ];
    const ALL: [&str; 11] = [
        "actor",
        "brief",
        "fresh_context",
        "given",
        "kind",
        "known_bad",
        "lineage",
        "result",
        "target",
        "transcript",
        "worker",
    ];
    fn without(names: &[&'static str], gone: &str) -> Vec<&'static str> {
        names.iter().copied().filter(|n| *n != gone).collect()
    }
    #[test]
    fn claims_follow_the_facts() {
        assert_eq!(graded(&record(|_| ())), ("cross-make", "helper"));
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
            r#"{"supplied_by":"owner","wrong":"other","right":"good","rejected_wrong":true,"accepted_right":true}"#,
            r#"{"supplied_by":"owner","wrong":"good","right":"bad","rejected_wrong":true,"accepted_right":true}"#,
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
    fn a_malformed_record_is_self() {
        assert!(!malformed(&record(|_| ())));
        assert!(!malformed(&attested(record(|_| ()), &ALL, "h", KEY)));
        // Absent fields are not malformed, except the two parties.
        for field in ALL {
            let r = record(|f| set(f, field, ""));
            assert_eq!(
                malformed(&r),
                field == "actor" || field == "worker",
                "{field}"
            );
        }
        for (field, to) in [
            ("actor", r#""judge""#),
            ("actor", r#"{"id":"judge"}"#),
            ("actor", r#"{"id":7,"session":"s2"}"#),
            ("worker", r#"{"session":"s1"}"#),
            ("worker", r#"{"id":"worker","session":null}"#),
            ("brief", r#""kernel""#),
            ("given", r#""not a list""#),
            ("given", r#"["work"]"#),
            ("given", r#"[{"role":"work"}]"#),
            ("given", r#"[{"role":7,"content":"w"}]"#),
            ("fresh_context", r#""yes""#),
            ("transcript", "null"),
            ("transcript", "7"),
            ("known_bad", "[]"),
            (
                "known_bad",
                r#"{"supplied_by":"owner","wrong":"bad","right":"good","rejected_wrong":true}"#,
            ),
            (
                "known_bad",
                r#"{"supplied_by":"owner","rejected_wrong":true,"accepted_right":true}"#,
            ),
            (
                "known_bad",
                r#"{"wrong":"bad","right":"good","rejected_wrong":true,"accepted_right":true}"#,
            ),
            ("attestation", "null"),
            ("attestation", r#"{"key":"h","mac":"00"}"#),
            ("attestation", r#"{"key":"h","mac":"00","covers":"actor"}"#),
            ("attestation", r#"{"key":"h","mac":"00","covers":[1]}"#),
            ("attestation", r#"{"key":7,"mac":"00","covers":[]}"#),
            ("attestation", r#"{"key":"h","covers":[]}"#),
            ("kind", "7"),
            ("target", "null"),
            ("result", "true"),
            ("lineage", r#""i""#),
        ] {
            let r = record(|f| set(f, field, to));
            assert!(malformed(&r), "{field} {to}");
            assert_eq!(graded(&r), ("self", "self"), "{field} {to}");
        }
        assert_eq!(graded(&json::parse(b"{}").unwrap()), ("self", "self"));
        assert_eq!(graded(&Value::Null), ("self", "self"));
        // Whoever signed it.
        let mut signed = attested(record(|_| ()), &ALL, "h", KEY);
        if let Value::Object(f) = &mut signed {
            set(f, "x-extra", "1");
            set(f, "brief", r#""kernel""#);
        }
        assert_eq!(graded(&signed), ("self", "self"));
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
        // Each field a fact reads must be covered, and so must what was judged.
        for field in APART {
            let r = attested(full(), &without(&ALL, field), "h", KEY);
            assert_eq!(graded(&r), ("cross-make", "helper"), "{field}");
        }
        // A bound field the record does not have is still to be listed, and is left out of what is signed.
        let no_lineage = record(|f| set(f, "lineage", ""));
        assert_eq!(
            graded(&attested(no_lineage, &ALL, "h", KEY)),
            ("cross-make", "cross-make")
        );
        // The grant is never above the claim.
        let helper = record(|f| set(f, "transcript", ""));
        assert_eq!(
            graded(&attested(helper, &ALL, "h", KEY)),
            ("helper", "helper")
        );
        let apart = record(|f| set(f, "known_bad", ""));
        assert_eq!(graded(&attested(apart, &ALL, "h", KEY)), ("apart", "apart"));
        // A wrong key, a key the policy does not name, keys that are not keys, a changed record.
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
        assert_eq!(
            graded(&attested(full(), &ALL, "upper", b"k")),
            ("cross-make", "helper")
        );
        assert_eq!(
            graded(&attested(full(), &ALL, "odd", b"k")),
            ("cross-make", "helper")
        );
        for (field, to) in [
            ("transcript", r#""another""#),
            ("kind", r#""confirm-baseline""#),
            ("target", r#""sha256:11""#),
            ("result", r#""refused""#),
            ("lineage", r#"{"intent":"j"}"#),
        ] {
            let mut changed = attested(full(), &ALL, "h", KEY);
            if let Value::Object(f) = &mut changed {
                set(f, field, to);
            }
            assert_eq!(graded(&changed), ("cross-make", "helper"), "{field}");
        }
        // The check value is exact: uppercase, a part of it, or a list out of order or with a repeat.
        let exact = |change: &dyn Fn(&str, &mut Vec<Value>) -> String| {
            let mut r = attested(full(), &ALL, "h", KEY);
            let att = r.opt_mut("attestation").unwrap();
            let mac = att.text("mac").unwrap().to_owned();
            let mut covers = att.opt("covers").unwrap().array().to_vec();
            let mac = change(&mac, &mut covers);
            *att.opt_mut("mac").unwrap() = json::string(&mac);
            *att.opt_mut("covers").unwrap() = Value::Array(covers);
            graded(&r)
        };
        let sign = |covers: &[Value]| {
            let r = full();
            let fields = covers
                .iter()
                .filter_map(|c| Some((c.str().to_owned(), r.opt(c.str())?.clone())))
                .fold(Vec::new(), |mut all: Vec<(String, Value)>, f| {
                    all.retain(|(k, _)| *k != f.0);
                    all.push(f);
                    all
                });
            let payload = json::object(vec![
                ("covers", Value::Array(covers.to_vec())),
                ("fields", Value::Object(fields)),
            ]);
            hmac(KEY, json::encode(&payload).as_bytes())
        };
        assert_eq!(
            exact(&|mac, _| mac.to_owned()),
            ("cross-make", "cross-make")
        );
        assert_eq!(
            exact(&|mac, _| mac.to_uppercase()),
            ("cross-make", "helper")
        );
        assert_eq!(
            exact(&|mac, _| mac[..62].to_owned()),
            ("cross-make", "helper")
        );
        assert_eq!(
            exact(&|_, covers| {
                covers.swap(0, 1);
                sign(covers)
            }),
            ("cross-make", "helper")
        );
        assert_eq!(
            exact(&|_, covers| {
                covers.insert(0, covers[0].clone());
                sign(covers)
            }),
            ("cross-make", "helper")
        );
    }
}
