use crate::{
    acts::{self, text},
    canonical, evidence,
    intent::{self, Criterion},
    json::{self, Value},
};
use std::collections::BTreeMap;
type Ledger = [(String, Value)];
fn list(v: Option<&Value>) -> &[Value] {
    match v {
        Some(Value::Array(a)) => a,
        _ => &[],
    }
}
fn sorted(v: &Value) -> Value {
    let mut a = v.array().to_vec();
    a.sort_by(|x, y| x.str().encode_utf16().cmp(y.str().encode_utf16()));
    Value::Array(a)
}
fn baseline(i: &Value) -> String {
    let criteria = Value::Object(
        i.get("criteria")
            .object()
            .iter()
            .map(|(n, c)| {
                (
                    n.clone(),
                    json::object(vec![
                        ("gate", c.get("gate").clone()),
                        ("checked_by", sorted(c.get("checked_by"))),
                    ]),
                )
            })
            .collect(),
    );
    canonical::identity(&json::object(vec![
        ("owner", i.get("owner").clone()),
        ("children", sorted(i.get("children"))),
        ("criteria", criteria),
    ]))
}
/// The key an evidence record stands under, or none if the record is rejected:
/// it must state the core key of its own preimage.
fn stated_key(body: &Value) -> Option<String> {
    let key = canonical::core_key(body.opt("preimage")?).ok()?;
    (text(body, "core_key") == Some(key.as_str())).then_some(key)
}
/// Whether an evidence record counts for the obligation `name`, whose key as things stand is `key`.
fn counts(body: &Value, name: &str, key: Option<&str>, own: &Value, policy: &Value) -> bool {
    let writer = text(body, "writer");
    let trusted = list(policy.opt("trusted_writers"))
        .iter()
        .any(|w| matches!(w, Value::String(s) if Some(s.as_str()) == writer));
    let accepted = writer.is_some() && (writer == text(own, "writer") || trusted);
    text(body, "obligation") == Some(name)
        && key.is_some()
        && stated_key(body).as_deref() == key
        && text(body, "platform").is_some()
        && text(body, "platform") == text(own, "platform")
        && accepted
}
/// The level of an act record for an intent: graded as any act, but `self` when it is not about the intent's worker.
fn level(r: &Value, policy: &Value, intent: &Value) -> usize {
    let worker = r.opt("worker").and_then(|w| text(w, "id"));
    if worker.is_none() || worker != text(intent, "worker") {
        0
    } else {
        acts::grade(r, policy).level
    }
}
fn agreed<'a>(ledger: &'a Ledger, kind: &'a str) -> impl Iterator<Item = &'a Value> {
    ledger
        .iter()
        .filter(move |(k, r)| {
            k == "act" && text(r, "kind") == Some(kind) && text(r, "result") == Some("agreed")
        })
        .map(|(_, r)| r)
}
/// The levels of the agreed acts that would confirm the intent but for the floor.
fn confirmations(ledger: &Ledger, name: &str, intent: &Value, policy: &Value) -> Vec<usize> {
    let base = baseline(intent);
    let owner = text(intent, "owner");
    agreed(ledger, "confirm-baseline")
        .filter(|r| {
            r.opt("lineage").and_then(|l| text(l, "intent")) == Some(name)
                && text(r, "target") == Some(base.as_str())
                && owner.is_some()
                && r.opt("actor").and_then(|a| text(a, "id")) == owner
        })
        .map(|r| level(r, policy, intent))
        .collect()
}
/// The highest level among the agreed acts matching one criterion with one obligation.
fn match_check(
    ledger: &Ledger,
    name: &str,
    criterion: &str,
    obligation: &Value,
    intent: &Value,
    policy: &Value,
) -> usize {
    let target = canonical::identity(&json::object(vec![
        ("intent", json::string(name)),
        ("criterion", json::string(criterion)),
        ("obligation", obligation.clone()),
    ]));
    agreed(ledger, "match-check")
        .filter(|r| text(r, "target") == Some(target.as_str()))
        .map(|r| level(r, policy, intent))
        .max()
        .unwrap_or(0)
}
/// The separation report from the level of each act there must be, the confirmation first.
fn separation(levels: &[(&str, usize)]) -> Value {
    let weakest = levels.iter().map(|(_, x)| *x).min().unwrap_or(0);
    let kind = levels
        .iter()
        .find(|(_, x)| *x == weakest)
        .map_or("confirm-baseline", |(k, _)| k);
    let apart = levels.iter().filter(|(_, x)| *x >= 2).count();
    json::object(vec![
        ("weakest", json::string(acts::LEVELS[weakest])),
        ("act", json::string(kind)),
        ("apart_or_better", Value::Number(apart as i64)),
        ("of", Value::Number(levels.len() as i64)),
    ])
}
/// Whether some hard criterion has an obligation that is failed or in conflict.
fn hard_failure(criteria: &[Criterion]) -> bool {
    criteria.iter().any(|c| {
        c.gate == "hard"
            && c.checks
                .iter()
                .any(|s| matches!(s.as_str(), "failed" | "conflict"))
    })
}
/// Project status from each required intent: its status and whether a hard gate failed,
/// or nothing if there is no such intent.
fn project(required: &[Option<(&str, bool)>]) -> &'static str {
    if required.is_empty() {
        "nothing-required"
    } else if required.iter().any(|r| matches!(r, Some((_, true)))) {
        "failed"
    } else if required
        .iter()
        .all(|r| matches!(r, Some(("delivered" | "fulfilled", _))))
    {
        "passed"
    } else {
        "unknown"
    }
}
fn count(n: usize) -> Value {
    Value::Number(n as i64)
}
pub fn run(v: &Value) -> Vec<Value> {
    let mut obligations = v.get("obligations").clone();
    let mut intents = v.get("intents").clone();
    let policy = v.get("policy");
    let own = v.get("self");
    let floor = acts::rank(policy.get("floors").get("confirm-baseline").str())
        .expect("the confirm-baseline floor is not a separation level");
    let min = policy.get("min_hard_gates").number();
    let mut ledger: Vec<(String, Value)> = Vec::new();
    let mut out = Vec::new();
    for step in v.get("steps").array() {
        let a = step.get("do");
        if let Some(x) = a.opt("append") {
            ledger.push((x.get("kind").str().into(), x.get("body").clone()));
        }
        // A change to an obligation, or a gate, that is not there has nothing to act on.
        if let Some(x) = a.opt("change") {
            let o = obligations.opt_mut(x.get("obligation").str());
            if let Some(p) = o.and_then(|o| o.opt_mut("preimage")) {
                *p = x.get("preimage").clone();
            }
        }
        if let Some(x) = a.opt("set_gate") {
            let gate = intents
                .opt_mut(x.get("intent").str())
                .and_then(|i| i.opt_mut("criteria"))
                .and_then(|c| c.opt_mut(x.get("criterion").str()))
                .and_then(|c| c.opt_mut("gate"));
            if let Some(g) = gate {
                *g = x.get("to").clone();
            }
        }
        let evidence = || ledger.iter().filter(|(k, _)| k == "evidence");
        let rejected = evidence().filter(|(_, b)| stated_key(b).is_none()).count();
        let mut statuses: BTreeMap<&str, &'static str> = BTreeMap::new();
        let mut obligations_out = Vec::new();
        for (name, o) in obligations.object() {
            let key = o.opt("preimage").and_then(|p| canonical::core_key(p).ok());
            let status = evidence::status(
                evidence()
                    .filter(|(_, b)| counts(b, name, key.as_deref(), own, policy))
                    .filter_map(|(_, b)| text(b, "verdict")),
            );
            statuses.insert(name, status);
            let mut f = vec![("status", json::string(status))];
            if status == "unknown" {
                f.push(("reason", json::string("never-run")));
            }
            obligations_out.push((name.clone(), json::object(f)));
        }
        let mut intents_out = Vec::new();
        let mut reports: BTreeMap<&str, (&'static str, bool)> = BTreeMap::new();
        for (name, i) in intents.object() {
            let confirmations = confirmations(&ledger, name, i, policy);
            let confirmed = confirmations.iter().any(|l| *l >= floor);
            let mut levels = vec![(
                "confirm-baseline",
                confirmations.into_iter().max().unwrap_or(0),
            )];
            let mut criteria = Vec::new();
            for (cn, c) in i.get("criteria").object() {
                let checked_by = c.get("checked_by").array();
                for o in checked_by {
                    let best = match_check(&ledger, name, cn, o, i, policy);
                    levels.push(("match-check", best));
                }
                // An obligation the project does not have is never passed.
                criteria.push(Criterion {
                    gate: c.get("gate").str().into(),
                    checks: checked_by
                        .iter()
                        .map(|o| (*statuses.get(o.str()).unwrap_or(&"unknown")).to_owned())
                        .collect(),
                });
            }
            let gates = |gate: &str| criteria.iter().filter(|c| c.gate == gate).count();
            let deferred_open = criteria
                .iter()
                .filter(|c| c.gate == "deferred" && !c.met())
                .count();
            let met = criteria.iter().filter(|c| c.met()).count();
            let status = intent::status(confirmed, &criteria.iter().collect::<Vec<_>>(), min);
            reports.insert(name, (status, hard_failure(&criteria)));
            intents_out.push((
                name.clone(),
                json::object(vec![
                    ("status", json::string(status)),
                    (
                        "gates",
                        json::object(vec![
                            ("hard", count(gates("hard"))),
                            ("soft", count(gates("soft"))),
                            ("deferred", count(gates("deferred"))),
                            ("deferred_open", count(deferred_open)),
                        ]),
                    ),
                    (
                        "score",
                        json::object(vec![("met", count(met)), ("of", count(criteria.len()))]),
                    ),
                    ("separation", separation(&levels)),
                ]),
            ));
        }
        let required: Vec<_> = list(policy.opt("required"))
            .iter()
            .map(|r| reports.get(r.str()).copied())
            .collect();
        out.push(json::object(vec![
            ("obligations", Value::Object(obligations_out)),
            ("intents", Value::Object(intents_out)),
            (
                "project",
                json::object(vec![("status", json::string(project(&required)))]),
            ),
            ("rejected", count(rejected)),
        ]));
    }
    out
}
#[cfg(test)]
mod tests {
    use super::*;
    fn value(s: &str) -> Value {
        json::parse(s.as_bytes()).unwrap()
    }
    #[test]
    fn baseline_sorts_sets() {
        let a = value(
            r#"{"owner":"o","children":["z","a"],"criteria":{"c":{"gate":"hard","checked_by":["b","a"]}}}"#,
        );
        let b = value(
            r#"{"owner":"o","children":["a","z"],"criteria":{"c":{"gate":"hard","checked_by":["a","b"]}}}"#,
        );
        assert_eq!(baseline(&a), baseline(&b));
        let soft = value(
            r#"{"owner":"o","children":["a","z"],"criteria":{"c":{"gate":"soft","checked_by":["a","b"]}}}"#,
        );
        assert_ne!(baseline(&a), baseline(&soft));
        // The worker is not part of what the owner confirms.
        let with_worker = value(
            r#"{"owner":"o","worker":"w","children":["a","z"],"criteria":{"c":{"gate":"hard","checked_by":["a","b"]}}}"#,
        );
        assert_eq!(baseline(&a), baseline(&with_worker));
    }
    #[test]
    fn records_that_count() {
        let pre = value(r#"{"inputs":{"targets":["a"]}}"#);
        let key = canonical::core_key(&pre).unwrap();
        let own = value(r#"{"writer":"me","platform":"p"}"#);
        let policy = value(r#"{"trusted_writers":["friend"]}"#);
        let record = |writer: &str, platform: &str, core_key: &str| {
            json::object(vec![
                ("obligation", json::string("o")),
                ("preimage", pre.clone()),
                ("core_key", json::string(core_key)),
                ("platform", json::string(platform)),
                ("writer", json::string(writer)),
            ])
        };
        let good = record("me", "p", &key);
        assert_eq!(stated_key(&good).as_deref(), Some(key.as_str()));
        assert!(counts(&good, "o", Some(&key), &own, &policy));
        assert!(counts(
            &record("friend", "p", &key),
            "o",
            Some(&key),
            &own,
            &policy
        ));
        assert!(!counts(
            &record("stranger", "p", &key),
            "o",
            Some(&key),
            &own,
            &policy
        ));
        assert!(!counts(
            &record("me", "q", &key),
            "o",
            Some(&key),
            &own,
            &policy
        ));
        assert!(!counts(&good, "other", Some(&key), &own, &policy));
        assert!(!counts(&good, "o", Some("sha256:00"), &own, &policy));
        assert!(!counts(&good, "o", None, &own, &policy));
        // A record that states another key than its preimage's is rejected, whatever the key.
        let wrong = record("me", "p", "sha256:00");
        assert_eq!(stated_key(&wrong), None);
        assert!(!counts(&wrong, "o", Some("sha256:00"), &own, &policy));
        // A preimage that cannot be keyed has no key to state.
        let unkeyable = json::object(vec![
            ("preimage", value(r#"{"inputs":{"targets":["b","a"]}}"#)),
            (
                "core_key",
                json::string(&canonical::identity(&value(
                    r#"{"inputs":{"targets":["b","a"]}}"#,
                ))),
            ),
        ]);
        assert_eq!(stated_key(&unkeyable), None);
        assert_eq!(stated_key(&value("{}")), None);
        assert!(!counts(&value("{}"), "o", Some(&key), &own, &policy));
    }
    fn act(kind: &str, result: &str, target: &str, actor: &str, worker: &str) -> (String, Value) {
        (
            "act".into(),
            value(&format!(
                r#"{{"kind":"{kind}","result":"{result}","target":"{target}","lineage":{{"intent":"i"}},
                    "actor":{{"id":"{actor}","session":"s2"}},"worker":{{"id":"{worker}","session":"s1"}}}}"#
            )),
        )
    }
    #[test]
    fn acts_for_an_intent() {
        let intent = value(
            r#"{"owner":"o","worker":"w","children":[],"criteria":{"c":{"gate":"hard","checked_by":["ob"]}}}"#,
        );
        let policy = value(r#"{"attestors":{},"makes":[]}"#);
        let base = baseline(&intent);
        let good = act("confirm-baseline", "agreed", &base, "o", "w");
        assert_eq!(level(&good.1, &policy, &intent), 1);
        let ledger = vec![
            good,
            act("confirm-baseline", "refused", &base, "o", "w"),
            act("confirm-baseline", "agreed", "sha256:00", "o", "w"),
            act("confirm-baseline", "agreed", &base, "someone", "w"),
            act("match-check", "agreed", &base, "o", "w"),
            ("evidence".into(), value("{}")),
            ("act".into(), value("{}")),
            // About another worker: it would confirm, at `self`.
            act("confirm-baseline", "agreed", &base, "o", "x"),
        ];
        assert_eq!(confirmations(&ledger, "i", &intent, &policy), [1, 0]);
        assert!(confirmations(&ledger, "j", &intent, &policy).is_empty());
        let ob = json::string("ob");
        assert_eq!(match_check(&ledger, "i", "c", &ob, &intent, &policy), 0);
        let target = canonical::identity(&value(
            r#"{"intent":"i","criterion":"c","obligation":"ob"}"#,
        ));
        let ledger = vec![
            act("match-check", "agreed", &target, "o", "x"),
            act("match-check", "agreed", &target, "checker", "w"),
            act("match-check", "refused", &target, "checker", "w"),
        ];
        assert_eq!(match_check(&ledger, "i", "c", &ob, &intent, &policy), 1);
        assert_eq!(match_check(&ledger, "i", "d", &ob, &intent, &policy), 0);
        assert_eq!(
            match_check(&ledger[..1], "i", "c", &ob, &intent, &policy),
            0
        );
    }
    #[test]
    fn separation_report() {
        let text = |levels: &[(&str, usize)]| json::encode(&separation(levels));
        assert_eq!(
            text(&[("confirm-baseline", 1), ("match-check", 1)]),
            r#"{"act":"confirm-baseline","apart_or_better":0,"of":2,"weakest":"helper"}"#
        );
        assert_eq!(
            text(&[
                ("confirm-baseline", 3),
                ("match-check", 2),
                ("match-check", 0)
            ]),
            r#"{"act":"match-check","apart_or_better":2,"of":3,"weakest":"self"}"#
        );
    }
    #[test]
    fn project_status() {
        assert_eq!(project(&[]), "nothing-required");
        assert_eq!(
            project(&[Some(("delivered", false)), Some(("fulfilled", false))]),
            "passed"
        );
        assert_eq!(
            project(&[Some(("delivered", false)), Some(("open", false))]),
            "unknown"
        );
        assert_eq!(
            project(&[Some(("open", true)), Some(("fulfilled", false))]),
            "failed"
        );
        // A required intent the project does not have is not delivered.
        assert_eq!(project(&[Some(("fulfilled", false)), None]), "unknown");
    }
    #[test]
    fn hard_failures() {
        let c = |gate: &str, check: &str| Criterion {
            gate: gate.into(),
            checks: vec![check.into()],
        };
        assert!(hard_failure(&[c("hard", "failed")]));
        assert!(hard_failure(&[c("soft", "passed"), c("hard", "conflict")]));
        assert!(!hard_failure(&[c("hard", "unknown"), c("soft", "failed")]));
        assert!(!hard_failure(&[c("deferred", "failed")]));
    }
    #[test]
    fn steps_with_nothing_to_act_on() {
        let scenario = value(
            r#"{"self":{"writer":"k","platform":"p"},
                "policy":{"min_hard_gates":1,"required":["i","missing"],"trusted_writers":[],"floors":{"confirm-baseline":"helper"},"attestors":{},"makes":[]},
                "obligations":{"ob":{"preimage":{"inputs":{}}}},
                "intents":{"i":{"owner":"o","worker":"w","children":[],"criteria":{"c":{"gate":"deferred","checked_by":[]},"d":{"gate":"hard","checked_by":["nowhere"]}}}},
                "steps":[{"do":{"change":{"obligation":"gone","preimage":{}}}},
                         {"do":{"set_gate":{"intent":"gone","criterion":"c","to":"hard"}}},
                         {"do":{"set_gate":{"intent":"i","criterion":"gone","to":"hard"}}},
                         {"do":{"append":{"kind":"other","body":{}}}},
                         {"do":{"append":{"kind":"evidence","body":{}}}}]}"#,
        );
        let results = run(&scenario);
        assert_eq!(results.len(), 5);
        let last = json::encode(&results[4]);
        assert_eq!(
            json::encode(&results[0]).replace(r#""rejected":0"#, ""),
            last.replace(r#""rejected":1"#, "")
        );
        let i = results[4].get("intents").get("i");
        assert_eq!(
            json::encode(i.get("gates")),
            r#"{"deferred":1,"deferred_open":1,"hard":1,"soft":0}"#
        );
        assert_eq!(json::encode(i.get("score")), r#"{"met":0,"of":2}"#);
        assert_eq!(results[4].get("project").get("status").str(), "unknown");
    }
}
