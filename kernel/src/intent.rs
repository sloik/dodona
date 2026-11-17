use crate::{
    acts,
    json::{self, Value},
};
use std::collections::BTreeMap;
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
        if let Some(a) = action.opt("check") {
            criteria.get_mut(a.get("criterion").str()).unwrap().checks =
                vec![a.get("status").str().into()]
        }
        if let Some(a) = action.opt("edit") {
            let gate = &mut criteria.get_mut(a.get("criterion").str()).unwrap().gate;
            if *gate != a.get("to").str() {
                *gate = a.get("to").str().into();
                confirmed = false;
            }
        }
        if let Some(a) = action.opt("amend") {
            let (effective, level) = grade(a, floor);
            if effective {
                criteria.get_mut(a.get("criterion").str()).unwrap().gate = a.get("to").str().into()
            }
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
                    let (effective, level) = grade(a, floor);
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
