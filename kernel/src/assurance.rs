use crate::json::{self, Value};
fn judge(links: &Value, defects: &Value) -> (&'static str, &'static str) {
    let levels = [
        "none", "asserted", "observed", "sampled", "bounded", "proven",
    ];
    let shown = ["spec-to-code", "code-to-runs", "runs-to-world"]
        .iter()
        .map(|key| {
            let value = links
                .opt(key)
                .and_then(|v| {
                    if let Value::String(s) = v {
                        Some(s.as_str())
                    } else {
                        None
                    }
                })
                .unwrap_or("none");
            levels.iter().position(|l| *l == value).unwrap()
        })
        .min()
        .unwrap();
    let non_vacuous = if defects.object().is_empty() {
        "none-planted"
    } else if defects.object().iter().all(|(_, v)| v.str() == "passed") {
        "shown"
    } else {
        "not-shown"
    };
    (levels[shown], non_vacuous)
}
pub fn run(input: &Value) -> Vec<Value> {
    input
        .get("steps")
        .array()
        .iter()
        .map(|s| {
            let j = s.get("do").get("judge");
            let (shown, non_vacuous) = judge(j.get("links"), j.get("defects"));
            json::object(vec![
                ("shown", json::string(shown)),
                ("non_vacuous", json::string(non_vacuous)),
            ])
        })
        .collect()
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rules() {
        let v = json::parse(br#"{"a":"passed"}"#).unwrap();
        let l = json::parse(
            br#"{"spec-to-code":"proven","code-to-runs":"bounded","runs-to-world":"sampled"}"#,
        )
        .unwrap();
        assert_eq!(judge(&l, &v), ("sampled", "shown"));
        let e = json::parse(br#"{}"#).unwrap();
        assert_eq!(judge(&e, &e), ("none", "none-planted"));
        let u = json::parse(br#"{"a":"unknown"}"#).unwrap();
        assert_eq!(judge(&l, &u).1, "not-shown");
    }
}
