use crate::{
    acts,
    json::{self, Value},
};
use std::collections::BTreeMap;
/// The gates a criterion can have.
pub const GATES: [&str; 3] = ["hard", "soft", "deferred"];
/// The gate a status report counts a criterion under. One that is not exactly
/// a gate counts as `hard`, so a mistake in writing it can only make delivery harder.
pub fn gate_as_read(gate: Option<&Value>) -> &'static str {
    match gate {
        Some(Value::String(g)) => GATES.iter().find(|x| *x == g).copied().unwrap_or("hard"),
        _ => "hard",
    }
}
/// What the check behind a criterion can say.
pub const CHECKS: [&str; 4] = ["unknown", "passed", "failed", "conflict"];
/// A criterion as the status rule sees it: its gate, and the status of each check behind it.
pub struct Criterion {
    pub gate: String,
    pub checks: Vec<String>,
}
impl Criterion {
    fn one(gate: &str, check: &str) -> Criterion {
        Criterion {
            gate: gate.into(),
            checks: vec![check.into()],
        }
    }
    /// Some check behind it is not passed.
    fn lacking(&self) -> bool {
        self.checks.iter().any(|s| s != "passed")
    }
    /// It has at least one check and every one is passed.
    pub fn met(&self) -> bool {
        !self.checks.is_empty() && !self.lacking()
    }
}
pub fn run(input: &Value) -> Vec<Value> {
    let mut criteria: BTreeMap<String, Criterion> = input
        .get("criteria")
        .object()
        .iter()
        .map(|(k, v)| (k.clone(), Criterion::one(v.get("gate").str(), "unknown")))
        .collect();
    let policy = input.get("policy");
    let floor = rank(policy.get("exception_separation").str());
    let min = policy.get("min_hard_gates").number();
    let mut confirmed = false;
    let mut results = Vec::new();
    for step in input.get("steps").array() {
        let action = step.get("do");
        let mut amendment = None;
        if action.opt("confirm").is_some() {
            confirmed = true
        }
        // A step that names a criterion the intent does not have, or carries a
        // gate, status or level that does not exist, changes nothing.
        if let Some(a) = action.opt("check") {
            let status = a.text("status").filter(|s| CHECKS.contains(s));
            if let (Some(c), Some(status)) = (named(&mut criteria, a), status) {
                c.checks = vec![status.into()];
            }
        }
        if let Some(a) = action.opt("edit") {
            if let (Some(c), Some(to)) = (named(&mut criteria, a), gate(a)) {
                if c.gate != to {
                    c.gate = to.into();
                    confirmed = false;
                }
            }
        }
        if let Some(a) = action.opt("amend") {
            let (effective, level) = match (named(&mut criteria, a), gate(a)) {
                (Some(c), Some(to)) => {
                    let (effective, level) = judged(a, floor);
                    if effective {
                        c.gate = to.into();
                    }
                    (effective, level)
                }
                _ => (false, "self"),
            };
            amendment = Some(json::object(vec![
                ("takes_effect", Value::Bool(effective)),
                ("level", json::string(level)),
            ]));
        }
        let status = status(confirmed, &criteria.values().collect::<Vec<_>>(), min);
        let mut result = vec![("status", json::string(status))];
        if let Some(a) = amendment {
            result.push(("amendment", a))
        }
        results.push(json::object(result));
    }
    results
}
/// The criterion a step names, if the intent has it.
fn named<'a>(
    criteria: &'a mut BTreeMap<String, Criterion>,
    step: &Value,
) -> Option<&'a mut Criterion> {
    criteria.get_mut(step.text("criterion")?)
}
/// The gate a step sets, if it is one.
fn gate(step: &Value) -> Option<&str> {
    step.text("to").filter(|g| GATES.contains(g))
}
/// Whether a request for an exception says who grants it, and claims nothing that does not exist.
fn well_formed(a: &Value) -> bool {
    let absent_or = |field: &str, allowed: &dyn Fn(&str) -> bool| match a.opt(field) {
        None => true,
        Some(Value::String(s)) => allowed(s),
        Some(_) => false,
    };
    matches!(a.text("by"), Some("owner" | "worker"))
        && absent_or("claims", &|s| acts::rank(s).is_some())
        && absent_or("source", &|s| s == "declared" || s == "attested")
}
/// Whether an exception takes effect, and the level granted. One that is not well formed has no effect.
fn judged(a: &Value, floor: usize) -> (bool, &str) {
    if well_formed(a) {
        grade(a, floor)
    } else {
        (false, "self")
    }
}
fn rank(s: &str) -> usize {
    acts::rank(s).expect("not a separation level")
}

fn grade(a: &Value, floor: usize) -> (bool, &str) {
    let owner = a.get("by").str() == "owner";
    let level = if owner {
        {
            let claim = a.opt("claims").map(Value::str).unwrap_or("self");
            let cap = if a.opt("source").map(Value::str).unwrap_or("declared") == "attested" {
                "cross-make"
            } else {
                "helper"
            };
            if rank(claim) > rank(cap) {
                cap
            } else {
                claim
            }
        }
    } else {
        "self"
    };
    (owner && rank(level) >= floor, level)
}
/// The status of an intent: the one rule, for intent scenarios and for status scenarios.
/// In intent scenarios every criterion has exactly one check, so `uncovered` never applies.
pub fn status(confirmed: bool, criteria: &[&Criterion], min: i64) -> &'static str {
    let hard = criteria.iter().filter(|c| c.gate == "hard").count() as i64;
    let lacking = |gate: &str| criteria.iter().any(|c| c.gate == gate && c.lacking());
    if !confirmed {
        "draft"
    } else if criteria.iter().any(|c| c.checks.is_empty()) {
        "uncovered"
    } else if hard < min.max(1) {
        "unguarded"
    } else if lacking("hard") {
        "open"
    } else if lacking("deferred") {
        "delivered"
    } else {
        "fulfilled"
    }
}
pub fn states(input: &Value) -> Vec<Value> {
    let policy = input.get("policy");
    let floor = rank(policy.get("exception_separation").str());
    input
        .get("states")
        .array()
        .iter()
        .map(|state| {
            let criteria: Vec<Criterion> = state
                .get("criteria")
                .object()
                .iter()
                .map(|(_, v)| Criterion::one(v.get("gate").str(), v.get("check").str()))
                .collect();
            let confirmed = matches!(state.get("confirmed"), Value::Bool(true));
            let amendments = state
                .get("amendments")
                .array()
                .iter()
                .map(|a| {
                    let (effective, level) = judged(a, floor);
                    json::object(vec![
                        ("takes_effect", Value::Bool(effective)),
                        ("level", json::string(level)),
                    ])
                })
                .collect();
            json::object(vec![
                (
                    "status",
                    json::string(status(
                        confirmed,
                        &criteria.iter().collect::<Vec<_>>(),
                        policy.get("min_hard_gates").number(),
                    )),
                ),
                ("amendments", Value::Array(amendments)),
            ])
        })
        .collect()
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn intent_status() {
        let mut c = vec![Criterion::one("hard", "unknown")];
        let of =
            |c: &[Criterion], confirmed, min| status(confirmed, &c.iter().collect::<Vec<_>>(), min);
        assert_eq!(of(&c, false, 1), "draft");
        assert_eq!(of(&c, true, 2), "unguarded");
        assert_eq!(of(&c, true, 1), "open");
        c[0].checks = vec!["passed".into()];
        assert_eq!(of(&c, true, 1), "fulfilled");
        assert_eq!(of(&c, true, 0), "fulfilled");
        c.push(Criterion::one("soft", "failed"));
        assert_eq!(of(&c, true, 1), "fulfilled");
        assert_eq!(of(&c, true, 2), "unguarded");
        c.push(Criterion::one("deferred", "unknown"));
        assert_eq!(of(&c, true, 1), "delivered");
        c[2].checks.clear();
        assert_eq!(of(&c, true, 1), "uncovered");
        assert_eq!(of(&[], true, 0), "unguarded");
    }
    #[test]
    fn unreadable_gates() {
        let read = |text: &str| gate_as_read(Some(&json::parse(text.as_bytes()).unwrap()));
        assert_eq!(read(r#""hard""#), "hard");
        assert_eq!(read(r#""soft""#), "soft");
        assert_eq!(read(r#""deferred""#), "deferred");
        for odd in [
            r#""Hard""#,
            r#""soft ""#,
            "\"so\u{200b}ft\"",
            r#""""#,
            "7",
            "null",
        ] {
            assert_eq!(read(odd), "hard", "{odd}");
        }
        assert_eq!(gate_as_read(None), "hard");
    }
    #[test]
    fn met_needs_a_check() {
        assert!(Criterion::one("hard", "passed").met());
        assert!(!Criterion::one("hard", "unknown").met());
        let mut c = Criterion::one("deferred", "passed");
        c.checks.push("conflict".into());
        assert!(!c.met());
        c.checks.clear();
        assert!(!c.met());
    }
    #[test]
    fn states_use_the_same_rules() {
        let input = json::parse(
            br#"{"policy":{"exception_separation":"helper","min_hard_gates":0},"states":[
                {"confirmed":true,"criteria":{"c":{"gate":"soft","check":"passed"}},
                 "amendments":[{"by":"owner","claims":"apart"},{"by":"worker","claims":"apart"}]},
                {"confirmed":true,"criteria":{"c":{"gate":"hard","check":"passed"},"d":{"gate":"deferred","check":"failed"}},"amendments":[]}]}"#,
        )
        .unwrap();
        let got: Vec<String> = states(&input).iter().map(json::encode).collect();
        assert_eq!(
            got,
            [
                r#"{"amendments":[{"level":"helper","takes_effect":true},{"level":"self","takes_effect":false}],"status":"unguarded"}"#,
                r#"{"amendments":[],"status":"delivered"}"#
            ]
        );
    }
    #[test]
    fn steps_that_name_nothing() {
        let input = json::parse(
            br#"{"criteria":{"c":{"gate":"hard"}},"policy":{"exception_separation":"self","min_hard_gates":1},"steps":[
                {"do":{"confirm":{}}},{"do":{"check":{"criterion":"c","status":"passed"}}},
                {"do":{"check":{"criterion":"gone","status":"failed"}}},{"do":{"check":{"criterion":"c","status":"made-up"}}},
                {"do":{"edit":{"criterion":"gone","to":"soft"}}},{"do":{"edit":{"criterion":"c","to":"made-up"}}},
                {"do":{"edit":{"criterion":7,"to":"soft"}}},
                {"do":{"amend":{"criterion":"gone","to":"soft","by":"owner"}}},
                {"do":{"amend":{"criterion":"c","to":"made-up","by":"owner"}}},
                {"do":{"amend":{"criterion":"c","to":"soft","by":"nobody"}}},
                {"do":{"amend":{"criterion":"c","to":"soft","by":"owner","claims":"made-up"}}},
                {"do":{"amend":{"criterion":"c","to":"soft","by":"owner","source":"made-up"}}},
                {"do":{"amend":{"criterion":"c","to":"soft","by":"owner"}}}]}"#,
        )
        .unwrap();
        let got = run(&input);
        for r in &got[1..12] {
            assert_eq!(r.get("status").str(), "fulfilled");
        }
        for r in &got[7..12] {
            assert_eq!(
                json::encode(r.get("amendment")),
                r#"{"level":"self","takes_effect":false}"#
            );
        }
        assert_eq!(got[12].get("status").str(), "unguarded");
        assert!(!well_formed(
            &json::parse(br#"{"by":"owner","claims":7}"#).unwrap()
        ));
        assert!(well_formed(
            &json::parse(br#"{"by":"worker","claims":"apart","source":"attested"}"#).unwrap()
        ));
    }
    #[test]
    fn exception_grade() {
        let a = json::parse(br#"{"by":"owner","claims":"helper"}"#).unwrap();
        assert_eq!(grade(&a, rank("helper")), (true, "helper"));
        assert_eq!(grade(&a, rank("apart")), (false, "helper"));
        let declared = json::parse(br#"{"by":"owner","claims":"credentialed"}"#).unwrap();
        assert_eq!(grade(&declared, rank("apart")), (false, "helper"));
        let attested =
            json::parse(br#"{"by":"owner","claims":"credentialed","source":"attested"}"#).unwrap();
        assert_eq!(grade(&attested, rank("cross-make")), (true, "cross-make"));
        let absent = json::parse(br#"{"by":"owner"}"#).unwrap();
        assert_eq!(grade(&absent, rank("self")), (true, "self"));
        let b = json::parse(br#"{"by":"worker","claims":"credentialed"}"#).unwrap();
        assert_eq!(grade(&b, 0), (false, "self"));
    }
}
