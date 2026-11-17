use crate::json::{self, Value};
use std::collections::BTreeMap;
#[derive(Clone, PartialEq, Eq)]
struct Key {
    obligation: String,
    tool: String,
    inputs: Vec<String>,
}
struct Attempt {
    key: Key,
    run: String,
    outcome: String,
}
pub fn run(input: &Value) -> Vec<Value> {
    let obligations = input.get("obligations");
    let start = input.get("start");
    let mut defs: BTreeMap<String, String> = start
        .get("definitions")
        .object()
        .iter()
        .map(|(k, v)| (k.clone(), v.str().into()))
        .collect();
    let mut tool = start.get("tool").str().to_owned();
    let mut up = start.get("backend").str() == "up";
    let mut attempts: Vec<Attempt> = Vec::new();
    let mut results = Vec::new();
    for step in input.get("steps").array() {
        let a = step.get("do");
        if let Some(x) = a.opt("edit") {
            defs.insert(x.get("definition").str().into(), x.get("to").str().into());
        }
        if let Some(x) = a.opt("repin") {
            tool = x.get("to").str().into()
        }
        if let Some(x) = a.opt("backend") {
            up = x.get("to").str() == "up"
        }
        if let Some(x) = a.opt("submit") {
            let o = x.get("obligation").str();
            attempts.push(Attempt {
                key: key(o, obligations, &defs, &tool),
                run: x.get("as").str().into(),
                outcome: if up { "pending" } else { "unavailable" }.into(),
            });
        }
        if let Some(x) = a.opt("complete") {
            let attempt = attempts
                .iter_mut()
                .find(|a| a.run == x.get("run").str() && a.outcome == "pending")
                .unwrap();
            attempt.outcome = x.get("verdict").str().into()
        }
        if let Some(x) = a.opt("lose") {
            let attempt = attempts
                .iter_mut()
                .find(|a| a.run == x.get("run").str() && a.outcome == "pending")
                .unwrap();
            attempt.outcome = "error".into()
        }
        let mut out = Vec::new();
        for (name, _) in obligations.object() {
            let k = key(name, obligations, &defs, &tool);
            let relevant: Vec<_> = attempts.iter().filter(|a| a.key == k).collect();
            let pass = relevant.iter().any(|a| a.outcome == "passed");
            let fail = relevant.iter().any(|a| a.outcome == "failed");
            let status = match (pass, fail) {
                (true, true) => "conflict",
                (true, false) => "passed",
                (false, true) => "failed",
                _ => "unknown",
            };
            let mut fields = vec![("status", json::string(status))];
            if status == "unknown" {
                let reason = if relevant.iter().any(|a| a.outcome == "pending") {
                    "pending"
                } else {
                    relevant
                        .last()
                        .map(|a| a.outcome.as_str())
                        .unwrap_or("never-run")
                };
                fields.push(("reason", json::string(reason)))
            }
            out.push((name.clone(), json::object(fields)));
        }
        results.push(Value::Object(out));
    }
    results
}
fn key(name: &str, obligations: &Value, defs: &BTreeMap<String, String>, tool: &str) -> Key {
    Key {
        obligation: name.into(),
        tool: tool.into(),
        inputs: obligations
            .get(name)
            .get("depends_on")
            .array()
            .iter()
            .map(|d| defs[d.str()].clone())
            .collect(),
    }
}
