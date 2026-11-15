# SPDX-FileCopyrightText: 2026 Vericto S.A.S.
# SPDX-License-Identifier: Apache-2.0

"""`VerictoSQLDatabase`: a LangChain `SQLDatabase` that checks every statement first.

Requires the `sql` extra: `pip install "langchain-vericto[sql]"` (it installs
`langchain-community` and SQLAlchemy).
"""

from __future__ import annotations

from typing import Any, Literal, Self

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine
from vericto import Vericto
from vericto.langchain import VerictoSQLDatabase as _SDKVerictoSQLDatabase

from langchain_vericto._guard import FailMode, build_guard


class VerictoSQLDatabase(_SDKVerictoSQLDatabase):
    """A `langchain_community.utilities.SQLDatabase` whose statements Vericto checks.

    It goes wherever a `SQLDatabase` goes (`SQLDatabaseToolkit`,
    `QuerySQLDatabaseTool`, `create_sql_agent`, query chains): every statement
    that `run`, `run_no_throw` or the toolkit's tools send through SQLAlchemy is
    checked by Vericto first, in the dialect of the engine.

    * Blocked: nothing runs. With `on_block="return"` (default) `run` and
      `run_no_throw` return an `Error: Vericto blocked this query (VERICTO-001,
      ...)` message with the rule and the suggested fix, so the model can correct
      its query. With `on_block="raise"` they raise `vericto.VerictoBlocked`.
    * Masked (online): the rewrite with masked sensitive columns runs instead.
    * Flagged / monitored: runs, and is logged on the `vericto` logger.
    * Vericto unavailable: `fail_mode="closed"` (default) raises
      `vericto.VerictoUnavailable` and nothing runs; `fail_mode="open"` runs the
      statement unevaluated with a `vericto.VerictoFailOpenWarning`.

    Schema reflection and the sample rows in `get_table_info` are handled as in
    the Vericto SDK (`vericto.langchain`), on which this class is built: reflection
    is not sent to Vericto, sample-row queries are checked (a blocked one is left
    out of the table info).

    Args:
        engine: the SQLAlchemy engine; `from_uri(...)` works too.
        *args: passed to `SQLDatabase`.
        offline: `True` for the local engine of the Vericto CLI (no account, the
            standard rules); `None` (default) reads `VERICTO_OFFLINE`; online
            otherwise (`VERICTO_API_KEY` and `VERICTO_DATABASE_ID`).
        api_key: Vericto API key (`proxy:evaluate` scope); default `VERICTO_API_KEY`.
        database_id: database registered in your workspace; default
            `VERICTO_DATABASE_ID`.
        api_url: Vericto API URL; default `VERICTO_API_URL`, then the public API.
        fail_mode: `"closed"` (default) or `"open"`; `None` reads `VERICTO_FAIL_MODE`.
        timeout: seconds per evaluation.
        offline_cli_path: the `vericto` binary; default `VERICTO_CLI`, then PATH.
        guard: an existing `vericto.Vericto`, instead of the arguments above.
        dialect: the Vericto dialect; read from `engine.dialect.name` when omitted.
        on_block: `"return"` (default) or `"raise"`.
        **kwargs: passed to `SQLDatabase` (and `context` / `end_user` for business
            policies, see the Vericto SDK).

    Example:
        ```python
        from langchain_vericto import VerictoSQLDatabase

        db = VerictoSQLDatabase.from_uri("sqlite:///shop.db", offline=True)
        db.run("DELETE FROM orders")
        # 'Error: Vericto blocked this query (VERICTO-001, severity critical). ...'
        ```
    """

    def __init__(
        self,
        engine: Engine,
        *args: Any,
        offline: bool | None = None,
        api_key: str | None = None,
        database_id: str | None = None,
        api_url: str | None = None,
        fail_mode: FailMode | None = "closed",
        timeout: float | None = None,
        offline_cli_path: str | None = None,
        guard: Vericto | None = None,
        dialect: str | None = None,
        on_block: Literal["return", "raise"] = "return",
        **kwargs: Any,
    ) -> None:
        """Build the guard (unless `guard` is given) and the checked `SQLDatabase`."""
        owns = guard is None
        if guard is None:
            guard = build_guard(
                offline=offline,
                api_key=api_key,
                database_id=database_id,
                api_url=api_url,
                fail_mode=fail_mode,
                timeout=timeout,
                offline_cli_path=offline_cli_path,
            )
        try:
            super().__init__(
                engine, *args, guard=guard, dialect=dialect, on_block=on_block, **kwargs
            )
        except BaseException:
            if owns:
                guard.close()
            raise
        self._lc_vericto_owns_guard = owns

    @classmethod
    def from_uri(
        cls,
        database_uri: str | URL,
        engine_args: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Self:
        """Connect with a SQLAlchemy URL; `kwargs` are the arguments of the constructor."""
        return cls(create_engine(database_uri, **(engine_args or {})), **kwargs)

    def close(self) -> None:
        """Stop checking and close the guard this database built.

        Detaches the listener from the engine; closes the guard (its HTTP pool, or
        the `vericto serve` process offline) unless it was passed in with `guard=`.
        """
        self.close_vericto()
        if self._lc_vericto_owns_guard:
            self.vericto_guard.close()
