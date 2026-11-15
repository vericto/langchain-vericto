# SPDX-FileCopyrightText: 2026 Vericto S.A.S.
# SPDX-License-Identifier: Apache-2.0

"""LangChain integration for Vericto, database guardrails for AI agents.

* `VerictoSQLCheck`: a tool that checks a SQL statement with Vericto and returns
  a structured verdict, without running it.
* `VerictoSQLDatabase`: a `SQLDatabase` that checks every statement before it
  runs and refuses blocked ones (needs the `sql` extra).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_vericto._verdict import FindingDict, VerdictDict, verdict_to_dict
from langchain_vericto._version import __version__
from langchain_vericto.tools import VerictoSQLCheck, VerictoSQLCheckInput

if TYPE_CHECKING:
    from langchain_vericto.sql_database import VerictoSQLDatabase

__all__ = [
    "FindingDict",
    "VerdictDict",
    "VerictoSQLCheck",
    "VerictoSQLCheckInput",
    "VerictoSQLDatabase",
    "__version__",
    "verdict_to_dict",
]


def __getattr__(name: str) -> Any:
    # VerictoSQLDatabase needs langchain-community and SQLAlchemy (the `sql`
    # extra): import it only when it is asked for.
    if name == "VerictoSQLDatabase":
        try:
            from langchain_vericto.sql_database import VerictoSQLDatabase
        except ImportError as exc:
            msg = (
                "VerictoSQLDatabase needs langchain-community and SQLAlchemy: "
                'pip install "langchain-vericto[sql]"'
            )
            raise ImportError(msg) from exc
        return VerictoSQLDatabase
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
