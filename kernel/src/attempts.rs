use crate::{
    acts,
    json::{self, Value},
};
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
    // Every attempt in the order taken; those on the current target start at `current`.
    let mut all: Vec<(String, String)> = Vec::new();
    let mut current = 0;
    input
        .get("steps")
        .array()
        .iter()
        .map(|step| {
            let a = step.get("do");
            if let Some(t) = a.opt("take") {
                all.push((t.get("as").str().into(), "open".into()));
            }
            if let Some(c) = a.opt("close") {
                if let Some(a) = all
                    .iter_mut()
                    .find(|(t, r)| t == c.get("ticket").str() && r == "open")
                {
                    a.1 = c.get("result").str().into();
                }
            }
            if a.opt("change_target").is_some() {
                current = all.len();
            }
            let (result, shopped) = judge(&all[current..]);
            let (_, retried) = judge(&all);
            let mut fields = vec![
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
                ("attempts", Value::Number(all.len() as i64)),
                ("retried", Value::Bool(retried)),
            ];
            if let Some(claim) = input.opt("claims") {
                let rank = acts::rank(claim.str()).expect("claims is not a separation level");
                fields.push((
                    "granted",
                    json::string(if shopped && rank > 1 {
                        "helper"
                    } else {
                        claim.str()
                    }),
                ));
            }
            json::object(fields)
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
