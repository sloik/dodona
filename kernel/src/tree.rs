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
    let min = input.get("policy").get("min_hard_gates").number();
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
                let n = c.get("node").str();
                let node = if n == "root" {
                    &mut root
                } else {
                    children.get_mut(n).unwrap()
                };
                node.1 = c.get("status").str().into();
            }
            if let Some(e) = a.opt("edit") {
                let n = e.get("node").str();
                let node = if n == "root" {
                    &mut root
                } else {
                    children.get_mut(n).unwrap()
                };
                node.0 = e.get("to").str().into();
                confirmed = false;
            }
            if let Some(r) = a.opt("remove") {
                children.remove(r.get("child").str());
                confirmed = false;
            }
            if let Some(add) = a.opt("add") {
                children.insert(
                    add.get("child").str().into(),
                    (add.get("gate").str().into(), "unknown".into()),
                );
                confirmed = false;
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
    }
}
