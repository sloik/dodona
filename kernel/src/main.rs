// Unsafe code is allowed in one module only: `proc`, which ends process trees.
#![deny(unsafe_code)]
mod acts;
mod assurance;
mod attempts;
mod canonical;
mod decisions;
mod evidence;
mod host;
mod intent;
mod json;
mod jsonread;
mod ledger;
mod path;
mod plan;
mod platforms;
#[allow(unsafe_code)]
mod proc;
mod project_status;
mod session;
mod status;
mod tree;
mod unicode;
mod unicode_tables;
mod wire;
use json::Value;
use std::io::{self, Read, Write};
use std::process::ExitCode;
fn results(results: Vec<Value>) -> Value {
    json::object(vec![("results", Value::Array(results))])
}
/// The answer to one command, or why the input cannot be handled.
/// Input of the wrong shape for its command stops the process instead; either
/// way nothing is printed and the exit status is not zero.
fn answer(command: &str, input: &[u8]) -> Result<Value, String> {
    // These two commands have a refusal for input that is not acceptable JSON.
    if command == "canonical" {
        return Ok(canonical::answer(input));
    }
    // An append reads its own input, without recursion, so that a body nested too
    // deep for any reader is refused as `bad-request` at any depth.
    if command == "ledger-append" {
        return ledger::append(input);
    }
    let v = match json::parse(input) {
        Ok(v) => v,
        Err(reason) if command == "key" => {
            return Ok(json::object(vec![("refused", json::string(reason))]))
        }
        // A check's input that is not a JSON object is refused as `bad-input`.
        Err(_) if command == "check" => Value::Null,
        Err(reason) => return Err(format!("the input is not acceptable JSON: {reason}")),
    };
    let kind = || match v.opt("kind") {
        Some(Value::String(s)) => Ok(s.as_str()),
        _ => Err("the input has no `kind`".to_owned()),
    };
    Ok(match command {
        "key" => canonical::key(&v),
        "path" => path::one(&v),
        "path-set" => path::set(&v),
        "ledger-read" => ledger::read(&v)?,
        "check" => host::check(&v)?,
        "scenario" => results(match kind()? {
            "acts" => acts::run(&v),
            "status" => status::run(&v),
            "plan" => plan::run(&v),
            "platforms" => platforms::run(&v),
            "attempts" => attempts::run(&v),
            "tree" => tree::run(&v),
            "assurance" => assurance::run(&v),
            "decisions" => decisions::run(&v),
            "evidence" => evidence::run(&v),
            "intent" => intent::run(&v),
            other => return Err(format!("no scenarios of kind `{other}`")),
        }),
        "states" => results(match kind()? {
            "evidence" => evidence::states(&v),
            "intent" => intent::states(&v),
            other => return Err(format!("no states of kind `{other}`")),
        }),
        other => return Err(format!("no command `{other}`")),
    })
}
fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().collect();
    let command = args.get(1).cloned().unwrap_or_default();
    // A session takes its limits and the provider as arguments and reads no input.
    let answer = if command == "session" {
        session::run(&args[2..])
    } else if command == "status" {
        // Every input gets one JSON object and the exit status 0, a refusal included.
        let mut input = Vec::new();
        match io::stdin().read_to_end(&mut input) {
            Ok(_) => Ok(project_status::answer(&input)),
            Err(_) => Ok(project_status::answer(b"")),
        }
    } else {
        let mut input = Vec::new();
        match io::stdin().read_to_end(&mut input) {
            Ok(_) => answer(&command, &input),
            Err(e) => Err(format!("cannot read standard input: {e}")),
        }
    };
    match answer {
        Ok(answer) => {
            let mut out = io::stdout().lock();
            match writeln!(out, "{}", json::encode(&answer)).and_then(|_| out.flush()) {
                Ok(()) => ExitCode::SUCCESS,
                Err(_) => ExitCode::FAILURE,
            }
        }
        Err(why) => {
            eprintln!("dodona-kernel: {why}");
            ExitCode::from(2)
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn commands() {
        assert!(answer("canonical", b"{").unwrap().opt("refused").is_some());
        assert!(answer("key", b"{").unwrap().opt("refused").is_some());
        assert!(answer("key", b"{}").unwrap().opt("core_key").is_some());
        assert!(answer("scenario", b"{").is_err());
        assert!(answer("scenario", b"{}").is_err());
        assert!(answer("scenario", br#"{"kind":"nothing"}"#).is_err());
        assert!(answer("states", br#"{"kind":"plan"}"#).is_err());
        assert!(answer("ledger-read", b"{}").is_err());
        assert!(answer("ledger-append", b"{").is_err());
        // A body too deep for any reader is refused, not read by recursion, and
        // before the ledger it names is touched.
        let deep = format!(
            r#"{{"body":{}{},"kind":"note","ledger":"never-written.ledger","wait_ms":0}}"#,
            "[".repeat(100_000),
            "]".repeat(100_000)
        );
        let r = answer("ledger-append", deep.as_bytes()).unwrap();
        assert_eq!(json::encode(&r), r#"{"refused":"bad-request"}"#);
        assert!(!std::path::Path::new("never-written.ledger.lock").exists());
        assert!(answer("nothing", b"{}").is_err());
        assert!(answer("", b"{}").is_err());
        let r = answer("scenario", br#"{"kind":"assurance","steps":[]}"#).unwrap();
        assert_eq!(json::encode(&r), r#"{"results":[]}"#);
    }
}
