# Writing a provider

Status: **draft 0.2**, written against the [protocol schemas](../protocol/README.md). No kernel exists yet, so nothing here has been run against one. What can be checked today is that every message you write validates against [messages.schema.json](../protocol/messages.schema.json). Every JSON line in this file does, and was checked that way.

This page is for someone who has never spoken to the authors. If something you need is missing, that is a gap in the documents. Please report it as one.

## What a provider is

A provider is a program the kernel starts and talks to over standard input and output ([decision 0003](../decisions/0003-providers-are-separate-processes.md)). It can be written in any language that reads and writes text. It supplies one or more **capabilities**, such as turning a decision file into a decision node, or checking whether a specification holds.

The kernel decides what is asked and when. The provider only answers. A provider never starts a tool itself: when a check needs a tool, the provider describes the run and the kernel hands it to an executor ([decision 0007](../decisions/0007-execution-backend-is-separate-from-the-verifier.md)).

The capabilities, and who offers them:

| Capability | Offered by | You answer with |
|---|---|---|
| `intent.index` | An intent format | Intents, with criteria, gates and children; amendments |
| `decision.index` | A decision format | Decisions: status, what each governs, what it supersedes |
| `definition.index` | A language | Definitions: name, identity, dependencies, files |
| `obligation.enumerate` | Any provider that checks, builds or tests conformance | The separate questions your tool can answer |
| `obligation.check` | A verifier | A run to make, or a verdict |
| `artifact.build` | A builder | A run to make, or the build outputs |
| `conformance.check` | A conformance checker | A run to make, or a verdict with its method |
| `run.submit` | An executor | A handle for a run, then its progress and report |
| `tool.resolve` | A toolchain | An exact tool tree for a platform |
| `store.blob` | A store | A file, or the identity of a file |

If you offer `obligation.check`, `artifact.build` or `conformance.check`, you must also offer `obligation.enumerate`.

## The session

1. The kernel starts your program and sends one line, `hello`: the protocol versions it speaks, its limits, and a test string (the echo).
2. You answer with one line, `manifest`: your name and version, the protocol version you chose, what you offer, the tools you need, and what a result from you assumes. Return the echo string unchanged. A provider that mangles it is stopped before any work is done.
3. The kernel sends requests. Each has an `id` and a `deadline_ms`, the time you have to answer, counted from when the kernel sent the line. You answer each with a `result` or an `error` carrying the same `id`. You never speak first.
4. The kernel sends `shutdown`, or closes your input. Then stop. If you do not, the whole process tree is ended.

Rules of the road, all from [the protocol README](../protocol/README.md):

- One JSON message per line, UTF-8, ended by a single line-feed. No carriage return, no byte-order mark. Never print a line longer than `max_line_bytes` from `hello`.
- Standard error is for your logs. It is kept, capped, and never read as a message.
- Do not put anything on standard output that is not a message.
- A message that fails validation ends the session, and any check in progress ends in `error`. An answer after its deadline is logged and dropped.
- Bulk data never travels in a message. Files are named by relative path, inside the working directory of the request, together with their identity (a `sha256:` hash of the bytes). Paths use `/`, are relative, and may not contain `.` or `..` segments.
- Lists that are sets are sorted by their UTF-8 bytes. Numbers are integers. Commands are argument lists, never a string for a shell. No clock reading takes part in anything the kernel hashes.
- Hashing structured values uses the canonical encoding (`protocol/canonical-encoding.md`). You rarely need it: the kernel computes the keys, and you only report identities of files and definitions.

## An example: a verifier

The provider in this example is imaginary. It is called `example.verifier.widthcheck` and checks that no line of a text file is longer than a limit. It uses one tool, `widthcheck`. The messages are shown one at a time; each box is one line on the wire.

**1. Kernel to provider: hello.** The echo string contains non-ASCII and control characters, written as JSON escapes.

```json
{"type":"hello","protocol":["0.2"],"limits":{"max_line_bytes":1048576,"deadline_ms":10000},"echo":"héllo ☃ \u0001\u001f end"}
```

**2. Provider to kernel: the manifest.** It sits inside a `manifest` message that repeats the echo. The manifest is described by [provider-manifest.schema.json](../protocol/provider-manifest.schema.json). Here the provider says what it offers, that its checking is exhaustive over the lines of a file, that it needs the tool `widthcheck` at version 1.2 or later, and what its results assume.

```json
{"type":"manifest","echo":"héllo ☃ \u0001\u001f end","manifest":{"protocol":"0.2","name":"example.verifier.widthcheck","version":"0.1.0","capabilities":[{"capability":"obligation.enumerate","determinism":"deterministic"},{"capability":"obligation.check","determinism":"deterministic","strength":{"class":"width-scan","rank":"exhaustive"}}],"tools":[{"name":"widthcheck","constraint":">=1.2"}],"trusted_base":["widthcheck counts characters correctly"]}}
```

**3. Kernel to provider: enumerate.** The project has bound this provider, as the binding `widths`, to two files: a rule file and a text file. The language provider has already indexed them at file level. The kernel passes the definitions and the files, which are in the working directory.

```json
{"type":"request","id":"1","deadline_ms":30000,"capability":"obligation.enumerate","body":{"binding":"widths","definitions":[{"name":"docs/intro.txt","identity":"sha256:34a04005bcaf206eec990bd9637d9fdb6725e0a0c0d4aebf003f17f4c956eb5c","depends_on":[],"granularity":"file","files":["docs/intro.txt"]},{"name":"rules/width.cfg","identity":"sha256:d4f02eaafd1a9e9de7d10972ca8e47fa7a985825c3c9c1e249c72683cb3e4f19","depends_on":[],"granularity":"file","files":["rules/width.cfg"]}],"files":[{"path":"docs/intro.txt","identity":"sha256:34a04005bcaf206eec990bd9637d9fdb6725e0a0c0d4aebf003f17f4c956eb5c"},{"path":"rules/width.cfg","identity":"sha256:d4f02eaafd1a9e9de7d10972ca8e47fa7a985825c3c9c1e249c72683cb3e4f19"}]}}
```

**4. Provider to kernel: one obligation.** Only you know what your tool can answer separately; here, one question per text file. `name` is a locator inside the binding that survives edits to the content. `config` holds everything that could change the answer: the kernel hashes it into the key. A real provider would also enumerate a planted defect, an obligation with `expect` set to `violated` and a `defect_of` naming this one, so the kernel can show the check is able to fail.

```json
{"type":"result","id":"1","capability":"obligation.enumerate","body":{"obligations":[{"name":"width/docs/intro.txt","kind":"check","specified_by":["rules/width.cfg"],"targets":["docs/intro.txt"],"expect":"holds","config":{"max_columns":80}}]}}
```

**5. Kernel to provider: check.** The obligation comes back with its binding. The tool is already pinned and unpacked at `tools/widthcheck`, with the digest the lock records. `op` says this is the start of a check.

```json
{"type":"request","id":"2","deadline_ms":60000,"capability":"obligation.check","body":{"op":"start","obligation":{"binding":"widths","name":"width/docs/intro.txt","kind":"check","specified_by":["rules/width.cfg"],"targets":["docs/intro.txt"],"expect":"holds","config":{"max_columns":80}},"inputs":[{"path":"docs/intro.txt","identity":"sha256:34a04005bcaf206eec990bd9637d9fdb6725e0a0c0d4aebf003f17f4c956eb5c"},{"path":"rules/width.cfg","identity":"sha256:d4f02eaafd1a9e9de7d10972ca8e47fa7a985825c3c9c1e249c72683cb3e4f19"}],"tools":[{"name":"widthcheck","version":"1.2.0","digest":"sha256:28c66bbc4e7ec2364490efd88fba85548b5779434bb4252643db9371af5d1e12","root":"tools/widthcheck"}],"platform":{"os":"macos","arch":"aarch64"}}}
```

**6. Provider to kernel: next, a run description.** The provider does not start the tool. It says exactly what to run: a program that is a file inside the pinned tool tree, an argument list, the input files, the outputs it expects, limits, the platform, and the tool digests it expects. Times are in milliseconds, sizes in bytes.

```json
{"type":"result","id":"2","capability":"obligation.check","body":{"next":{"program":{"tool":"widthcheck","path":"bin/widthcheck"},"args":["--max","80","--report","out/report.txt","docs/intro.txt"],"inputs":[{"path":"docs/intro.txt","identity":"sha256:34a04005bcaf206eec990bd9637d9fdb6725e0a0c0d4aebf003f17f4c956eb5c"}],"outputs":[{"path":"out/report.txt"}],"limits":{"wall_ms":20000,"output_bytes":65536},"platform":{"os":"macos","arch":"aarch64"},"tools":[{"name":"widthcheck","digest":"sha256:28c66bbc4e7ec2364490efd88fba85548b5779434bb4252643db9371af5d1e12"}]}}}
```

**7. The kernel and the executor.** This part is between the kernel and the executor provider, not you. It is shown so you know what the report you get back contains. The kernel records the submission, then submits the run under a key:

```json
{"type":"request","id":"e1","deadline_ms":10000,"capability":"run.submit","body":{"op":"submit","key":"sha256:e67d23e7820c49a8051dac2831f38290f5e72f66c8db5079eeb60d82f14894c0","run":{"program":{"tool":"widthcheck","path":"bin/widthcheck"},"args":["--max","80","--report","out/report.txt","docs/intro.txt"],"inputs":[{"path":"docs/intro.txt","identity":"sha256:34a04005bcaf206eec990bd9637d9fdb6725e0a0c0d4aebf003f17f4c956eb5c"}],"outputs":[{"path":"out/report.txt"}],"limits":{"wall_ms":20000,"output_bytes":65536},"platform":{"os":"macos","arch":"aarch64"},"tools":[{"name":"widthcheck","digest":"sha256:28c66bbc4e7ec2364490efd88fba85548b5779434bb4252643db9371af5d1e12"}]}}}
```

```json
{"type":"result","id":"e1","capability":"run.submit","body":{"handle":"run-0001"}}
```

The kernel polls the executor with the handle returned by `submit`. These messages follow the draft `run.submit` schema.

```json
{"type":"request","id":"e2","deadline_ms":10000,"capability":"run.submit","body":{"op":"poll","handle":"run-0001"}}
```

When the run has ended, the answer carries the platform and tool digests actually run. The kernel compares them with what was asked.

```json
{"type":"result","id":"e2","capability":"run.submit","body":{"state":"finished","report":{"handle":"run-0001","end":"exited","exit_status":0,"platform":{"os":"macos","arch":"aarch64"},"tools_ran":[{"name":"widthcheck","digest":"sha256:28c66bbc4e7ec2364490efd88fba85548b5779434bb4252643db9371af5d1e12"}],"isolation":"best-effort","captured_output":{"path":"out/captured.log","identity":"sha256:836ff184e7b41b1e13cb5fd89fa1de98dbbab99e9d2918913ff43b86a5c7c213"},"outputs":[{"path":"out/report.txt","identity":"sha256:762069bc07a6e1b5df123a5ae7bd91c10daa04694fbaa17fba0cd6a8dcce8f22"}]}}}
```

If the executor is still running the job, it answers the same poll with `running`.

```json
{"type":"result","id":"e2","capability":"run.submit","body":{"state":"running"}}
```

In that branch, the kernel can poll again or ask to cancel the run. This example shows a cancellation with an empty captured log and no output files.

```json
{"type":"request","id":"e3","deadline_ms":10000,"capability":"run.submit","body":{"op":"cancel","handle":"run-0001"}}
{"type":"result","id":"e3","capability":"run.submit","body":{"state":"cancelled","report":{"handle":"run-0001","end":"cancelled","platform":{"os":"macos","arch":"aarch64"},"tools_ran":[{"name":"widthcheck","digest":"sha256:28c66bbc4e7ec2364490efd88fba85548b5779434bb4252643db9371af5d1e12"}],"isolation":"best-effort","captured_output":{"path":"out/captured.log","identity":"sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},"outputs":[]}}}
```

The walkthrough continues with the `finished` answer above.

**8. Kernel to provider: the run result.** The kernel passes the report to you as a request with `op` set to `run.result`. The output files are now in your working directory at the paths the report gives.

```json
{"type": "request", "id": "3", "deadline_ms": 60000, "capability": "obligation.check", "body": {"op": "run.result", "check": "2", "run": 1, "report": {"handle": "run-0001", "end": "exited", "exit_status": 0, "platform": {"os": "macos", "arch": "aarch64"}, "tools_ran": [{"name": "widthcheck", "digest": "sha256:28c66bbc4e7ec2364490efd88fba85548b5779434bb4252643db9371af5d1e12"}], "isolation": "best-effort", "captured_output": {"path": "out/captured.log", "identity": "sha256:836ff184e7b41b1e13cb5fd89fa1de98dbbab99e9d2918913ff43b86a5c7c213"}, "outputs": [{"path": "out/report.txt", "identity": "sha256:762069bc07a6e1b5df123a5ae7bd91c10daa04694fbaa17fba0cd6a8dcce8f22"}]}}}
```

**9. Provider to kernel: final.** You read `out/report.txt`, and decide. Here the file is within the limit. The verdict is one of `passed`, `failed`, `error` or `unsupported`; the kernel alone writes the evidence record and derives the obligation's status. Give a `strength` for `passed` and `failed`: your class of evidence and its rank (`exhaustive`, `bounded`, `sampled` or `documented`). Attach what someone would need to audit the verdict later; for a `failed` verdict, the counterexample or diagnostic goes in `attachments`.

```json
{"type":"result","id":"3","capability":"obligation.check","body":{"final":{"verdict":"passed","strength":{"class":"width-scan","rank":"exhaustive"},"trusted_base":[],"summary":{"lines_scanned":42,"longest_line":78},"attachments":[{"path":"out/report.txt","identity":"sha256:762069bc07a6e1b5df123a5ae7bd91c10daa04694fbaa17fba0cd6a8dcce8f22"}]}}}
```

Had the check needed another run, you would have answered `next` again with a second run description instead of `final`. Then the loop repeats from step 7.

**10. Kernel to provider: shutdown.** Then exit.

```json
{"type":"shutdown"}
```

When you cannot answer a request, send an `error` with the request's `id`. Its code tells the kernel what to record: `unsupported` becomes the verdict `unsupported`, `unavailable` becomes `unavailable`, and `invalid-request` and `internal` become `error`.

```json
{"type":"error","id":"2","code":"invalid-request","detail":"the obligation names a file that is not in the working directory"}
```

## Rules for checks that need tools

These apply to `obligation.check`, `artifact.build` and `conformance.check`.

- **Describe, never run.** The program is a path inside a pinned tool tree. The tools you may name are the ones in the request's `tools` list, which come from the lock.
- **The first answer fixes the key.** If you need an input the kernel did not give you, name it in `declared` in your first `next` answer. After the first run is submitted, the key is fixed. A later run may name only tools and inputs already in it. Anything else ends the check in `error`.
- **A check can take several runs.** Every run is recorded in the evidence.
- **A run that exits is yours to interpret, whatever its exit status; a run that timed out, was cancelled or went over a limit ends the check in `error` and you are not asked.** The report says how the run ended (`exited`, `timed-out`, `cancelled` or `limit-exceeded`) and the exit status. If the tool answered "unknown", the verdict is `error`, not `passed`. Only a check that ran to completion and found what the obligation expects is `passed` ([decision 0005](../decisions/0005-closed-verdict-set.md)).
- **An obligation that expects a violation** (`expect` is `violated`, a planted defect) is `passed` when your check finds the violation it names.
- **Builds** answer `final` with `outputs`: each output file by relative path and identity, and whether the build is `deterministic`. A build's kind is `build`.
- **Conformance checks** also receive a `mapping`, the files that connect the specification to the implementation. The `class` in your `strength` is the method you used, such as trace replay.

## Example: definition.index

A language provider names each definition, gives its identity, lists what it depends on, says how fine its granularity was, and names the files that materialise it ([decision 0004](../decisions/0004-definition-identity-comes-from-the-language-provider.md)). The identity must depend on content alone. A file you cannot read goes in `rejected` with a reason code; nothing is dropped silently.

```json
{"type":"request","id":"1","deadline_ms":30000,"capability":"definition.index","body":{"binding":"sheets","files":[{"path":"src/area.sheet","identity":"sha256:35137c536e268997095b9eb31cfa0cfe536d00dbf6126486e63c05dc35261154"},{"path":"src/broken.sheet","identity":"sha256:ba09ef587fd2742c341694074f8ea0ab5d42499bb193246b46c7cc185308fadf"}]}}
```

```json
{"type":"result","id":"1","capability":"definition.index","body":{"definitions":[{"name":"area.sheet#rate","identity":"sha256:45e84635bc4803c5cc5d456c798a13d37a7fd184f76b012b01c01676d5ce46c0","depends_on":[],"granularity":"definition","files":["src/area.sheet"]},{"name":"area.sheet#total","identity":"sha256:d92c6a81b2ff50096bcda80885427d1f59a25b5f483f7055523504925d16ab23","depends_on":["area.sheet#rate"],"granularity":"definition","files":["src/area.sheet"]}],"rejected":[{"path":"src/broken.sheet","code":"parse-error","detail":"line 3: unexpected end of formula"}]}}
```

## Example: decision.index

A decision provider maps its own status words onto `proposed`, `accepted`, `superseded` and `rejected`. `governs` names definitions, with the identity each had when the decision was written. When that identity changes, the kernel flags the decision for review.

```json
{"type":"request","id":"1","deadline_ms":30000,"capability":"decision.index","body":{"binding":"decisions","files":[{"path":"decisions/0001-flat-rate.md","identity":"sha256:86ae35d58a6aa3b5742df94ef9d7162219f0106a911ae1954c1f0604aaec805d"}]}}
```

```json
{"type":"result","id":"1","capability":"decision.index","body":{"decisions":[{"name":"0001","identity":"sha256:86ae35d58a6aa3b5742df94ef9d7162219f0106a911ae1954c1f0604aaec805d","file":"decisions/0001-flat-rate.md","title":"Use a flat rate","status":"accepted","governs":[{"name":"area.sheet#rate","identity":"sha256:45e84635bc4803c5cc5d456c798a13d37a7fd184f76b012b01c01676d5ce46c0"}],"supersedes":[]}],"rejected":[]}}
```

`intent.index` follows the same pattern. Its result is described in [messages.schema.json](../protocol/messages.schema.json) under `res_intent_index`.

## Example: store.blob

This exchange illustrates the draft message schema. The file `out/message.txt` contains the five bytes `hello`. A `put` request stores the file and returns its content identity.

```json
{"type":"request","id":"1","deadline_ms":30000,"capability":"store.blob","body":{"op":"put","file":"out/message.txt"}}
{"type":"result","id":"1","capability":"store.blob","body":{"identity":"sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"}}
```

A `get` request uses that identity and gives the destination path in `into`. The result names the retrieved file.

```json
{"type":"request","id":"2","deadline_ms":30000,"capability":"store.blob","body":{"op":"get","identity":"sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824","into":"work/message.txt"}}
{"type":"result","id":"2","capability":"store.blob","body":{"file":"work/message.txt"}}
```

## Example: tool.resolve

These draft messages use a synthetic release. Its only file is the program `bin/sheetc`, with the bytes `fixture sheetc` followed by a line feed. The toolchain returns the published digest of those bytes and the [digest of the tree listing](../protocol/tool-tree-digest.md). The request's `tree_into` names the destination for the tree.

```json
{"type":"request","id":"1","deadline_ms":30000,"capability":"tool.resolve","body":{"name":"sheetc","constraint":"=1.0.0","platform":{"os":"linux","arch":"x86_64"},"tree_into":"tools/sheetc"}}
{"type":"result","id":"1","capability":"tool.resolve","body":{"resolved":{"name":"sheetc","version":"1.0.0","platform":{"os":"linux","arch":"x86_64"},"digest":"sha256:31b45b96ab37d93b6eb6e9327768f2e59b1e36bcdc8207a9901bb53593a085a5","requires":[],"upstream":{"source":"https://example.com/sheetc/1.0.0/linux-x86_64/sheetc","published_digest":"sha256:08249184cb7b2bea25821a755fb3bf075c49dbfc9e8971644a74dddcead646b1"},"entry":"bin/sheetc","tree":"tools/sheetc"}}}
```

The same release has no Windows build in this example.

```json
{"type":"request","id":"2","deadline_ms":30000,"capability":"tool.resolve","body":{"name":"sheetc","constraint":"=1.0.0","platform":{"os":"windows","arch":"x86_64"},"tree_into":"tools/sheetc"}}
{"type":"result","id":"2","capability":"tool.resolve","body":{"unresolved":{"code":"no-build-for-platform"}}}
```

## Example: artifact.build

This draft exchange uses the pinned `sheetc` tree above. The fixture's configuration, source and output files contain `format=object`, `area: 12` and `fixture object` respectively, each followed by a line feed.

The kernel starts the build obligation. The builder describes a run that reads the two inputs and declares `out/demo.o`.

```json
{"type":"request","id":"1","deadline_ms":30000,"capability":"artifact.build","body":{"op":"start","obligation":{"binding":"builds","name":"build/demo","kind":"build","specified_by":["rules/demo.cfg"],"targets":["src/demo.sheet"],"expect":"holds","config":{}},"inputs":[{"path":"rules/demo.cfg","identity":"sha256:58be2095a5f2dd75c3d6e928154de473bfdf982165e8e2eef4e25a0995485452"},{"path":"src/demo.sheet","identity":"sha256:b9a1815f4f1bcba0585246c9f3bc224dd3ef84d3d6efc6a95c27e76ef2112eb5"}],"tools":[{"name":"sheetc","digest":"sha256:31b45b96ab37d93b6eb6e9327768f2e59b1e36bcdc8207a9901bb53593a085a5","version":"1.0.0","root":"tools/sheetc"}],"platform":{"os":"linux","arch":"x86_64"}}}
{"type":"result","id":"1","capability":"artifact.build","body":{"next":{"program":{"tool":"sheetc","path":"bin/sheetc"},"args":["--rules","rules/demo.cfg","--output","out/demo.o","src/demo.sheet"],"inputs":[{"path":"rules/demo.cfg","identity":"sha256:58be2095a5f2dd75c3d6e928154de473bfdf982165e8e2eef4e25a0995485452"},{"path":"src/demo.sheet","identity":"sha256:b9a1815f4f1bcba0585246c9f3bc224dd3ef84d3d6efc6a95c27e76ef2112eb5"}],"outputs":[{"path":"out/demo.o"}],"limits":{"wall_ms":20000,"output_bytes":65536},"platform":{"os":"linux","arch":"x86_64"},"tools":[{"name":"sheetc","digest":"sha256:31b45b96ab37d93b6eb6e9327768f2e59b1e36bcdc8207a9901bb53593a085a5"}]}}}
```

The kernel returns the executor's report under the original check ID. The builder returns a successful build with the output identity and its determinism declaration. The captured log is empty.

```json
{"type":"request","id":"2","deadline_ms":30000,"capability":"artifact.build","body":{"op":"run.result","check":"1","run":1,"report":{"handle":"build-0001","end":"exited","exit_status":0,"platform":{"os":"linux","arch":"x86_64"},"tools_ran":[{"name":"sheetc","digest":"sha256:31b45b96ab37d93b6eb6e9327768f2e59b1e36bcdc8207a9901bb53593a085a5"}],"isolation":"best-effort","captured_output":{"path":"out/captured.log","identity":"sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},"outputs":[{"path":"out/demo.o","identity":"sha256:6cb54a97f497e7b39f196e09ff5a80126822b5a948c307aeb9c91401b4d86a52"}]}}}
{"type":"result","id":"2","capability":"artifact.build","body":{"final":{"verdict":"passed","outputs":[{"path":"out/demo.o","identity":"sha256:6cb54a97f497e7b39f196e09ff5a80126822b5a948c307aeb9c91401b4d86a52"}],"deterministic":true}}}
```

## Where to look for the exact shape

| You need | Look at |
|---|---|
| Every message and every field | [messages.schema.json](../protocol/messages.schema.json). The definitions named `req_` and `res_` followed by the capability, with dots as underscores, are the request and result bodies |
| The manifest | [provider-manifest.schema.json](../protocol/provider-manifest.schema.json) |
| Names, verdicts, platforms, strength | [common.schema.json](../protocol/common.schema.json) |
| What gets pinned for your tools | [lock.schema.json](../protocol/lock.schema.json) |
| What the kernel writes after you answer | [evidence-record.schema.json](../protocol/evidence-record.schema.json) |
| How a project is configured to use you | [configuration.md](configuration.md) |
| What the project requires to pass | [policy.schema.json](../protocol/policy.schema.json) and the [policy configuration](configuration.md#policy) |

## What is not yet written

- The canonical encoding and the path check, with test vectors. Until they exist, write paths conservatively: ASCII letters, digits, `-`, `_` and `.` inside names, and `/` between segments.
- A conformance kit that perturbs your environment to look for inputs you did not declare.
- Any kernel to run you against. Until one exists, validate your lines against the schemas yourself.
