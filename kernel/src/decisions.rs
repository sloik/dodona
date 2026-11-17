use crate::json::{self, Value};
use std::collections::BTreeMap;
fn flagged(current: Option<&str>, recorded: &str) -> bool {
    current != Some(recorded)
}
pub fn run(input: &Value) -> Vec<Value> {
    let mut names: BTreeMap<String, String> = input
        .get("names")
        .object()
        .iter()
        .map(|(k, v)| (k.clone(), v.str().into()))
        .collect();
    let governed: Vec<String> = input
        .get("governs")
        .array()
        .iter()
        .map(|x| x.str().to_owned())
        .collect();
    let mut recorded = names.clone();
    input
        .get("steps")
        .array()
        .iter()
        .map(|step| {
            let a = step.get("do");
            if let Some(e) = a.opt("edit") {
                let name = e.get("name").str();
                if let Value::String(v) = e.get("to") {
                    names.insert(name.into(), v.clone());
                } else {
                    names.remove(name);
                }
            }
            if a.opt("review").is_some() {
                if governed.iter().all(|n| names.contains_key(n)) {
                    recorded = names.clone();
                }
            }
            json::object(vec![(
                "flagged",
                Value::Bool(
                    governed
                        .iter()
                        .any(|n| flagged(names.get(n).map(String::as_str), &recorded[n])),
                ),
            )])
        })
        .collect()
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rules() {
        assert!(!flagged(Some("a"), "a"));
        assert!(flagged(Some("b"), "a"));
        assert!(flagged(None, "a"));
    }
}
