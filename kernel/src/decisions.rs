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
    let governed = input.get("governs").str();
    let mut recorded = names[governed].clone();
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
                if let Some(v) = names.get(governed) {
                    recorded = v.clone();
                }
            }
            json::object(vec![(
                "flagged",
                Value::Bool(flagged(names.get(governed).map(String::as_str), &recorded)),
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
