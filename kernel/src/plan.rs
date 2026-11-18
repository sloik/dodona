use crate::json::{self, Value};
use std::collections::{BTreeMap, BTreeSet};
fn closure(name: &str, defs: &Value, seen: &mut BTreeSet<String>) {
    if seen.insert(name.into()) {
        for d in defs.get(name).get("depends_on").array() {
            closure(d.str(), defs, seen);
        }
    }
}
fn key(
    name: &str,
    input: &Value,
    content: &BTreeMap<String, String>,
    tools: &BTreeMap<String, String>,
) -> String {
    let o = input.get("obligations").get(name);
    let mut parts = Vec::new();
    if let Some(producer) = o.opt("artifact_of") {
        parts.push(key(producer.str(), input, content, tools));
    }
    if let Some(targets) = o.opt("targets") {
        let defs = input.get("definitions");
        let mut names = BTreeSet::new();
        for t in targets.array() {
            closure(t.str(), defs, &mut names);
        }
        if input.get("granularity").str() == "file" {
            let files: BTreeSet<_> = names
                .iter()
                .map(|n| defs.get(n).get("file").str().to_owned())
                .collect();
            for (n, d) in defs.object() {
                if files.contains(d.get("file").str()) {
                    names.insert(n.clone());
                }
            }
        }
        for n in names {
            parts.push(format!("{}:{}:{}", n.len(), n, content[&n]));
        }
    }
    if let Some(t) = o.opt("tool") {
        parts.push(tools[t.str()].clone());
    }
    json::encode(&Value::Array(
        parts.iter().map(|s| json::string(s)).collect(),
    ))
}
fn planned(
    input: &Value,
    content: &BTreeMap<String, String>,
    tools: &BTreeMap<String, String>,
    done: &BTreeSet<(String, String)>,
) -> Vec<String> {
    let mut plan: Vec<_> = input
        .get("obligations")
        .object()
        .iter()
        .filter(|(name, _)| !done.contains(&(name.clone(), key(name, input, content, tools))))
        .map(|(name, _)| name.clone())
        .collect();
    plan.sort();
    plan
}
/// Whether following `artifact_of` from every obligation comes to an end.
fn chains_end(obligations: &Value) -> bool {
    obligations.object().iter().all(|(name, _)| {
        let mut at = name.as_str();
        for _ in 0..obligations.object().len() {
            match obligations.opt(at).and_then(|o| o.opt("artifact_of")) {
                Some(Value::String(next)) => at = next,
                _ => return true,
            }
        }
        false
    })
}
pub fn run(input: &Value) -> Vec<Value> {
    assert!(
        chains_end(input.get("obligations")),
        "an obligation is an artifact of itself"
    );
    let start = input.get("start");
    let mut content: BTreeMap<String, String> = start
        .get("content")
        .object()
        .iter()
        .map(|(k, v)| (k.clone(), v.str().into()))
        .collect();
    let mut tools: BTreeMap<String, String> = start
        .get("tools")
        .object()
        .iter()
        .map(|(k, v)| (k.clone(), v.str().into()))
        .collect();
    let mut done = BTreeSet::new();
    input
        .get("steps")
        .array()
        .iter()
        .map(|step| {
            let a = step.get("do");
            // An edit or repin of something the scenario does not have changes nothing.
            if let Some(e) = a.opt("edit") {
                let definition = e.text("definition").and_then(|d| content.get_mut(d));
                if let (Some(content), Some(to)) = (definition, e.text("to")) {
                    *content = to.into();
                }
            }
            if let Some(r) = a.opt("repin") {
                let tool = r.text("tool").and_then(|t| tools.get_mut(t));
                if let (Some(tool), Some(to)) = (tool, r.text("to")) {
                    *tool = to.into();
                }
            }
            // Running an obligation the scenario does not have runs nothing.
            let mut ran = a.opt("run").map(|_| false);
            let named = a.opt("run").and_then(|r| r.text("obligation"));
            let known = named.and_then(|n| Some((n, input.get("obligations").opt(n)?)));
            if let Some((n, o)) = known {
                let ready = o
                    .opt("artifact_of")
                    .map(|p| {
                        done.contains(&(p.str().to_owned(), key(p.str(), input, &content, &tools)))
                    })
                    .unwrap_or(true);
                let go = ready
                    && planned(input, &content, &tools, &done)
                        .iter()
                        .any(|p| p == n);
                if go {
                    done.insert((n.into(), key(n, input, &content, &tools)));
                }
                ran = Some(go);
            }
            let mut result = vec![(
                "plan",
                Value::Array(
                    planned(input, &content, &tools, &done)
                        .iter()
                        .map(|s| json::string(s))
                        .collect(),
                ),
            )];
            if let Some(r) = ran {
                result.push(("ran", Value::Bool(r)));
            }
            json::object(result)
        })
        .collect()
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn dependencies() {
        let defs = json::parse(
            br#"{"a":{"depends_on":["b"]},"b":{"depends_on":["c"]},"c":{"depends_on":[]}}"#,
        )
        .unwrap();
        let mut seen = BTreeSet::new();
        closure("a", &defs, &mut seen);
        assert_eq!(seen.len(), 3);
    }
    #[test]
    fn artifact_chains() {
        let ok =
            json::parse(br#"{"a":{"targets":[]},"b":{"artifact_of":"a"},"c":{"artifact_of":"b"}}"#)
                .unwrap();
        assert!(chains_end(&ok));
        let own = json::parse(br#"{"a":{"artifact_of":"a"}}"#).unwrap();
        assert!(!chains_end(&own));
        let ring = json::parse(br#"{"a":{"artifact_of":"b"},"b":{"artifact_of":"a"}}"#).unwrap();
        assert!(!chains_end(&ring));
    }
    #[test]
    fn keys_and_planning() {
        let input = json::parse(br#"{"granularity":"file","definitions":{"a":{"depends_on":["b"],"file":"one"},"b":{"depends_on":[],"file":"two"},"c":{"depends_on":[],"file":"two"}},"obligations":{"build":{"targets":["a"],"tool":"cc"},"test":{"artifact_of":"build","tool":"runner"}}}"#).unwrap();
        let mut content = BTreeMap::from([
            ("a".into(), "1".into()),
            ("b".into(), "1".into()),
            ("c".into(), "1".into()),
        ]);
        let mut tools = BTreeMap::from([("cc".into(), "1".into()), ("runner".into(), "1".into())]);
        let original = key("test", &input, &content, &tools);
        let mut done = BTreeSet::new();
        assert_eq!(planned(&input, &content, &tools, &done).len(), 2);
        done.insert(("test".into(), original.clone()));
        assert_eq!(planned(&input, &content, &tools, &done), vec!["build"]);
        content.insert("c".into(), "2".into());
        assert_ne!(key("test", &input, &content, &tools), original);
        content.insert("c".into(), "1".into());
        assert_eq!(key("test", &input, &content, &tools), original);
        tools.insert("cc".into(), "2".into());
        assert_ne!(key("test", &input, &content, &tools), original);
    }
}
