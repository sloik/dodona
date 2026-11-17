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

The `path` command reads an object containing a lowercase hexadecimal `hex`
string and reports whether those bytes are an acceptable path. `path-set`
reads an object containing `paths` and reports every case-insensitive collision.
The `states` command judges independent evidence or intent states in one input;
`scenario` continues to judge a sequence of changes.

The checked-in Unicode tables use Unicode 15.1.0. To regenerate them, put the
five official data files named in the table header in a directory and run:

```text
python3 tools/gen_unicode_tables.py <data-directory>
```

The header records the SHA-256 digest of every input. The optional full Unicode
normalization test is run with `DODONA_UCD_DIR` set to that directory:

```text
cargo test --manifest-path kernel/Cargo.toml normalization_conformance -- --ignored
```
