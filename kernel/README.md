# Seed kernel

This is a small first seed for scenario status and canonical encoding. It is not a usable dodona: it has no providers, persistent ledger, planner or agent interface. Passing the kit is sampled evidence, not a proof.

Build from the repository root:

```text
cargo build --release --manifest-path kernel/Cargo.toml
```

Run the judges from the repository root (on Windows use the executable's `.exe` suffix):

```text
python3 tools/run_kit.py -- kernel/target/release/dodona-kernel scenario
python3 tools/run_vectors.py -- kernel/target/release/dodona-kernel canonical
```
