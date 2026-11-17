#![forbid(unsafe_code)]
mod canonical;
mod evidence;
mod intent;
mod json;
use std::io::{self, Read, Write};
fn main() {
    let mut input = Vec::new();
    let answer = if io::stdin().read_to_end(&mut input).is_err() {
        json::object(vec![("refused", json::string("not-json"))])
    } else {
        match std::env::args().nth(1).as_deref() {
            Some("canonical") => canonical::answer(&input),
            Some("scenario") => match json::parse(&input) {
                Ok(v) => {
                    let results = match v.get("kind").str() {
                        "evidence" => evidence::run(&v),
                        "intent" => intent::run(&v),
                        _ => Vec::new(),
                    };
                    json::object(vec![("results", json::Value::Array(results))])
                }
                Err(reason) => json::object(vec![("refused", json::string(reason))]),
            },
            _ => json::object(vec![("refused", json::string("not-json"))]),
        }
    };
    let mut out = io::stdout().lock();
    let _ = writeln!(out, "{}", json::encode(&answer));
}
