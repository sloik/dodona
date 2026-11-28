# Reference providers

Reference providers are examples of the [protocol](../protocol/README.md); none is privileged over a third-party provider.

| Provider | Name in its manifest | Capabilities | What it reads |
|---|---|---|---|
| [tlc/](tlc/) | `dodona.tla` | `obligation.enumerate`, `obligation.check` | Each model folder's `expected.json`, and what the model checker printed |
| [intents/](intents/) | `dodona.intent.markdown` | `intent.index` | `intents/*.md`, refusing a file that could be read more than one way |
| [node-test/](node-test/provider.py) | `dodona.node-test` | `obligation.enumerate`, `obligation.check` | One top-level test with a literal name per bound test file and its stock Node TAP result |

The [Node provider decision](../decisions/0035-a-test-runner-provider.md) gives the file rule and verdict. Each obligation declares the entire selected binding as input. Node receives the file as an operand and reports the test name. Exactly one matching top-level result and its corresponding exit can supply a sampled pass or failure. A skipped, differently named or additional result supplies no evidence. Test names must differ from their own file paths because Node can use the file path when no test ran.

The [checkout retry example](../examples/checkout-retry/README.md) binds separate model and runtime checks. Its evidence shows what happens when either the implementation or an assumption changes.
