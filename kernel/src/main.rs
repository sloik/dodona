#![forbid(unsafe_code)]
mod canonical;
mod evidence;
mod intent;
mod json;
mod path;
mod unicode;
mod unicode_tables;
use std::io::{self, Read, Write};
fn main() {
    let mut input = Vec::new();
    let answer = if io::stdin().read_to_end(&mut input).is_err() {
        json::object(vec![("refused", json::string("not-json"))])
    } else {
        match std::env::args().nth(1).as_deref() {
            Some("canonical") => canonical::answer(&input),
            Some("scenario" | "states" | "path" | "path-set") => match json::parse(&input) {
                Ok(v) => {
                    let command = std::env::args().nth(1).unwrap();
                    if command == "path" {
                        path::one(&v)
                    } else if command == "path-set" {
                        path::set(&v)
                    } else {
                        let results = match (command.as_str(), v.get("kind").str()) {
                            ("scenario", "evidence") => evidence::run(&v),
                            ("states", "evidence") => evidence::states(&v),
                            ("scenario", "intent") => intent::run(&v),
                            ("states", "intent") => intent::states(&v),
                            _ => Vec::new(),
                        };
                        json::object(vec![("results", json::Value::Array(results))])
                    }
                }
                Err(reason) => json::object(vec![("refused", json::string(reason))]),
            },
            _ => json::object(vec![("refused", json::string("not-json"))]),
        }
    };
    let mut out = io::stdout().lock();
    let _ = writeln!(out, "{}", json::encode(&answer));
}
