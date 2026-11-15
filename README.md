# langchain-vericto

[![PyPI](https://img.shields.io/pypi/v/langchain-vericto?label=PyPI)](https://pypi.org/project/langchain-vericto/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

The LangChain integration for [Vericto](https://vericto.com), database guardrails
for AI agents. Vericto parses each SQL statement into an AST and checks it
against deterministic rules before it runs: `DELETE` or `UPDATE` without
`WHERE`, `DROP TABLE`, unbounded `SELECT`, and more. No LLM is involved in the
decision; the same SQL always gets the same verdict.

This package gives a LangChain agent two things:

- **`VerictoSQLCheck`**: a tool that checks a statement and returns a structured
  verdict (allowed or blocked, rule codes, messages, suggested fix) without
  running it. Sync and async.
- **`VerictoSQLDatabase`**: a drop-in `SQLDatabase` (for `SQLDatabaseToolkit`,
  `QuerySQLDatabaseTool`, `create_sql_agent` and query chains) that checks every
  statement before it reaches the database and refuses blocked ones with a
  message the agent can act on. Fail-closed by default.

Two ways to evaluate, same API:

| | Offline | Online |
|---|---|---|
| Account, network | none; the SQL never leaves the machine | a Vericto workspace; the SQL goes to the Vericto Runtime API |
| Needs | the Vericto CLI 2.1.0 or later installed | `VERICTO_API_KEY` (scope `proxy:evaluate`) and `VERICTO_DATABASE_ID` |
| Rules | the standard rules of the engine in the CLI, at their default severities | your workspace's rules: overrides, custom rules |
| Sensitive-column masking, agent allowlists, business policies, audit trail | no | yes |
| Metered | no | counts against the workspace's monthly query quota |

## Installation

```bash
pip install -U langchain-vericto            # the check tool
pip install -U "langchain-vericto[sql]"     # plus VerictoSQLDatabase (langchain-community, SQLAlchemy)
```

Python 3.11 or later.

## Quickstart: offline, no account

Install the Vericto CLI (it carries the engine; nothing is downloaded at run
time):

```bash
npm i -g @vericto/vericto-cli        # or: brew install vericto/tap/vericto
vericto --version                    # 2.1.0 or later
```

Check a statement:

```python
import json

from langchain_vericto import VerictoSQLCheck

tool = VerictoSQLCheck(offline=True, dialect="postgres")

verdict = json.loads(tool.invoke({"query": "DELETE FROM users"}))
verdict["decision"]  # 'BLOCKED'
verdict["rule_codes"]  # ['VERICTO-001']
verdict["suggested_fix"]  # 'DELETE FROM users WHERE id = $1'

json.loads(tool.invoke({"query": "SELECT id FROM users WHERE id = 42 LIMIT 1"}))["decision"]
# 'ALLOWED'
```

Guard a database (here SQLite; any SQLAlchemy URL works):

```python
from langchain_vericto import VerictoSQLDatabase

db = VerictoSQLDatabase.from_uri("sqlite:///shop.db", offline=True)

db.run("SELECT id, total FROM orders WHERE id = 1 LIMIT 10")  # runs
db.run("DELETE FROM orders")
# Error: Vericto blocked this query (VERICTO-001, severity critical). It was NOT executed.
# Suggested fix: DELETE FROM orders WHERE id = $1
# Rewrite the query following the suggested fix and try again.
```

The dialect comes from the engine (`sqlite` here). `examples/quickstart.py` runs
all of this end to end.

## Quickstart: online, your workspace's rules

Create an API key with the `proxy:evaluate` scope in the Vericto dashboard and
register the database you are protecting. Then:

```bash
export VERICTO_API_KEY="vtro_..."
export VERICTO_DATABASE_ID="..."     # the registered database's id
```

```python
from langchain_vericto import VerictoSQLCheck, VerictoSQLDatabase

tool = VerictoSQLCheck(dialect="postgres")
db = VerictoSQLDatabase.from_uri("postgresql+psycopg://...")
```

The verdicts now follow your workspace's rules, sensitive columns come back
masked (`rewritten_query`, and the database runs the rewrite), and every
evaluation has an `event_id` in the audit trail.

Offline mode is never chosen on its own: with no `offline=True`, no
`VERICTO_OFFLINE=1` and no API key, the first check raises
`vericto.VerictoConfigError`. Offline mode combined with an API key raises too
("choose one"), so a missing secret can never quietly fall back to fewer rules.

## Use it in an agent

```python
# pip install "langchain-vericto[sql]" "langchain[anthropic]"
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_community.agent_toolkits import SQLDatabaseToolkit

from langchain_vericto import VerictoSQLCheck, VerictoSQLDatabase

db = VerictoSQLDatabase.from_uri("sqlite:///shop.db", offline=True)
model = init_chat_model("claude-sonnet-4-6")  # any chat model with tool calling

toolkit = SQLDatabaseToolkit(db=db, llm=model)
agent = create_agent(
    model=model,
    tools=[*toolkit.get_tools(), VerictoSQLCheck.from_database(db)],
    system_prompt=(
        "You answer questions about the shop database. Check every query with "
        "vericto_sql_check before running it, and never run a blocked query."
    ),
)
agent.invoke({"messages": [{"role": "user", "content": "Delete all orders."}]})
```

Every query the toolkit runs goes through Vericto, whether or not the model
calls the check tool first: the check tool lets it ask before it tries, the
database refuses what is blocked either way.

## The verdict

`VerictoSQLCheck` returns the verdict as a JSON string; called with a
`ToolCall`, the `ToolMessage` carries the same dict as its `artifact`.
`tool.check(query)` returns the SDK's `vericto.Verdict`, and
`langchain_vericto.verdict_to_dict` turns it into the dict.

| Key | Meaning |
|---|---|
| `decision` | `ALLOWED`, `FLAGGED`, `MONITORED`, `PARSE_ERROR`, `BLOCKED`, or `UNEVALUATED` (no verdict, `fail_mode="open"`) |
| `allowed` | Vericto lets it run: `ALLOWED`, `FLAGGED`, `MONITORED`, `PARSE_ERROR`. Never for `BLOCKED` or `UNEVALUATED`. |
| `blocked`, `evaluated` | booleans |
| `rule_codes` | rules that matched, deciding rule first (`["VERICTO-001"]`) |
| `severity` | the deciding rule's severity |
| `messages` | readable reasons (server message, each finding and where it matched) |
| `suggested_fix` | a safer statement or advice, when Vericto has one |
| `findings` | `rule_code`, `severity`, `suggested_fix`, `location` (AST path) per rule |
| `rewritten_query` | the statement that runs instead, sensitive columns masked (online) |
| `dialect`, `mode`, `engine_version`, `ruleset_version`, `event_id` | provenance: `mode` is `offline` or `online`; `event_id` online only |
| `summary` | one paragraph for the model: what happened and what to do next |

A text with several statements gets one verdict, the strongest finding among
them: `SELECT 1; DELETE FROM orders` is `BLOCKED` by `VERICTO-001`.

## Fail mode

When Vericto cannot answer (network, timeout, quota, the local engine process
failing):

- `fail_mode="closed"` (default): `vericto.VerictoUnavailable` is raised and
  nothing runs. It is never turned into text for the model.
- `fail_mode="open"`: `VerictoSQLDatabase` runs the statement unevaluated with a
  `vericto.VerictoFailOpenWarning`; `VerictoSQLCheck` returns an `UNEVALUATED`
  verdict with `allowed: false`.
- `fail_mode=None`: read `VERICTO_FAIL_MODE` (closed when unset).

Configuration errors (bad key, missing scope, no CLI in offline mode, an
unsupported dialect) raise `vericto.VerictoConfigError` in both modes.

## Configuration

Both classes take the same connection arguments; each falls back to an
environment variable.

| Argument | Environment | Default |
|---|---|---|
| `offline` | `VERICTO_OFFLINE` | online |
| `api_key` | `VERICTO_API_KEY` | required online |
| `database_id` | `VERICTO_DATABASE_ID` | required online |
| `api_url` | `VERICTO_API_URL` | `https://api.vericto.com` |
| `fail_mode` | `VERICTO_FAIL_MODE` (only with `fail_mode=None`) | `"closed"` |
| `timeout` | `VERICTO_TIMEOUT` (online) | 5 s online, 30 s offline |
| `offline_cli_path` | `VERICTO_CLI` | `vericto` on `PATH` |
| `guard` | | a `vericto.Vericto` to share instead |

`VerictoSQLCheck` also takes `dialect` (default `postgres`; the model may pass
another one per call). `VerictoSQLDatabase` takes every `SQLDatabase` argument,
`dialect` (default: the engine's), `on_block` (`"return"`, default, or `"raise"`
to raise `vericto.VerictoBlocked`), and `context` / `end_user` for business
policies (see the [Vericto SDK](https://github.com/vericto/vericto-python#readme)).

Call `close()` on either object when you are done: it stops the local
`vericto serve` process (offline) or closes the HTTP pool (online). A guard
passed with `guard=` is left to its owner.

## How it works, and its limits

The evaluation is done by the official Vericto SDK for Python
([`vericto`](https://pypi.org/project/vericto/), Apache-2.0), which this package
depends on; `VerictoSQLDatabase` is built on the SDK's `vericto.langchain`
integration.

- **Online**, the SDK sends the statement (never parameter values) to the
  Vericto Runtime API (`POST /api/v1/proxy/query`, header `X-API-Key`, scope
  `proxy:evaluate`) over HTTPS, with retries and backoff.
- **Offline**, the SDK starts the installed Vericto CLI once as
  `vericto serve --stdio` and sends it JSON Lines over a pipe. The engine runs
  in that separate process (it is AGPL-3.0-only and is never imported, linked or
  bundled by this package). No network listener, no request to anyone.

Limits, stated plainly:

- Offline mode needs the CLI installed and checks the standard rules only: no
  custom rules or severity overrides, no masking, no agent allowlists, no
  business policies, no audit trail. It answers "is this SQL obviously
  dangerous?", not "is this allowed by my organization's policy?".
- Vericto checks the statement, not the data: it does not know how many rows a
  `WHERE` matches, and it does not replace database permissions. Give the agent
  a database role with the least privilege it needs as well.
- A statement Vericto cannot parse is `PARSE_ERROR`: offline (and by default
  online) it is allowed to run and reported, per policy.
- The SDK is synchronous; the async paths run it in a worker thread.
- `VerictoSQLDatabase` subclasses `langchain_community`'s `SQLDatabase`.
  [`langchain-community` is being sunset](https://github.com/langchain-ai/langchain-community/issues/674):
  it still installs and works (0.4.x), and it is only needed for the `sql`
  extra. `VerictoSQLCheck` depends on `langchain-core` alone. For SQLAlchemy code
  without `SQLDatabase`, `vericto.sqlalchemy.instrument(engine)` from the SDK
  guards an engine directly.
- Suggested fixes come from the engine and may use placeholders (`$1`) that you
  fill in; they are advice, not SQL to run blindly.

## Development

```bash
uv sync                                   # Python 3.11+, uv
make lint                                 # ruff check, ruff format --check, mypy
make test                                 # unit tests, LangChain standard tests, no network
make integration_test                     # against the real engine (see below)
uv build && uvx twine check --strict dist/*
```

Integration tests run offline against the real engine when a Vericto CLI is on
`PATH` or in `VERICTO_CLI` (`VERICTO_REQUIRE_CLI=1` makes a missing CLI a
failure instead of a skip), and online when `VERICTO_API_KEY` and
`VERICTO_DATABASE_ID` are set. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[Apache License 2.0](LICENSE). See [NOTICE](NOTICE) and
[TRADEMARKS.md](TRADEMARKS.md). The Vericto engine and CLI are separate programs
under their own license (AGPL-3.0-only); this package talks to the CLI as a
separate process and does not include it.
