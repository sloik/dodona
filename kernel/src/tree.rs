use crate::json::{self, Value};
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
                if let Some(node) = node(&mut root, &mut children, c.get("node").str()) {
                    node.1 = c.get("status").str().into();
                }
            }
            if let Some(e) = a.opt("edit") {
                if let Some(node) = node(&mut root, &mut children, e.get("node").str()) {
                    if node.0 != e.get("to").str() {
                        node.0 = e.get("to").str().into();
                        confirmed = false;
                    }
                }
            }
            if let Some(r) = a.opt("remove") {
                if children.remove(r.get("child").str()).is_some() {
                    confirmed = false;
                }
            }
            if let Some(add) = a.opt("add") {
                if !children.contains_key(add.get("child").str()) {
                    children.insert(
                        add.get("child").str().into(),
                        (add.get("gate").str().into(), "unknown".into()),
                    );
                    confirmed = false;
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
    }
}
