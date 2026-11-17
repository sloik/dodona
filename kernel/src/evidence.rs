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
            let run = x.get("as").str();
            if in_flight(&attempts, run).is_none() {
                attempts.push(Attempt {
                    key: key(x.get("obligation").str(), obligations, &defs, &tool),
                    run: run.into(),
                    outcome: if up { "pending" } else { "unavailable" }.into(),
                });
            }
        }
        if let Some(x) = a.opt("complete") {
            if let Some(i) = in_flight(&attempts, x.get("run").str()) {
                attempts[i].outcome = x.get("verdict").str().into();
            }
        }
        if let Some(x) = a.opt("lose") {
            if let Some(i) = in_flight(&attempts, x.get("run").str()) {
                attempts[i].outcome = "error".into();
            }
        }
        let mut out = Vec::new();
        for (name, _) in obligations.object() {
            let k = key(name, obligations, &defs, &tool);
            let relevant: Vec<_> = attempts.iter().filter(|a| a.key == k).collect();
            let status = status(relevant.iter().map(|a| a.outcome.as_str()));
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

/// The run of that name that has started and not yet ended, if there is one.
fn in_flight(attempts: &[Attempt], run: &str) -> Option<usize> {
    attempts
        .iter()
        .position(|a| a.run == run && a.outcome == "pending")
}
/// The status of an obligation from the verdicts of the records that count for it.
/// Anything that is not a verdict, such as a run with no result, is passed over.
pub fn status<'a>(verdicts: impl IntoIterator<Item = &'a str>) -> &'static str {
    let (mut pass, mut fail) = (false, false);
    for verdict in verdicts {
        pass |= verdict == "passed";
        fail |= verdict == "failed";
    }
    match (pass, fail) {
        (true, true) => "conflict",
        (true, false) => "passed",
        (false, true) => "failed",
        _ => "unknown",
    }
}
pub fn states(input: &Value) -> Vec<Value> {
    let obligations = input.get("obligations");
    input
        .get("states")
        .array()
        .iter()
        .map(|state| {
            let mut out = Vec::new();
            for (name, obligation) in obligations.object() {
                let matches = |entry: &&Value| {
                    let inputs = entry.get("inputs");
                    let deps = obligation.get("depends_on").array();
                    entry.get("obligation").str() == name
                        && entry.get("tool").str() == state.get("tool").str()
                        && inputs.object().len() == deps.len()
                        && deps.iter().all(|d| {
                            match (inputs.opt(d.str()), state.get("definitions").opt(d.str())) {
                                (Some(a), Some(b)) => a.str() == b.str(),
                                _ => false,
                            }
                        })
                };
                let records: Vec<_> = state
                    .get("records")
                    .array()
                    .iter()
                    .filter(matches)
                    .collect();
                let status = status(records.iter().map(|r| r.get("verdict").str()));
                let pending =
                    status == "unknown" && state.get("running").array().iter().any(|r| matches(&r));
                out.push((
                    name.clone(),
                    json::object(vec![
                        ("status", json::string(status)),
                        ("pending", Value::Bool(pending)),
                    ]),
                ));
            }
            Value::Object(out)
        })
        .collect()
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn statuses() {
        assert_eq!(status([]), "unknown");
        assert_eq!(status(["pending", "error", "unavailable"]), "unknown");
        assert_eq!(status(["passed", "passed"]), "passed");
        assert_eq!(status(["failed", "error"]), "failed");
        assert_eq!(status(["passed", "failed"]), "conflict");
    }
    #[test]
    fn runs_in_flight() {
        let attempt = |run: &str, outcome: &str| Attempt {
            key: Key {
                obligation: "o".into(),
                tool: "t".into(),
                inputs: Vec::new(),
            },
            run: run.into(),
            outcome: outcome.into(),
        };
        let attempts = [
            attempt("a", "passed"),
            attempt("b", "unavailable"),
            attempt("a", "pending"),
        ];
        assert_eq!(in_flight(&attempts, "a"), Some(2));
        assert_eq!(in_flight(&attempts, "b"), None);
        assert_eq!(in_flight(&attempts, "c"), None);
    }
    fn statuses_after(steps: &str) -> Vec<String> {
        let input = format!(
            r#"{{"obligations":{{"o":{{"depends_on":["d"]}}}},"start":{{"definitions":{{"d":"1"}},"tool":"t","backend":"up"}},"steps":[{steps}]}}"#
        );
        run(&json::parse(input.as_bytes()).unwrap())
            .iter()
            .map(|r| {
                let o = r.get("o");
                o.opt("reason").unwrap_or(o.get("status")).str().to_owned()
            })
            .collect()
    }
    #[test]
    fn states_count_only_current_records() {
        let input = json::parse(
            br#"{"obligations":{"o":{"depends_on":["d"]},"q":{"depends_on":["d"]}},"states":[
                {"definitions":{"d":"2"},"tool":"t","running":[{"obligation":"q","inputs":{"d":"2"},"tool":"t"}],
                 "records":[{"obligation":"o","inputs":{"d":"2"},"tool":"t","verdict":"passed"},
                            {"obligation":"o","inputs":{"d":"1"},"tool":"t","verdict":"failed"},
                            {"obligation":"o","inputs":{"d":"2"},"tool":"old","verdict":"failed"}]},
                {"definitions":{"d":"1"},"tool":"t","running":[{"obligation":"o","inputs":{"d":"1"},"tool":"t"}],
                 "records":[{"obligation":"o","inputs":{"d":"1"},"tool":"t","verdict":"failed"},
                            {"obligation":"o","inputs":{"d":"1"},"tool":"t","verdict":"passed"}]}]}"#,
        )
        .unwrap();
        let got: Vec<String> = states(&input).iter().map(json::encode).collect();
        assert_eq!(
            got,
            [
                r#"{"o":{"pending":false,"status":"passed"},"q":{"pending":true,"status":"unknown"}}"#,
                r#"{"o":{"pending":false,"status":"conflict"},"q":{"pending":false,"status":"unknown"}}"#
            ]
        );
    }
    #[test]
    fn steps_out_of_turn() {
        let got = statuses_after(
            r#"{"do":{"complete":{"run":"j","verdict":"passed"}}},{"do":{"lose":{"run":"j"}}},
               {"do":{"submit":{"obligation":"o","as":"j"}}},{"do":{"submit":{"obligation":"o","as":"j"}}},
               {"do":{"complete":{"run":"j","verdict":"passed"}}},{"do":{"complete":{"run":"j","verdict":"failed"}}},
               {"do":{"submit":{"obligation":"o","as":"j"}}},{"do":{"lose":{"run":"j"}}}"#,
        );
        assert_eq!(
            got,
            [
                "never-run",
                "never-run",
                "pending",
                "pending",
                "passed",
                "passed",
                "passed",
                "passed"
            ]
        );
    }
}
