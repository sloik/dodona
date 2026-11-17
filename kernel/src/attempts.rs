use crate::json::{self, Value};
fn judge(attempts: &[(String, String)]) -> (&'static str, bool) {
    let result = if attempts.is_empty() {
        "none"
    } else if attempts.iter().all(|(_, r)| r == "agreed") {
        "agreed"
    } else {
        "refused"
    };
    let mut prior_failure = false;
    let mut shopped = false;
    for (_, r) in attempts {
        if r == "agreed" && prior_failure {
            shopped = true;
        }
        if r != "agreed" {
            prior_failure = true;
        }
    }
    (result, shopped)
}
pub fn run(input: &Value) -> Vec<Value> {
    let mut attempts: Vec<(String, String)> = Vec::new();
    let mut total = 0;
    input
        .get("steps")
        .array()
        .iter()
        .map(|step| {
            let a = step.get("do");
            if let Some(t) = a.opt("take") {
                attempts.push((t.get("as").str().into(), "open".into()));
                total += 1;
            }
            if let Some(c) = a.opt("close") {
                attempts
                    .iter_mut()
                    .find(|(t, _)| t == c.get("ticket").str())
                    .unwrap()
                    .1 = c.get("result").str().into();
            }
            if a.opt("change_target").is_some() {
                attempts.clear();
            }
            let (result, shopped) = judge(&attempts);
            json::object(vec![
                ("result", json::string(result)),
                ("shopped", Value::Bool(shopped)),
                (
                    "cap",
                    if shopped {
                        json::string("helper")
                    } else {
                        Value::Null
                    },
                ),
                ("attempts", Value::Number(total)),
            ])
        })
        .collect()
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rules() {
        assert_eq!(judge(&[]), ("none", false));
        assert_eq!(judge(&[("a".into(), "open".into())]), ("refused", false));
        assert_eq!(
            judge(&[
                ("a".into(), "refused".into()),
                ("b".into(), "agreed".into())
            ]),
            ("refused", true)
        );
        assert_eq!(judge(&[("a".into(), "agreed".into())]), ("agreed", false));
    }
}
