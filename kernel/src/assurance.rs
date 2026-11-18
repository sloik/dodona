use crate::json::{self, Value};
/// The assurance scale, weakest first.
pub const SCALE: [&str; 6] = [
    "none", "asserted", "observed", "sampled", "bounded", "proven",
];
pub fn rank(level: &str) -> Option<usize> {
    SCALE.iter().position(|l| *l == level)
}
fn is(v: &Value, status: &str) -> bool {
    matches!(v, Value::String(s) if s == status)
}
fn judge(links: &Value, defects: &Value) -> (&'static str, &'static str) {
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
            // A level that does not exist reports nothing.
            rank(value).unwrap_or(0)
        })
        .min()
        .unwrap();
    let non_vacuous = if defects.object().is_empty() {
        "none-planted"
    } else if defects.object().iter().all(|(_, v)| is(v, "passed")) {
        "shown"
    } else {
        "not-shown"
    };
    (SCALE[shown], non_vacuous)
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
        assert_eq!(rank("none"), Some(0));
        assert!(rank("proven") > rank("bounded"));
        assert_eq!(rank("made-up"), None);
        let odd = json::parse(br#"{"spec-to-code":"made-up","code-to-runs":7}"#).unwrap();
        assert_eq!(
            judge(&odd, &json::parse(br#"{"a":7}"#).unwrap()),
            ("none", "not-shown")
        );
    }
}
