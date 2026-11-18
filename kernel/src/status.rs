use crate::{
    acts::{self, text},
    assurance, canonical, evidence,
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
    a.sort_by(|x, y| json::key_order(x.str(), y.str()));
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
/// A string inside an object inside the record, such as `actor.id`.
fn sub<'a>(r: &'a Value, field: &str, name: &str) -> Option<&'a str> {
    r.opt(field).and_then(|f| text(f, name))
}
/// The least separation at which an act of this kind counts: `self` if policy gives none.
fn floor(policy: &Value, kind: &str) -> usize {
    match policy.opt("floors").and_then(|f| f.opt(kind)) {
        None => 0,
        Some(Value::String(s)) => acts::rank(s).expect("a floor is not a separation level"),
        Some(_) => panic!("a floor is not a separation level"),
    }
}
/// The level an evidence record states, on the assurance scale. One that states
/// none, or something not on the scale, is `asserted`.
fn stated_level(body: &Value) -> usize {
    text(body, "level").and_then(assurance::rank).unwrap_or(1)
}
/// The level shown for an obligation from its status and the levels of the records that count for it.
fn obligation_level(status: &str, levels: impl Iterator<Item = usize>) -> usize {
    if status == "passed" {
        levels.max().unwrap_or(0)
    } else {
        0
    }
}
/// The level shown for a criterion: the weakest among its obligations, `none` if it has none.
fn criterion_level(levels: impl Iterator<Item = usize>) -> usize {
    levels.min().unwrap_or(0)
}
/// The level shown for an intent, and the criterion it rests on: the weakest among
/// all criteria, soft ones included, and the first criterion in sorted order at that level.
fn headline<'a>(criteria: &[(&'a str, &Criterion, usize)]) -> (usize, Option<&'a str>) {
    let level = criteria.iter().map(|(_, _, l)| *l).min().unwrap_or(0);
    let criterion = criteria
        .iter()
        .filter(|(_, _, l)| *l == level)
        .map(|(name, _, _)| *name)
        .min_by(|a, b| json::key_order(a, b));
    (level, criterion)
}
/// Agreed exceptions for the intent: how many count, and how many are below the floor.
fn exceptions(ledger: &Ledger, name: &str, intent: &Value, policy: &Value) -> (usize, usize) {
    let owner = text(intent, "owner");
    let floor = floor(policy, "grant-amendment");
    let (mut counted, mut below) = (0, 0);
    for r in agreed(ledger, "grant-amendment").filter(|r| sub(r, "lineage", "intent") == Some(name))
    {
        let by_owner = owner.is_some() && sub(r, "actor", "id") == owner;
        if by_owner && level(r, policy, intent) >= floor {
            counted += 1;
        } else {
            below += 1;
        }
    }
    (counted, below)
}
/// The level of an act record for an intent: graded as any act, but `self` when it is not about the intent's worker.
fn level(r: &Value, policy: &Value, intent: &Value) -> usize {
    let worker = sub(r, "worker", "id");
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
            sub(r, "lineage", "intent") == Some(name)
                && text(r, "target") == Some(base.as_str())
                && owner.is_some()
                && sub(r, "actor", "id") == owner
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
/// The gate a `set_gate` step names, if the project has that intent and criterion.
fn gate_of<'a>(intents: &'a mut Value, step: &Value) -> Option<&'a mut Value> {
    intents
        .opt_mut(step.text("intent")?)?
        .opt_mut("criteria")?
        .opt_mut(step.text("criterion")?)?
        .opt_mut("gate")
}
fn count(n: usize) -> Value {
    Value::Number(n as i64)
}
pub fn run(v: &Value) -> Vec<Value> {
    let mut obligations = v.get("obligations").clone();
    let mut intents = v.get("intents").clone();
    let policy = v.get("policy");
    let own = v.get("self");
    let floor = floor(policy, "confirm-baseline");
    let min = policy.get("min_hard_gates").number();
    let mut ledger: Vec<(String, Value)> = Vec::new();
    let mut out = Vec::new();
    for step in v.get("steps").array() {
        let a = step.get("do");
        // A record with a verdict that does not exist is not a record: appending it changes nothing.
        if let Some(x) = a.opt("append") {
            if let (Some(kind), Some(body)) = (x.text("kind"), x.opt("body")) {
                let verdict = body.text("verdict");
                if kind != "evidence" || verdict.is_some_and(|v| evidence::VERDICTS.contains(&v)) {
                    ledger.push((kind.into(), body.clone()));
                }
            }
        }
        // A change to an obligation, or a gate, that is not there has nothing to act on.
        if let Some(x) = a.opt("change") {
            let o = x.text("obligation").and_then(|o| obligations.opt_mut(o));
            let preimage = o.and_then(|o| o.opt_mut("preimage"));
            if let (Some(p), Some(to)) = (preimage, x.opt("preimage")) {
                *p = to.clone();
            }
        }
        if let Some(x) = a.opt("set_gate") {
            let to = x.text("to").filter(|g| intent::GATES.contains(g));
            if let (Some(g), Some(to)) = (gate_of(&mut intents, x), to) {
                *g = json::string(to);
            }
        }
        let evidence = || ledger.iter().filter(|(k, _)| k == "evidence");
        let rejected = evidence().filter(|(_, b)| stated_key(b).is_none()).count();
        let mut statuses: BTreeMap<&str, (&'static str, usize)> = BTreeMap::new();
        let mut obligations_out = Vec::new();
        for (name, o) in obligations.object() {
            let key = o.opt("preimage").and_then(|p| canonical::core_key(p).ok());
            let counting: Vec<&Value> = evidence()
                .map(|(_, b)| b)
                .filter(|b| counts(b, name, key.as_deref(), own, policy))
                .collect();
            let status = evidence::status(counting.iter().filter_map(|b| text(b, "verdict")));
            let level = obligation_level(status, counting.iter().map(|b| stated_level(b)));
            statuses.insert(name, (status, level));
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
            let mut shown = Vec::new();
            for (cn, c) in i.get("criteria").object() {
                let checked_by = c.get("checked_by").array();
                for o in checked_by {
                    let best = match_check(&ledger, name, cn, o, i, policy);
                    levels.push(("match-check", best));
                }
                // An obligation the project does not have is never passed, and shows nothing.
                let of = |o: &Value| *statuses.get(o.str()).unwrap_or(&("unknown", 0));
                criteria.push(Criterion {
                    gate: c.get("gate").str().into(),
                    checks: checked_by.iter().map(|o| of(o).0.to_owned()).collect(),
                });
                shown.push((
                    cn.as_str(),
                    criterion_level(checked_by.iter().map(|o| of(o).1)),
                ));
            }
            let shown: Vec<_> = shown
                .iter()
                .zip(&criteria)
                .map(|((name, level), c)| (*name, c, *level))
                .collect();
            let (shown_level, shown_criterion) = headline(&shown);
            let (counted, below_floor) = exceptions(&ledger, name, i, policy);
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
                    (
                        "shown",
                        json::object(vec![
                            ("level", json::string(assurance::SCALE[shown_level])),
                            (
                                "criterion",
                                shown_criterion.map_or(Value::Null, json::string),
                            ),
                        ]),
                    ),
                    (
                        "exceptions",
                        json::object(vec![
                            ("counted", count(counted)),
                            ("below_floor", count(below_floor)),
                        ]),
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
    fn levels_shown() {
        assert_eq!(stated_level(&value(r#"{"level":"bounded"}"#)), 4);
        assert_eq!(stated_level(&value(r#"{"level":"none"}"#)), 0);
        assert_eq!(stated_level(&value(r#"{"level":"made-up"}"#)), 1);
        assert_eq!(stated_level(&value(r#"{"level":5}"#)), 1);
        assert_eq!(stated_level(&value("{}")), 1);
        assert_eq!(obligation_level("passed", [2, 4, 1].into_iter()), 4);
        assert_eq!(obligation_level("passed", [].into_iter()), 0);
        for other in ["failed", "conflict", "unknown"] {
            assert_eq!(obligation_level(other, [5].into_iter()), 0);
        }
        assert_eq!(criterion_level([3, 2, 5].into_iter()), 2);
        assert_eq!(criterion_level([].into_iter()), 0);
        let c = |gate: &str| Criterion {
            gate: gate.into(),
            checks: Vec::new(),
        };
        let (hard, soft) = (c("hard"), c("soft"));
        assert_eq!(
            headline(&[("b", &hard, 3), ("a", &hard, 4)]),
            (3, Some("b"))
        );
        assert_eq!(
            headline(&[("b", &hard, 3), ("a", &soft, 3)]),
            (3, Some("a"))
        );
        assert_eq!(
            headline(&[("b", &hard, 5), ("a", &soft, 1)]),
            (1, Some("a"))
        );
        assert_eq!(headline(&[]), (0, None));
    }
    #[test]
    fn floors() {
        let policy = value(r#"{"floors":{"confirm-baseline":"apart"}}"#);
        assert_eq!(floor(&policy, "confirm-baseline"), 2);
        assert_eq!(floor(&policy, "grant-amendment"), 0);
        assert_eq!(floor(&value("{}"), "confirm-baseline"), 0);
    }
    #[test]
    fn exceptions_counted_and_not() {
        let intent = value(r#"{"owner":"o","worker":"w","children":[],"criteria":{}}"#);
        let policy = |floor: &str| {
            value(&format!(
                r#"{{"floors":{{"grant-amendment":"{floor}"}},"attestors":{{}},"makes":[]}}"#
            ))
        };
        let ledger = vec![
            act("grant-amendment", "agreed", "t", "o", "w"),
            act("grant-amendment", "refused", "t", "o", "w"),
            act("grant-amendment", "agreed", "t", "w", "w"),
            act("grant-amendment", "agreed", "t", "someone", "w"),
            act("grant-amendment", "agreed", "t", "o", "x"),
            act("confirm-baseline", "agreed", "t", "o", "w"),
            ("evidence".into(), value("{}")),
        ];
        assert_eq!(exceptions(&ledger, "i", &intent, &policy("helper")), (1, 3));
        assert_eq!(exceptions(&ledger, "i", &intent, &policy("self")), (2, 2));
        assert_eq!(exceptions(&ledger, "i", &intent, &policy("apart")), (0, 4));
        assert_eq!(exceptions(&ledger, "j", &intent, &policy("self")), (0, 0));
        assert_eq!(
            exceptions(&ledger[1..2], "i", &intent, &policy("self")),
            (0, 0)
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
                         {"do":{"set_gate":{"intent":"i","criterion":"c","to":"made-up"}}},
                         {"do":{"append":{"kind":"evidence","body":{"verdict":"made-up"}}}},
                         {"do":{"append":{"kind":7,"body":{}}}},
                         {"do":{"change":{"obligation":7,"preimage":{}}}},
                         {"do":{"append":{"kind":"evidence","body":{"verdict":"passed"}}}}]}"#,
        );
        let results = run(&scenario);
        assert_eq!(results.len(), 9);
        for r in &results[1..8] {
            assert_eq!(json::encode(r), json::encode(&results[0]));
        }
        let results = &results[4..];
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
