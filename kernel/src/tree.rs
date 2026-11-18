use crate::{
    intent,
    json::{self, Value},
};
use std::collections::BTreeMap;
fn status(
    confirmed: bool,
    root: &(String, String),
    children: &BTreeMap<String, (String, String)>,
    min: i64,
) -> &'static str {
    if !confirmed {
        "draft"
    } else if (std::iter::once(root)
        .chain(children.values())
        .filter(|(g, _)| g == "hard")
        .count() as i64)
        < min
    {
        "unguarded"
    } else if (root.0 == "hard" && root.1 != "passed")
        || children.values().any(|(g, s)| g != "hard" || s != "passed")
    {
        "open"
    } else {
        "delivered"
    }
}
/// The gate a step gives under `field`, if it is one a tree node can have.
fn gate<'a>(step: &'a Value, field: &str) -> Option<&'a str> {
    step.text(field).filter(|g| *g == "hard" || *g == "soft")
}
/// The gate and check of the root or of a child, if that node is there.
fn node<'a>(
    root: &'a mut (String, String),
    children: &'a mut BTreeMap<String, (String, String)>,
    name: &str,
) -> Option<&'a mut (String, String)> {
    if name == "root" {
        Some(root)
    } else {
        children.get_mut(name)
    }
}
pub fn run(input: &Value) -> Vec<Value> {
    let mut root = (
        input.get("root").get("gate").str().to_owned(),
        "unknown".to_owned(),
    );
    let mut children: BTreeMap<String, (String, String)> = input
        .get("children")
        .object()
        .iter()
        .map(|(k, v)| (k.clone(), (v.get("gate").str().into(), "unknown".into())))
        .collect();
    let min = input.get("policy").get("min_hard_gates").number().max(1);
    let mut confirmed = false;
    input
        .get("steps")
        .array()
        .iter()
        .map(|step| {
            let a = step.get("do");
            if a.opt("confirm").is_some() {
                confirmed = true;
            }
            if let Some(c) = a.opt("check") {
                // A check of a child that is not there has nothing to act on.
                let status = c.text("status").filter(|s| intent::CHECKS.contains(s));
                let node = c
                    .text("node")
                    .and_then(|n| node(&mut root, &mut children, n));
                if let (Some(node), Some(status)) = (node, status) {
                    node.1 = status.into();
                }
            }
            if let Some(e) = a.opt("edit") {
                let node = e
                    .text("node")
                    .and_then(|n| node(&mut root, &mut children, n));
                if let (Some(node), Some(to)) = (node, gate(e, "to")) {
                    if node.0 != to {
                        node.0 = to.into();
                        confirmed = false;
                    }
                }
            }
            if let Some(r) = a.opt("remove") {
                if r.text("child").and_then(|c| children.remove(c)).is_some() {
                    confirmed = false;
                }
            }
            if let Some(add) = a.opt("add") {
                if let (Some(child), Some(gate)) = (add.text("child"), gate(add, "gate")) {
                    if child != "root" && !children.contains_key(child) {
                        children.insert(child.into(), (gate.into(), "unknown".into()));
                        confirmed = false;
                    }
                }
            }
            json::object(vec![(
                "status",
                json::string(status(confirmed, &root, &children, min)),
            )])
        })
        .collect()
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rules() {
        let root = ("hard".into(), "passed".into());
        let mut c = BTreeMap::new();
        assert_eq!(status(false, &root, &c, 1), "draft");
        assert_eq!(status(true, &root, &c, 2), "unguarded");
        c.insert("a".into(), ("soft".into(), "passed".into()));
        assert_eq!(status(true, &root, &c, 1), "open");
        c.get_mut("a").unwrap().0 = "hard".into();
        assert_eq!(status(true, &root, &c, 1), "delivered");
        let mut root = root;
        assert!(node(&mut root, &mut c, "root").is_some());
        assert!(node(&mut root, &mut c, "a").is_some());
        assert!(node(&mut root, &mut c, "gone").is_none());
        let input = json::parse(
            br#"{"root":{"gate":"hard"},"children":{"a":{"gate":"hard"}},"policy":{"min_hard_gates":1},"steps":[
                {"do":{"check":{"node":"root","status":"passed"}}},{"do":{"check":{"node":"a","status":"passed"}}},
                {"do":{"confirm":{}}},
                {"do":{"check":{"node":"gone","status":"failed"}}},{"do":{"check":{"node":"a","status":"made-up"}}},
                {"do":{"edit":{"node":"gone","to":"soft"}}},{"do":{"edit":{"node":"a","to":"deferred"}}},
                {"do":{"remove":{"child":"gone"}}},{"do":{"add":{"child":"b","gate":"made-up"}}},
                {"do":{"add":{"child":"root","gate":"hard"}}},{"do":{"add":{"child":7,"gate":"hard"}}},
                {"do":{"add":{"child":"b","gate":"soft"}}}]}"#,
        )
        .unwrap();
        let got: Vec<String> = run(&input)
            .iter()
            .map(|r| r.get("status").str().to_owned())
            .collect();
        assert_eq!(got[2..11], ["delivered"; 9]);
        assert_eq!(got[11], "draft");
    }
}
