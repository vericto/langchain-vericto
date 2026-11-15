# Changelog

All notable changes to this package are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - Unreleased

First release.

### Added

- `VerictoSQLCheck`, a LangChain tool (`BaseTool`, typed `args_schema`, sync and
  async) that checks a SQL statement with Vericto without running it and returns
  a structured verdict as JSON: `decision`, `allowed`, `blocked`, `rule_codes`,
  `messages`, `suggested_fix`, `findings`, `rewritten_query`, provenance (`mode`,
  `engine_version`, `ruleset_version`, `event_id`) and a `summary` for the model.
  With a `ToolCall`, the `ToolMessage` carries the verdict dict as its
  `artifact`. `VerictoSQLCheck.from_database(db)` shares a database's guard and
  dialect.
- `VerictoSQLDatabase` (extra `sql`), a `langchain_community` `SQLDatabase` that
  checks every statement before it runs (`run`, `run_no_throw`,
  `SQLDatabaseToolkit`, `QuerySQLDatabaseTool`) in the engine's dialect, and
  refuses blocked ones with a message naming the rule and the suggested fix
  (`on_block="return"`, default) or `vericto.VerictoBlocked` (`"raise"`). Built on
  the Vericto SDK's `vericto.langchain` integration.
- Offline mode (`offline=True` or `VERICTO_OFFLINE=1`): the standard rules of the
  local engine in the Vericto CLI 2.1.0+, no account, no network. Online mode
  (`VERICTO_API_KEY`, `VERICTO_DATABASE_ID`): your workspace's rules through the
  Vericto Runtime API.
- `fail_mode="closed"` by default for both classes; `"open"` and `None`
  (`VERICTO_FAIL_MODE`) are opt-in.
- LangChain standard tests (`langchain-tests` 1.1.9): `ToolsUnitTests` and,
  offline against the real engine, `ToolsIntegrationTests`.
