use crate::json::{self, Value};
use std::collections::{BTreeMap, BTreeSet};
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
    // The names the scenario has. One that has gone can come back; no other can appear.
    let known: BTreeSet<String> = names.keys().cloned().collect();
    let mut recorded = names.clone();
    input
        .get("steps")
        .array()
        .iter()
        .map(|step| {
            let a = step.get("do");
            if let Some(e) = a.opt("edit") {
                // Only a name the scenario has can be edited: to new content, or to null when it goes.
                let name = e.text("name").filter(|n| known.contains(*n));
                match (name, e.opt("to")) {
                    (Some(name), Some(Value::String(v))) => {
                        names.insert(name.into(), v.clone());
                    }
                    (Some(name), Some(Value::Null)) => {
                        names.remove(name);
                    }
                    _ => (),
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
        let input = json::parse(
            br#"{"names":{"n":"1","m":"1"},"governs":["n"],"steps":[
                {"do":{"edit":{"name":"gone","to":"2"}}},{"do":{"edit":{"name":"n","to":7}}},
                {"do":{"edit":{"name":7,"to":"2"}}},{"do":{"review":{}}},
                {"do":{"edit":{"name":"n","to":null}}},{"do":{"review":{}}},{"do":{"edit":{"name":"n","to":"1"}}},
                {"do":{"edit":{"name":"m","to":null}}},{"do":{"review":{}}},{"do":{"edit":{"name":"m","to":"2"}}},
                {"do":{"edit":{"name":"n","to":"3"}}}]}"#,
        )
        .unwrap();
        let got: Vec<String> = run(&input).iter().map(json::encode).collect();
        let (no, yes) = (r#"{"flagged":false}"#, r#"{"flagged":true}"#);
        assert_eq!(got, [no, no, no, no, yes, yes, no, no, no, no, yes]);
    }
}
