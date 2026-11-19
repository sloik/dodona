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
    // The policy's number is counted over the whole tree; each child needs a
    // hard gate of its own but is not held to that number (decision 0030).
    let tree_hard = std::iter::once(root)
        .chain(children.values())
        .filter(|(g, _)| g == "hard")
        .count() as i64;
    let child_unguarded = children.values().any(|(g, _)| g != "hard");
    if !confirmed {
        "draft"
    } else if tree_hard < min || child_unguarded {
        "unguarded"
    } else if (root.0 == "hard" && root.1 != "passed")
        || children.values().any(|(g, s)| g == "hard" && s != "passed")
    {
        "open"
    } else {
        "delivered"
    }
}
/// The gate a step gives under `field`, as it counts. A string other than
/// exactly `soft` counts as `hard`: a mistake in writing a gate can only make
/// delivery harder. A gate that is not a string gives nothing.
fn gate(step: &Value, field: &str) -> Option<&'static str> {
    step.text(field).map(counts_as)
}
/// What a gate written as `g` counts as.
fn counts_as(g: &str) -> &'static str {
    if g == "soft" {
        "soft"
    } else {
        "hard"
    }
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
        counts_as(input.get("root").get("gate").str()).to_owned(),
        "unknown".to_owned(),
    );
    let mut children: BTreeMap<String, (String, String)> = input
        .get("children")
        .object()
        .iter()
        .map(|(k, v)| (k.clone(), (counts_as(v.get("gate").str()).into(), "unknown".into())))
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
        // A child with no hard gate holds the tree, whatever the count.
        assert_eq!(status(true, &root, &c, 1), "unguarded");
        c.get_mut("a").unwrap().0 = "hard".into();
        assert_eq!(status(true, &root, &c, 1), "delivered");
        // The floor is met over the tree; the child is not held to it alone.
        assert_eq!(status(true, &root, &c, 2), "delivered");
        assert_eq!(status(true, &root, &c, 3), "unguarded");
        c.get_mut("a").unwrap().1 = "conflict".into();
        assert_eq!(status(true, &root, &c, 2), "open");
        let soft_root = ("soft".to_owned(), "unknown".to_owned());
        c.get_mut("a").unwrap().1 = "passed".into();
        assert_eq!(status(true, &soft_root, &c, 1), "delivered");
        assert_eq!(status(true, &soft_root, &BTreeMap::new(), 1), "unguarded");
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
                {"do":{"remove":{"child":"gone"}}},{"do":{"add":{"child":"b","gate":7}}},
                {"do":{"add":{"child":"root","gate":"hard"}}},{"do":{"add":{"child":7,"gate":"hard"}}},
                {"do":{"add":{"child":"b","gate":"soft"}}},{"do":{"confirm":{}}},
                {"do":{"edit":{"node":"b","to":"Hard"}}},{"do":{"confirm":{}}},
                {"do":{"edit":{"node":"b","to":"deferred"}}},{"do":{"add":{"child":"c","gate":"made-up"}}},
                {"do":{"confirm":{}}},{"do":{"check":{"node":"b","status":"passed"}}},
                {"do":{"check":{"node":"c","status":"passed"}}}]}"#,
        )
        .unwrap();
        let got: Vec<String> = run(&input)
            .iter()
            .map(|r| r.get("status").str().to_owned())
            .collect();
        assert_eq!(got[2..11], ["delivered"; 9]);
        assert_eq!(got[11], "draft");
        // b is soft, then counts as hard once written `Hard`; `deferred` is no
        // change from that; a child added as `made-up` counts as hard too.
        assert_eq!(
            got[12..],
            ["unguarded", "draft", "open", "open", "draft", "open", "open", "delivered"]
        );
    }
}
