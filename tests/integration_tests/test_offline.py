# SPDX-FileCopyrightText: 2026 Vericto S.A.S.
# SPDX-License-Identifier: Apache-2.0

"""Offline mode against the real local engine of the Vericto CLI."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from langchain_tests.integration_tests import ToolsIntegrationTests
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from vericto import VerictoBlocked

from langchain_vericto import VerictoSQLCheck, VerictoSQLDatabase


@pytest.fixture
def check(offline_env: str) -> Iterator[VerictoSQLCheck]:
    tool = VerictoSQLCheck(offline=True, offline_cli_path=offline_env)
    yield tool
    tool.close()


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    eng = create_engine(f"sqlite:///{tmp_path / 'shop.db'}")
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE orders (id INTEGER PRIMARY KEY, total INTEGER)"))
        conn.execute(text("INSERT INTO orders VALUES (1, 10), (2, 20)"))
    yield eng
    eng.dispose()


def _count(engine: Engine) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text("SELECT count(*) FROM orders")).scalar_one())


def test_safe_select_is_allowed(check: VerictoSQLCheck) -> None:
    verdict = json.loads(
        check.invoke({"query": "SELECT id, total FROM orders WHERE id = 1 LIMIT 10"})
    )
    assert verdict["decision"] == "ALLOWED"
    assert verdict["allowed"] is True
    assert verdict["mode"] == "offline"
    assert verdict["engine_version"]
    assert verdict["ruleset_version"].startswith("standard@engine-")


@pytest.mark.parametrize("dialect", ["postgres", "mysql", "oracle", "mssql", "snowflake", "sqlite"])
def test_delete_without_where_is_blocked_with_vericto_001(
    check: VerictoSQLCheck, dialect: str
) -> None:
    verdict = json.loads(check.invoke({"query": "DELETE FROM orders", "dialect": dialect}))
    assert verdict["decision"] == "BLOCKED"
    assert verdict["blocked"] is True
    assert verdict["rule_codes"][0] == "VERICTO-001"
    assert verdict["severity"] == "critical"
    assert verdict["suggested_fix"]
    assert verdict["dialect"] == dialect


def test_strongest_finding_of_several_statements(check: VerictoSQLCheck) -> None:
    verdict = json.loads(check.invoke({"query": "SELECT 1; DELETE FROM orders"}))
    assert verdict["rule_codes"][0] == "VERICTO-001"


async def test_async_and_sync_agree(check: VerictoSQLCheck) -> None:
    sync = json.loads(check.invoke({"query": "UPDATE orders SET total = 0"}))
    # Concurrent calls share one `vericto serve` process.
    results = await asyncio.gather(
        *(check.ainvoke({"query": "UPDATE orders SET total = 0"}) for _ in range(5))
    )
    assert all(json.loads(r)["rule_codes"] == sync["rule_codes"] for r in results)
    assert sync["blocked"] is True


def test_sql_database_refuses_delete_without_where(offline_env: str, engine: Engine) -> None:
    db = VerictoSQLDatabase(engine, offline=True, offline_cli_path=offline_env)
    try:
        assert db.vericto_dialect == "sqlite"
        assert db.run("SELECT id, total FROM orders WHERE id = 1 LIMIT 5") == "[(1, 10)]"
        result = db.run("DELETE FROM orders")
        assert isinstance(result, str)
        assert result.startswith("Error: Vericto blocked this query (VERICTO-001")
        assert db.run_no_throw("DELETE FROM orders").startswith("Error: Vericto blocked")  # type: ignore[union-attr]
        assert _count(engine) == 2
        # A safe, targeted DELETE goes through.
        db.run("DELETE FROM orders WHERE id = 2")
        assert _count(engine) == 1
    finally:
        db.close()


def test_sql_database_on_block_raise(offline_env: str, engine: Engine) -> None:
    db = VerictoSQLDatabase(engine, offline=True, offline_cli_path=offline_env, on_block="raise")
    try:
        with pytest.raises(VerictoBlocked) as info:
            db.run("DELETE FROM orders")
        assert info.value.verdict.rule_code == "VERICTO-001"
        assert info.value.verdict.mode == "offline"
        assert _count(engine) == 2
    finally:
        db.close()


@pytest.mark.usefixtures("offline_env")
class TestVerictoSQLCheckStandardOffline(ToolsIntegrationTests):
    """LangChain standard integration tests, offline."""

    @property
    def tool_constructor(self) -> type[VerictoSQLCheck]:
        return VerictoSQLCheck

    @property
    def tool_constructor_params(self) -> dict[str, Any]:
        return {"offline": True}

    @property
    def tool_invoke_params_example(self) -> dict[str, Any]:
        return {"query": "DELETE FROM orders"}
