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
/// How many attempts along the line may not agree before every retried
/// agreement is capped (decision 0031): a whole number of at least one, 2 when
/// the scenario gives none. Any other value is not one the contract allows,
/// and the input is refused.
fn limit(input: &Value) -> i64 {
    match input.opt("refusals_before_cap") {
        None => 2,
        Some(Value::Number(n)) if *n >= 1 => *n,
        Some(_) => panic!("refusals_before_cap is not a whole number of at least one"),
    }
}
/// Whether an agreement is capped at `helper`: when shopped, or when retried and
/// the line has at least `limit` attempts that are not agreed, open ones included.
fn capped(all: &[(String, String)], shopped: bool, retried: bool, limit: i64) -> bool {
    let not_agreed = all.iter().filter(|(_, r)| r != "agreed").count() as i64;
    shopped || (retried && not_agreed >= limit)
}
pub fn run(input: &Value) -> Vec<Value> {
    let limit = limit(input);
    // Every attempt in the order taken; those on the current target start at `current`.
    let mut all: Vec<(String, String)> = Vec::new();
    let mut current = 0;
    input
        .get("steps")
        .array()
        .iter()
        .map(|step| {
            let a = step.get("do");
            if let Some(ticket) = a.opt("take").and_then(|t| t.text("as")) {
                all.push((ticket.into(), "open".into()));
            }
            if let Some(c) = a.opt("close") {
                // A result that is neither, or a ticket that is not open, changes nothing.
                let result = c
                    .text("result")
                    .filter(|r| *r == "agreed" || *r == "refused");
                if let (Some(ticket), Some(result)) = (c.text("ticket"), result) {
                    if let Some(a) = all.iter_mut().find(|(t, r)| t == ticket && r == "open") {
                        a.1 = result.into();
                    }
                }
            }
            if a.opt("change_target").is_some() {
                current = all.len();
            }
            let (result, shopped) = judge(&all[current..]);
            let (_, retried) = judge(&all);
            let cap = capped(&all, shopped, retried, limit);
            let mut fields = vec![
                ("result", json::string(result)),
                ("shopped", Value::Bool(shopped)),
                (
                    "cap",
                    if cap {
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
                    json::string(if cap && rank > 1 {
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
        let input = json::parse(
            br#"{"steps":[{"do":{"take":{"as":"t"}}},{"do":{"close":{"ticket":"t","result":"made-up"}}},
                {"do":{"close":{"ticket":"gone","result":"agreed"}}},{"do":{"close":{"ticket":7,"result":"agreed"}}},
                {"do":{"take":{"as":7}}},{"do":{"close":{"ticket":"t","result":"agreed"}}}]}"#,
        )
        .unwrap();
        let got: Vec<String> = run(&input)
            .iter()
            .map(|r| format!("{} {}", r.get("result").str(), r.get("attempts").number()))
            .collect();
        assert_eq!(got[..5], ["refused 1"; 5]);
        assert_eq!(got[5], "agreed 1");
    }
    #[test]
    fn the_limit_on_refusals() {
        let line = |rs: &[&str]| -> Vec<(String, String)> {
            rs.iter().map(|r| ("t".to_owned(), r.to_string())).collect()
        };
        // Retried after one refusal: kept at the default limit, capped at a limit of one.
        let one = line(&["refused", "agreed"]);
        assert!(!capped(&one, false, true, 2));
        assert!(capped(&one, false, true, 1));
        // An open attempt counts as one that did not agree.
        let two = line(&["refused", "open", "agreed"]);
        assert!(capped(&two, false, true, 2));
        assert!(!capped(&two, false, true, 3));
        // Not retried, never capped by the limit; shopped, always capped.
        assert!(!capped(&line(&["refused", "refused"]), false, false, 1));
        assert!(capped(&one, true, true, 9));
        let read = |text: &str| limit(&json::parse(text.as_bytes()).unwrap());
        assert_eq!(read("{}"), 2);
        assert_eq!(read(r#"{"refusals_before_cap":1}"#), 1);
        for bad in [r#"{"refusals_before_cap":0}"#, r#"{"refusals_before_cap":"2"}"#] {
            let text = bad.to_owned();
            assert!(std::panic::catch_unwind(move || read(&text)).is_err());
        }
    }
}
