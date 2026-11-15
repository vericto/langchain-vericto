# SPDX-FileCopyrightText: 2026 Vericto S.A.S.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import warnings
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.tools.sql_database.tool import QuerySQLDatabaseTool
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from vericto import VerictoBlocked, VerictoConfigError, VerictoFailOpenWarning, VerictoUnavailable

from langchain_vericto import VerictoSQLCheck, VerictoSQLDatabase
from tests.unit_tests.fakes import FakeEvaluator, fake_guard, masking


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    eng = create_engine(f"sqlite:///{tmp_path / 'shop.db'}")
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE orders (id INTEGER PRIMARY KEY, total INTEGER)"))
        conn.execute(text("INSERT INTO orders VALUES (1, 10), (2, 20)"))
        conn.execute(text("CREATE TABLE customers (id INTEGER PRIMARY KEY, email TEXT)"))
        conn.execute(text("INSERT INTO customers VALUES (1, 'ana@example.com')"))
    yield eng
    eng.dispose()


def _count(engine: Engine) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text("SELECT count(*) FROM orders")).scalar_one())


def _db(engine: Engine, evaluator: FakeEvaluator, **kwargs: Any) -> VerictoSQLDatabase:
    fail_mode = kwargs.pop("fail_mode", "closed")
    return VerictoSQLDatabase(engine, guard=fake_guard(evaluator, fail_mode=fail_mode), **kwargs)


def test_dialect_comes_from_the_engine(engine: Engine) -> None:
    db = _db(engine, FakeEvaluator())
    assert db.vericto_dialect == "sqlite"
    assert db.dialect == "sqlite"


def test_safe_select_runs_and_is_checked(engine: Engine) -> None:
    evaluator = FakeEvaluator()
    db = _db(engine, evaluator)
    evaluator.calls.clear()
    assert db.run("SELECT id, total FROM orders WHERE id = 1 LIMIT 5") == "[(1, 10)]"
    assert evaluator.calls == [("SELECT id, total FROM orders WHERE id = 1 LIMIT 5", "sqlite")]


def test_delete_without_where_is_refused_with_a_message(engine: Engine) -> None:
    db = _db(engine, FakeEvaluator())
    result = db.run("DELETE FROM orders")
    assert isinstance(result, str)
    assert result.startswith("Error: Vericto blocked this query (VERICTO-001, severity critical)")
    assert "It was NOT executed." in result
    assert "Suggested fix: DELETE FROM orders WHERE id = $1" in result
    assert _count(engine) == 2


def test_run_no_throw_refuses_too(engine: Engine) -> None:
    db = _db(engine, FakeEvaluator())
    result = db.run_no_throw("DELETE FROM orders")
    assert isinstance(result, str)
    assert "VERICTO-001" in result
    assert _count(engine) == 2


def test_on_block_raise(engine: Engine) -> None:
    db = _db(engine, FakeEvaluator(), on_block="raise")
    with pytest.raises(VerictoBlocked) as info:
        db.run("DELETE FROM orders")
    assert info.value.verdict.rule_code == "VERICTO-001"
    with pytest.raises(VerictoBlocked):
        db.run_no_throw("DELETE FROM orders")
    assert _count(engine) == 2


def test_masked_rewrite_runs_instead_of_the_original(engine: Engine) -> None:
    db = _db(engine, FakeEvaluator(masking))
    assert db.run("SELECT id, email FROM customers LIMIT 10") == "[(1, '***')]"


def test_fail_closed_raises_and_runs_nothing(engine: Engine) -> None:
    db = _db(engine, FakeEvaluator(unavailable=True))
    with pytest.raises(VerictoUnavailable):
        db.run("DELETE FROM orders WHERE id = 1")
    assert _count(engine) == 2


def test_fail_open_runs_unevaluated_with_a_warning(engine: Engine) -> None:
    db = _db(engine, FakeEvaluator(unavailable=True), fail_mode="open")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        db.run("DELETE FROM orders WHERE id = 1")
    assert any(issubclass(w.category, VerictoFailOpenWarning) for w in caught)
    assert _count(engine) == 1


def test_toolkit_query_tool_is_guarded(engine: Engine) -> None:
    db = _db(engine, FakeEvaluator())
    toolkit = SQLDatabaseToolkit(db=db, llm=FakeListChatModel(responses=["ok"]))
    query_tool = next(t for t in toolkit.get_tools() if isinstance(t, QuerySQLDatabaseTool))
    result = query_tool.invoke({"query": "DELETE FROM orders"})
    assert "Vericto blocked this query (VERICTO-001" in result
    assert _count(engine) == 2


def test_from_uri_builds_the_guard_from_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evaluator = FakeEvaluator()
    seen: dict[str, Any] = {}

    def fake_build(**kwargs: Any) -> Any:
        seen.update(kwargs)
        return fake_guard(evaluator)

    monkeypatch.setattr("langchain_vericto.sql_database.build_guard", fake_build)
    db = VerictoSQLDatabase.from_uri(f"sqlite:///{tmp_path / 'x.db'}", offline=True, timeout=3.0)
    assert seen["offline"] is True
    assert seen["fail_mode"] == "closed"
    assert seen["timeout"] == 3.0
    db.close()
    db._engine.dispose()
    assert evaluator.closed == 1


def test_close_leaves_a_shared_guard_open(engine: Engine) -> None:
    evaluator = FakeEvaluator()
    db = _db(engine, evaluator)
    db.close()
    assert evaluator.closed == 0
    # Detached: statements are no longer checked.
    evaluator.calls.clear()
    db.run("SELECT 1")
    assert evaluator.calls == []


def test_guard_is_closed_when_construction_fails(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    evaluator = FakeEvaluator(dialects=("postgres",))
    monkeypatch.setattr(
        "langchain_vericto.sql_database.build_guard", lambda **_kw: fake_guard(evaluator)
    )
    with pytest.raises(VerictoConfigError):
        VerictoSQLDatabase(engine)  # sqlite is not supported by this evaluator
    assert evaluator.closed == 1


def test_check_tool_from_database_shares_guard_and_dialect(engine: Engine) -> None:
    evaluator = FakeEvaluator()
    db = _db(engine, evaluator)
    tool = VerictoSQLCheck.from_database(db)
    assert tool.get_guard() is db.vericto_guard
    verdict = json.loads(tool.invoke({"query": "DELETE FROM orders"}))
    assert verdict["dialect"] == "sqlite"
    assert verdict["rule_codes"] == ["VERICTO-001"]
