# Reference providers

Reference providers are examples of the [protocol](../protocol/README.md); none is privileged over a third-party provider.

| Provider | Name in its manifest | Capabilities | What it reads |
|---|---|---|---|
| [tlc/](tlc/) | `dodona.tla` | `obligation.enumerate`, `obligation.check` | Each model folder's `expected.json`, and what the model checker printed |
| [intents/](intents/) | `dodona.intent.markdown` | `intent.index` | `intents/*.md`, refusing a file that could be read more than one way |
