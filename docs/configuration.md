# Configuration reference: `dodona.toml`

Status: **draft 0.2**. **No kernel reads this file yet.** What follows records what the repository's own [dodona.toml](../dodona.toml) uses and what the architecture documents imply. Where something is undecided, this page says "not decided" and does not guess.

Configuration states **intent**: which provider handles which files, which tools are wanted, and where the policy file is. It is separate from two other things:

- the **lock**, which pins exact versions and digests and is generated ([lock.schema.json](../protocol/lock.schema.json), [decision 0008](../decisions/0008-reproducibility-levels.md));
- the **policy**, which says what must pass ([policy.schema.json](../protocol/policy.schema.json), [decision 0014](../decisions/0014-policy-is-separate-from-configuration.md)).

The file is TOML, in the root of the project. It holds no absolute paths and no shell fragments, and no platform-specific value outside a labelled per-platform section ([architecture section 6](../ARCHITECTURE.md#6-reproducibility), [decision 0009](../decisions/0009-platform-order-and-portability-rules.md)). What a per-platform section looks like, beyond `[[platform]]` below, is not decided. What the kernel does with a key it does not know (ignore it or refuse) is not decided.

## `[project]`

| Key | Type | Meaning | Default |
|---|---|---|---|
| `name` | string | The project's name | None. Required |
| `config` | string | Version of this file format, such as `"0.2"` | None. Required |
| `eol` | string | The line-ending convention for text files. The only value in use is `"lf"`. A text file that breaks it is an error and is never silently changed | Not decided |
| `bom` | string | Whether a text file may start with a byte-order mark. The only value in use is `"forbidden"` | Not decided |

Which files are text is declared by the provider that claims them (its manifest field `text_files`), not here.

## `[[platform]]`

One table per platform, in **support order** ([decision 0009](../decisions/0009-platform-order-and-portability-rules.md)). The lock covers these platforms. A platform listed here that a pinned tool has no build for makes the obligations that need it `unsupported` there, visibly.

| Key | Type | Meaning | Default |
|---|---|---|---|
| `os` | string | `macos`, `linux` or `windows` | None. Required |
| `arch` | string | `aarch64` or `x86_64` | None. Required |
| `libc` | string | `gnu` or `musl`. Meaningful on Linux | Not decided |

These are the values of the platform object in [common.schema.json](../protocol/common.schema.json), except that `emulated_on` is something a run reports and is never configured.

## `[[binding]]`

A binding attaches one provider, for a set of its capabilities, to the files it claims. A project has any number of them, and capabilities are bound separately, so one provider can index definitions while another builds.

| Key | Type | Meaning | Default |
|---|---|---|---|
| `name` | string | The binding's name. Obligations are named by binding and locator, and definitions are scoped by the binding that indexed them, so it must be unique | None. Required |
| `capabilities` | array of strings | Capabilities this binding uses from the provider. Each is a name from the [capability list](../protocol/common.schema.json) | None. Required |
| `provider` | string | The provider's name, as in its manifest and in the lock. The value `"@site"` means the binding is made outside the repository, by the site that runs the project. It is used for the executor and the toolchain | None. Required |
| `match` | array of strings | Which files the binding claims. Patterns are relative paths with `/`, in the style of `decisions/[0-9]*.md` | See below |
| `reproducibility` | string | `verdict`, `evidence` or `artifact`. The level the binding's obligations are held to ([decision 0008](../decisions/0008-reproducibility-levels.md)) | `verdict` |

Details:

- **`match`** is needed for capabilities that read files: `intent.index`, `decision.index`, `definition.index` and `obligation.enumerate`, `obligation.check`, `artifact.build`, `conformance.check`. It is left out for `run.submit`, `tool.resolve` and `store.blob`. A pattern matches a relative path segment by segment, with as many segments as the path: in a segment, `*` is any run of characters other than `/`, and `[0-9]` is one character in that range. There is no `?`, no `**` and no escape (decision 0034). Only regular files are claimed, never a link.
- **Two bindings may not claim the same file for the same capability.** That is an error at resolve time ([decision 0004](../decisions/0004-definition-identity-comes-from-the-language-provider.md)).
- **A file no binding claims** gets file identity: the hash of its bytes, with dependencies as declared in configuration. How dependencies of such a file are declared in configuration is not decided.
- **A binding that lists `obligation.check`, `artifact.build` or `conformance.check`** must also list `obligation.enumerate`, and the provider must offer both.
- **`reproducibility`** above what the provider's manifest allows (`max_reproducibility`) is an error at resolve time. Choosing a level per obligation, rather than per binding, is not decided.
- **A binding for `run.submit`** names an executor. There is no fallback to another executor. If the one named cannot be reached, the verdict is `unavailable`. A fallback would be an explicit, recorded configuration choice, and no key for it is decided.
- **Per-binding options** passed to a provider, such as the bounds of a checker, are not decided. For now a provider takes them from what it returns in `config` for each obligation.

## `[[tool]]`

A tool wanted by the project, or required by another tool. A tool is a directory tree, pinned in the lock by its digest.

| Key | Type | Meaning | Default |
|---|---|---|---|
| `name` | string | The tool's name | None. Required |
| `constraint` | string | Which versions are acceptable. See the grammar below | None. Required |
| `requires` | array of strings | Names of other tools this one needs, such as a language runtime. Each must have its own `[[tool]]` | Empty |

The lock records the whole closure: the tool, what it requires, what those require. How `requires` here relates to the `requires` a toolchain provider returns from `tool.resolve`, and which wins if they differ, is not decided. How a tool named in a provider's manifest relates to a `[[tool]]` of the same name is not decided either.

### Version constraints

A **version** is one or more non-negative whole numbers separated by dots, such as `17`, `1.7.4` or `17.0.9`. Compare two versions number by number from the left, treating a missing number as 0. So `17` equals `17.0.0`, and `1.10` is later than `1.9`. Versions with letters in them (such as release candidates) are not decided.

A **constraint** is one or more clauses separated by commas. A version satisfies it when it satisfies every clause (comma means *and*). A clause is an operator immediately followed by a version:

```
constraint = clause { "," clause }
clause     = operator version
operator   = "=" | ">=" | "<"
version    = number { "." number }
```

| Constraint | Accepts |
|---|---|
| `=1.7.4` | Exactly 1.7.4 |
| `>=17` | 17 and anything later |
| `>=1.2,<2` | From 1.2 up to, not including, 2 |

There is no *or*, no wildcard and no spaces. Which version the resolver picks when several satisfy the constraint is not decided. Whatever it picks is written to the lock as an exact version and does not change until the project asks to resolve again.

### Generate a draft lock from staged releases

`python tools/resolve_staged_lock.py RELEASES.json LOCK.json` writes a draft 0.2 lock for exact releases that have already been selected and staged. Each staged directory contains just the publisher's executable file. Paths are relative to the release declaration. On a filesystem with an owner-execute bit, set it on the staged file.

For example, stage the official Windows x64 release of Node 24.22.3 at `node-win-x64/node.exe` beside this declaration. Copy the SHA-256 from the publisher's release checksum list. [Node 24.22.3 checksums](https://nodejs.org/dist/v24.22.3/SHASUMS256.txt)

```json
{
  "entries": [
    {
      "kind": "tool",
      "name": "node",
      "version": "24.22.3",
      "requires": [],
      "platforms": [
        {
          "platform": {"os": "windows", "arch": "x86_64"},
          "tree": "node-win-x64",
          "entry": "node.exe",
          "upstream": {
            "source": "https://nodejs.org/dist/v24.22.3/win-x64/node.exe",
            "published_digest": "sha256:86fc4785327db5f5c7558dc6156c543b433c313e813a222e088086222ab4afa6"
          }
        }
      ]
    }
  ]
}
```

List direct tool dependencies by name in `requires`. Each tool must have its own entry and an exact pin for each platform that needs it. Use the full platform object, including `libc` and `emulated_on` where they apply. The generator checks the bytes against the supplied checksum, computes the tree digest, and writes the full dependency closure. It runs offline and replaces the output atomically after all checks pass. [Draft lock schema](../protocol/lock.schema.json)

For a platform extension, use `python tools/resolve_staged_lock.py --preserve PREVIOUS.json RELEASES.json LOCK.json`. Supply the complete set of staged releases and choose an output path distinct from the generated predecessor. The new lock must retain every previous exact version, requirement closure, platform digest and upstream source. A refusal leaves both files intact.

This reference path covers staged single-file releases. Project runs still select their tools from the site's configuration.

## `[policy]`

Points at the policy. The policy itself, what must pass and how strongly, lives in its own file so that the agent doing the work does not set the bar ([decision 0014](../decisions/0014-policy-is-separate-from-configuration.md)).

| Key | Type | Meaning | Default |
|---|---|---|---|
| `path` | string | Relative path of the policy file | Not decided. With no policy file, project status is `nothing-required`, never a pass |
| `reference` | string | The line of the project (`"main"` in the repository's file) whose policy is the reference policy. The kernel reports any difference between the policy in force and it | `main` ([decision 0014](../decisions/0014-policy-is-separate-from-configuration.md)) |
| `exception_separation` | string | The least separation level at which an exception takes effect: one of `self`, `helper`, `apart`, `tested`, `cross-make`, `credentialed` | Not decided |

Two things here are unsettled:

- `exception_separation` is a policy value, and decision 0014 says policy is kept apart from configuration. The policy schema carries the same thing as `separation.floor.grant-amendment`. Which file governs when both say something is not decided.
- `reference` appears in this file and as a field of the policy schema. Which governs is not decided.

How policy is protected from the agent it constrains is not decided. The format of the policy file, whether TOML with the keys of [policy.schema.json](../protocol/policy.schema.json) or JSON, is not decided; the file name `policy.toml` suggests the former.

## Things in the repository's file that are only comments

The repository's `dodona.toml` says no implementation is bound. The kernel's language is a binding to be chosen when a seed is built ([decision 0011](../decisions/0011-self-hosting-through-a-verified-seed.md)). No key for it exists.

## A complete small example

```toml
[project]
name = "example"
config = "0.2"
eol = "lf"
bom = "forbidden"

[[platform]]
os = "linux"
arch = "x86_64"

[[binding]]
name = "widths.index"
capabilities = ["definition.index"]
provider = "example.language.text"
match = ["docs/*.txt", "rules/*.cfg"]

[[binding]]
name = "widths"
capabilities = ["obligation.enumerate", "obligation.check"]
provider = "example.verifier.widthcheck"
match = ["rules/*.cfg"]
reproducibility = "verdict"

[[tool]]
name = "widthcheck"
constraint = ">=1.2,<2"

[[binding]]
name = "executor"
capabilities = ["run.submit"]
provider = "@site"

[[binding]]
name = "toolchain"
capabilities = ["tool.resolve"]
provider = "@site"

[policy]
path = "policy.toml"
reference = "main"
```
