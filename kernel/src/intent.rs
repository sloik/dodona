use crate::json::{self, Value};
use std::collections::BTreeMap;
pub fn run(input: &Value) -> Vec<Value> {
    let mut criteria: BTreeMap<String, (String, String)> = input
        .get("criteria")
        .object()
        .iter()
        .map(|(k, v)| (k.clone(), (v.get("gate").str().into(), "unknown".into())))
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
            criteria.get_mut(a.get("criterion").str()).unwrap().1 = a.get("status").str().into()
        }
        if let Some(a) = action.opt("edit") {
            criteria.get_mut(a.get("criterion").str()).unwrap().0 = a.get("to").str().into();
            confirmed = false
        }
        if let Some(a) = action.opt("amend") {
            let owner = a.get("by").str() == "owner";
            let level = if owner {
                a.opt("separation").map(Value::str).unwrap_or("self")
            } else {
                "self"
            };
            let effective = owner && rank(level) >= floor;
            if effective {
                criteria.get_mut(a.get("criterion").str()).unwrap().0 = a.get("to").str().into()
            }
            amendment = Some(json::object(vec![
                ("takes_effect", Value::Bool(effective)),
                ("level", json::string(level)),
            ]));
        }
        let status = if !confirmed {
            "draft"
        } else if (criteria.values().filter(|(g, _)| g == "hard").count() as i64) < min {
            "unguarded"
        } else if criteria.values().any(|(g, s)| g == "hard" && s != "passed") {
            "open"
        } else if criteria
            .values()
            .any(|(g, s)| g == "deferred" && s != "passed")
        {
            "delivered"
        } else {
            "fulfilled"
        };
        let mut result = vec![("status", json::string(status))];
        if let Some(a) = amendment {
            result.push(("amendment", a))
        }
        results.push(json::object(result));
    }
    results
}
fn rank(s: &str) -> usize {
    [
        "self",
        "helper",
        "apart",
        "tested",
        "cross-make",
        "credentialed",
    ]
    .iter()
    .position(|x| *x == s)
    .unwrap()
}
