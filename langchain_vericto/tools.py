# SPDX-FileCopyrightText: 2026 Vericto S.A.S.
# SPDX-License-Identifier: Apache-2.0

"""`VerictoSQLCheck`: ask Vericto whether a SQL statement may run, without running it."""

from __future__ import annotations

import asyncio
import json
import threading
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.tools import BaseTool
from langchain_core.utils import from_env, secret_from_env
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, SecretStr, field_validator
from vericto import Vericto, normalize_dialect

from langchain_vericto._guard import FailMode, build_guard
from langchain_vericto._verdict import VerdictDict, verdict_to_dict

if TYPE_CHECKING:
    from vericto import Verdict

    from langchain_vericto.sql_database import VerictoSQLDatabase

Dialect = Literal["postgres", "mysql", "oracle", "mssql", "snowflake", "sqlite"]


class VerictoSQLCheckInput(BaseModel):
    """Input of `VerictoSQLCheck`."""

    query: str = Field(
        description="The exact SQL statement (or statements) you intend to run.",
        min_length=1,
    )
    dialect: Dialect | None = Field(
        default=None,
        description=(
            "The SQL dialect of the database. Omit it to use the dialect the tool "
            "was configured with."
        ),
    )


class VerictoSQLCheck(BaseTool):
    """Check a SQL statement with Vericto, database guardrails for AI agents.

    Vericto parses the statement into an AST and checks it against deterministic
    rules (for example `VERICTO-001`, DELETE without WHERE) before anything runs.
    Nothing is executed: the tool returns the verdict as JSON (see
    `langchain_vericto.VerdictDict`): `decision`, `allowed`, `blocked`,
    `rule_codes`, `messages`, `suggested_fix`, `findings`, `mode` and a `summary`
    for the model. Called with a `ToolCall`, the `ToolMessage` also carries the
    verdict dict as its `artifact`.

    Setup:
        Install `langchain-vericto`, then pick a mode:

        * Offline, no account: install the Vericto CLI 2.1.0 or later
          (`npm i -g @vericto/vericto-cli` or `brew install vericto/tap/vericto`)
          and pass `offline=True` (or set `VERICTO_OFFLINE=1`). The CLI's local
          engine checks the standard rules; nothing leaves the machine.
        * Online, your workspace's rules: set `VERICTO_API_KEY` (a key with the
          `proxy:evaluate` scope) and `VERICTO_DATABASE_ID`.

        ```bash
        pip install -U langchain-vericto
        export VERICTO_API_KEY="vtro_..."
        export VERICTO_DATABASE_ID="..."
        ```

    Key init args:
        dialect: default dialect (`postgres`, `mysql`, `oracle`, `mssql`,
            `snowflake`, `sqlite`); the model may pass another one per call.
        offline: `True` for the local engine; `None` (default) reads
            `VERICTO_OFFLINE`; online otherwise.
        api_key: Vericto API key; defaults to `VERICTO_API_KEY`.
        database_id: the database registered in your workspace; defaults to
            `VERICTO_DATABASE_ID`.
        fail_mode: when Vericto cannot answer: `"closed"` (default) raises
            `vericto.VerictoUnavailable`; `"open"` returns an `UNEVALUATED`
            verdict (`allowed: false`).
        guard: an existing `vericto.Vericto` to share (overrides the other
            connection arguments).

    Instantiate:
        ```python
        from langchain_vericto import VerictoSQLCheck

        tool = VerictoSQLCheck(offline=True, dialect="postgres")
        ```

    Invoke directly with args:
        ```python
        tool.invoke({"query": "DELETE FROM users"})
        ```

        ```json
        {"decision": "BLOCKED", "allowed": false, "blocked": true,
         "rule_codes": ["VERICTO-001"], "suggested_fix": "DELETE FROM users WHERE id = $1", ...}
        ```

    Invoke with a tool call:
        ```python
        tool.invoke(
            {
                "args": {"query": "DELETE FROM users"},
                "id": "1",
                "name": tool.name,
                "type": "tool_call",
            }
        )
        ```
    """

    name: str = "vericto_sql_check"
    description: str = (
        "Check a SQL query with Vericto (database guardrails for AI agents) BEFORE running "
        "it. Input: the exact SQL. Output: JSON with `allowed`, `blocked`, the matched "
        "rule codes, a suggested fix and a summary. Do not run a query this tool reports "
        "as blocked: rewrite it following the suggested fix and check it again."
    )
    args_schema: type[BaseModel] = VerictoSQLCheckInput
    response_format: Literal["content", "content_and_artifact"] = "content_and_artifact"

    dialect: str = "postgres"
    """Dialect used when the model does not pass one."""
    offline: bool | None = None
    """`True`: the local engine of the Vericto CLI. `None`: `VERICTO_OFFLINE`."""
    api_key: SecretStr | None = Field(
        default_factory=secret_from_env("VERICTO_API_KEY", default=None)
    )
    """Vericto API key (`proxy:evaluate` scope). Defaults to `VERICTO_API_KEY`."""
    database_id: str | None = Field(default_factory=from_env("VERICTO_DATABASE_ID", default=None))
    """Database registered in your Vericto workspace. Defaults to `VERICTO_DATABASE_ID`."""
    api_url: str | None = None
    """Vericto API URL. Defaults to `VERICTO_API_URL`, then `https://api.vericto.com`."""
    fail_mode: FailMode | None = "closed"
    """`"closed"` (default) or `"open"`; `None` reads `VERICTO_FAIL_MODE`."""
    timeout: float | None = None
    """Seconds per evaluation (SDK defaults: 5 s online, 30 s offline)."""
    offline_cli_path: str | None = None
    """The `vericto` binary for offline mode. Defaults to `VERICTO_CLI`, then PATH."""
    guard: Vericto | None = Field(default=None, exclude=True)
    """A `vericto.Vericto` to use instead of building one."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    _guard: Vericto | None = PrivateAttr(default=None)
    _owns_guard: bool = PrivateAttr(default=False)
    _lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)

    @field_validator("dialect")
    @classmethod
    def _normalize_dialect(cls, value: str) -> str:
        return normalize_dialect(value)

    @classmethod
    def from_database(cls, db: VerictoSQLDatabase, **kwargs: Any) -> VerictoSQLCheck:
        """A check tool that shares the guard and the dialect of a `VerictoSQLDatabase`."""
        return cls(guard=db.vericto_guard, dialect=db.vericto_dialect, **kwargs)

    def get_guard(self) -> Vericto:
        """The `vericto.Vericto` guard, built on first use (thread-safe)."""
        if self.guard is not None:
            return self.guard
        with self._lock:
            if self._guard is None:
                self._guard = build_guard(
                    offline=self.offline,
                    api_key=self.api_key.get_secret_value() if self.api_key else None,
                    database_id=self.database_id,
                    api_url=self.api_url,
                    fail_mode=self.fail_mode,
                    timeout=self.timeout,
                    offline_cli_path=self.offline_cli_path,
                )
                self._owns_guard = True
            return self._guard

    def check(self, query: str, dialect: str | None = None) -> Verdict:
        """The `vericto.Verdict` for `query`. Nothing is executed.

        Raises:
            vericto.VerictoUnavailable: Vericto could not answer and
                `fail_mode="closed"`.
            vericto.VerictoConfigError: misconfiguration (no API key, no `vericto`
                CLI in offline mode, unsupported dialect, ...), in both fail modes.
        """
        return self.get_guard().check(query, normalize_dialect(dialect or self.dialect))

    def close(self) -> None:
        """Close the guard this tool built (its HTTP pool, or the `vericto serve` process).

        A guard passed in with `guard=` is left open: its owner closes it.
        """
        with self._lock:
            if self._guard is not None and self._owns_guard:
                self._guard.close()
            self._guard = None
            self._owns_guard = False

    def _run(
        self,
        query: str,
        dialect: str | None = None,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> tuple[str, VerdictDict]:
        verdict = verdict_to_dict(self.check(query, dialect))
        return json.dumps(verdict, ensure_ascii=False), verdict

    async def _arun(
        self,
        query: str,
        dialect: str | None = None,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> tuple[str, VerdictDict]:
        # The SDK is synchronous (an HTTP pool online, a pipe to `vericto serve`
        # offline, both thread-safe): run it in a worker thread so the event loop
        # is never blocked.
        verdict = verdict_to_dict(await asyncio.to_thread(self.check, query, dialect))
        return json.dumps(verdict, ensure_ascii=False), verdict
