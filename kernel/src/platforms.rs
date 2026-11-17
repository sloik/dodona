use crate::json::{self, Value};
use std::collections::BTreeMap;
fn reproducibility(records: &BTreeMap<(String, String), String>, key: &str) -> &'static str {
    let values: Vec<_> = records
        .iter()
        .filter(|((k, _), _)| k == key)
        .map(|(_, v)| v)
        .collect();
    if values.iter().any(|v| v.as_str() == "conflict") || values.iter().any(|v| *v != values[0]) {
        "differs"
    } else if values.len() >= 2 {
        "agrees"
    } else {
        "unknown"
    }
}
pub fn run(input: &Value) -> Vec<Value> {
    let keys = input.get("keys").array();
    let platforms = input.get("platforms").array();
    let allowed = matches!(input.get("stand_in_allowed"), Value::Bool(true))
        && !matches!(input.opt("provider_claims"), Some(Value::Bool(false)));
    let mut records: BTreeMap<(String, String), String> = BTreeMap::new();
    input
        .get("steps")
        .array()
        .iter()
        .map(|step| {
            let r = step.get("do").get("record");
            let entry = records
                .entry((r.get("key").str().into(), r.get("platform").str().into()))
                .or_insert_with(|| r.get("verdict").str().into());
            if entry != r.get("verdict").str() {
                *entry = "conflict".into();
            }
            let verified = keys
                .iter()
                .any(|k| reproducibility(&records, k.str()) == "agrees")
                && !keys
                    .iter()
                    .any(|k| reproducibility(&records, k.str()) == "differs");
            let mut stood = Vec::new();
            let mut statuses = Vec::new();
            let mut repro = Vec::new();
            for k in keys {
                let key = k.str();
                let mut ps = Vec::new();
                for p in platforms {
                    let platform = p.str();
                    let own = records.get(&(key.into(), platform.into()));
                    let stand = if allowed && verified {
                        records
                            .iter()
                            .find(|((kk, _), _)| kk == key)
                            .map(|(_, v)| v)
                    } else {
                        None
                    };
                    let value = own.or(stand);
                    if own.is_none() && value.is_some() {
                        stood.push((key.to_owned(), platform.to_owned()));
                    }
                    ps.push((
                        platform.to_owned(),
                        json::string(value.map(String::as_str).unwrap_or("unknown")),
                    ));
                }
                statuses.push((key.to_owned(), Value::Object(ps)));
                repro.push((key.to_owned(), json::string(reproducibility(&records, key))));
            }
            stood.sort();
            json::object(vec![
                ("status", Value::Object(statuses)),
                (
                    "stood_in",
                    Value::Array(
                        stood
                            .iter()
                            .map(|(k, p)| Value::Array(vec![json::string(k), json::string(p)]))
                            .collect(),
                    ),
                ),
                ("reproducibility", Value::Object(repro)),
            ])
        })
        .collect()
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rules() {
        let mut r = BTreeMap::new();
        assert_eq!(reproducibility(&r, "k"), "unknown");
        r.insert(("k".into(), "a".into()), "passed".into());
        assert_eq!(reproducibility(&r, "k"), "unknown");
        r.insert(("k".into(), "b".into()), "passed".into());
        assert_eq!(reproducibility(&r, "k"), "agrees");
        r.insert(("k".into(), "b".into()), "failed".into());
        assert_eq!(reproducibility(&r, "k"), "differs");
    }
}
