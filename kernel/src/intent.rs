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
            let (effective, level) = grade(a, floor);
            if effective {
                criteria.get_mut(a.get("criterion").str()).unwrap().0 = a.get("to").str().into()
            }
            amendment = Some(json::object(vec![
                ("takes_effect", Value::Bool(effective)),
                ("level", json::string(level)),
            ]));
        }
        let status = status(confirmed, &criteria, min);
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

fn grade(a: &Value, floor: usize) -> (bool, &str) {
    let owner = a.get("by").str() == "owner";
    let level = if owner {
        a.opt("separation").map(Value::str).unwrap_or("self")
    } else {
        "self"
    };
    (owner && rank(level) >= floor, level)
}
fn status(
    confirmed: bool,
    criteria: &BTreeMap<String, (String, String)>,
    min: i64,
) -> &'static str {
    if !confirmed {
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
            let criteria = state
                .get("criteria")
                .object()
                .iter()
                .map(|(k, v)| {
                    (
                        k.clone(),
                        (v.get("gate").str().into(), v.get("check").str().into()),
                    )
                })
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
                        &criteria,
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
        let mut c = BTreeMap::new();
        c.insert("c".into(), ("hard".into(), "unknown".into()));
        assert_eq!(status(false, &c, 1), "draft");
        assert_eq!(status(true, &c, 2), "unguarded");
        assert_eq!(status(true, &c, 1), "open");
        c.get_mut("c").unwrap().1 = "passed".into();
        assert_eq!(status(true, &c, 1), "fulfilled");
        c.insert("d".into(), ("deferred".into(), "unknown".into()));
        assert_eq!(status(true, &c, 1), "delivered");
    }
    #[test]
    fn exception_grade() {
        let a = json::parse(br#"{"by":"owner","separation":"helper"}"#).unwrap();
        assert_eq!(grade(&a, rank("helper")), (true, "helper"));
        assert_eq!(grade(&a, rank("apart")), (false, "helper"));
        let b = json::parse(br#"{"by":"worker","separation":"credentialed"}"#).unwrap();
        assert_eq!(grade(&b, 0), (false, "self"));
    }
}
