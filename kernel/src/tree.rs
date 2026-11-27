use crate::{
    intent,
    json::{self, Value},
};
use std::collections::BTreeMap;

struct Criterion {
    gate: &'static str,
    check: String,
}

impl Criterion {
    fn new(gate: &'static str) -> Self {
        Self {
            gate,
            check: "unknown".into(),
        }
    }
}

struct Child {
    parent: String,
    criterion: Criterion,
}

type Children = BTreeMap<String, Child>;

fn child_links(children: &Children) -> BTreeMap<&str, Vec<&str>> {
    let mut links = BTreeMap::<&str, Vec<&str>>::new();
    for (name, child) in children {
        links.entry(&child.parent).or_default().push(name);
    }
    links
}

fn subtree<'a>(name: &'a str, links: &BTreeMap<&str, Vec<&'a str>>) -> Vec<&'a str> {
    let mut names = vec![name];
    let mut next = 0;
    while next < names.len() {
        let parent = names[next];
        if let Some(children) = links.get(parent) {
            names.extend(children);
        }
        next += 1;
    }
    names
}

fn parent(value: &Value) -> Option<&str> {
    match value.opt("parent") {
        None => Some("root"),
        Some(Value::String(parent)) => Some(parent),
        Some(_) => None,
    }
}

fn status(confirmed: bool, root: &Criterion, children: &Children, min: i64) -> &'static str {
    if !confirmed {
        return "draft";
    }
    // Visit descendants before their parents so every hard gate counts once at each ancestor.
    let names = subtree("root", &child_links(children));
    let mut hard = BTreeMap::from([("root", i64::from(root.gate == "hard"))]);
    hard.extend(
        children
            .iter()
            .map(|(name, child)| (name.as_str(), i64::from(child.criterion.gate == "hard"))),
    );
    for name in names.into_iter().skip(1).rev() {
        let count = hard[name];
        *hard
            .get_mut(children[name].parent.as_str())
            .expect("a known parent") += count;
    }
    let tree_hard = hard["root"];
    let child_unguarded = children.keys().any(|name| hard[name.as_str()] == 0);
    if tree_hard < min || child_unguarded {
        "unguarded"
    } else if (root.gate == "hard" && root.check != "passed")
        || children
            .values()
            .any(|child| child.criterion.gate == "hard" && child.criterion.check != "passed")
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
    root: &'a mut Criterion,
    children: &'a mut Children,
    name: &str,
) -> Option<&'a mut Criterion> {
    if name == "root" {
        Some(root)
    } else {
        children.get_mut(name).map(|child| &mut child.criterion)
    }
}

fn read_tree(input: &Value) -> Result<(Criterion, Children), String> {
    let root = input
        .opt("root")
        .and_then(|root| root.text("gate"))
        .map(counts_as)
        .ok_or("the root's gate is not a string")?;
    let Some(Value::Object(entries)) = input.opt("children") else {
        return Err("tree children must be an object".into());
    };
    let mut children = Children::new();
    for (name, value) in entries {
        if name == "root" {
            return Err("a child cannot be named root".into());
        }
        let gate = value
            .text("gate")
            .map(counts_as)
            .ok_or("a child's gate is not a string")?;
        let parent = parent(value).ok_or("a child's parent is not a string")?;
        children.insert(
            name.clone(),
            Child {
                parent: parent.into(),
                criterion: Criterion::new(gate),
            },
        );
    }
    if subtree("root", &child_links(&children)).len() != children.len() + 1 {
        return Err("every child must have a parent chain ending at root".into());
    }
    Ok((Criterion::new(root), children))
}

fn remove_branch(children: &mut Children, name: &str) -> bool {
    if !children.contains_key(name) {
        return false;
    }
    let names: Vec<_> = subtree(name, &child_links(children))
        .into_iter()
        .map(str::to_owned)
        .collect();
    for child in names {
        children.remove(&child);
    }
    true
}

pub fn run(input: &Value) -> Result<Vec<Value>, String> {
    let (mut root, mut children) = read_tree(input)?;
    let min = input.get("policy").get("min_hard_gates").number().max(1);
    let mut confirmed = false;
    Ok(input
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
                    node.check = status.into();
                }
            }
            if let Some(e) = a.opt("edit") {
                let node = e
                    .text("node")
                    .and_then(|n| node(&mut root, &mut children, n));
                if let (Some(node), Some(to)) = (node, gate(e, "to")) {
                    if node.gate != to {
                        node.gate = to;
                        confirmed = false;
                    }
                }
            }
            if let Some(r) = a.opt("remove") {
                if r.text("child")
                    .is_some_and(|child| remove_branch(&mut children, child))
                {
                    confirmed = false;
                }
            }
            if let Some(add) = a.opt("add") {
                if let (Some(child), Some(gate), Some(parent)) =
                    (add.text("child"), gate(add, "gate"), parent(add))
                {
                    if child != "root"
                        && !children.contains_key(child)
                        && (parent == "root" || children.contains_key(parent))
                    {
                        children.insert(
                            child.into(),
                            Child {
                                parent: parent.into(),
                                criterion: Criterion::new(gate),
                            },
                        );
                        confirmed = false;
                    }
                }
            }
            json::object(vec![(
                "status",
                json::string(status(confirmed, &root, &children, min)),
            )])
        })
        .collect())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rules() {
        let root = Criterion {
            gate: "hard",
            check: "passed".into(),
        };
        let mut c = Children::new();
        assert_eq!(status(false, &root, &c, 1), "draft");
        assert_eq!(status(true, &root, &c, 2), "unguarded");
        c.insert(
            "a".into(),
            Child {
                parent: "root".into(),
                criterion: Criterion {
                    gate: "soft",
                    check: "passed".into(),
                },
            },
        );
        // A child with no hard gate holds the tree, whatever the count.
        assert_eq!(status(true, &root, &c, 1), "unguarded");
        c.get_mut("a").unwrap().criterion.gate = "hard";
        assert_eq!(status(true, &root, &c, 1), "delivered");
        // The floor is met over the tree; the child is not held to it alone.
        assert_eq!(status(true, &root, &c, 2), "delivered");
        assert_eq!(status(true, &root, &c, 3), "unguarded");
        c.get_mut("a").unwrap().criterion.check = "conflict".into();
        assert_eq!(status(true, &root, &c, 2), "open");
        let soft_root = Criterion::new("soft");
        c.get_mut("a").unwrap().criterion.check = "passed".into();
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
            .unwrap()
            .iter()
            .map(|r| r.get("status").str().to_owned())
            .collect();
        assert_eq!(got[2..11], ["delivered"; 9]);
        assert_eq!(got[11], "draft");
        // b is soft, then counts as hard once written `Hard`; `deferred` is no
        // change from that; a child added as `made-up` counts as hard too.
        assert_eq!(
            got[12..],
            [
                "unguarded",
                "draft",
                "open",
                "open",
                "draft",
                "open",
                "open",
                "delivered"
            ]
        );
    }
}
