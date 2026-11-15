# SPDX-FileCopyrightText: 2026 Vericto S.A.S.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from typing import Any

import pytest
from langchain_core.messages import ToolMessage
from pydantic import SecretStr, ValidationError
from vericto import VerictoConfigError, VerictoUnavailable

from langchain_vericto import VerictoSQLCheck, VerictoSQLCheckInput
from tests.unit_tests.fakes import FakeEvaluator, fake_guard, masking


def _tool(evaluator: FakeEvaluator | None = None, **kwargs: Any) -> VerictoSQLCheck:
    fail_mode = kwargs.pop("fail_mode", "closed")
    return VerictoSQLCheck(guard=fake_guard(evaluator, fail_mode=fail_mode), **kwargs)


def test_safe_select_is_allowed() -> None:
    evaluator = FakeEvaluator()
    tool = _tool(evaluator)
    content = tool.invoke({"query": "SELECT id FROM users WHERE id = 1 LIMIT 10"})
    verdict = json.loads(content)
    assert verdict["decision"] == "ALLOWED"
    assert verdict["allowed"] is True
    assert verdict["blocked"] is False
    assert verdict["rule_codes"] == []
    assert verdict["summary"].startswith("Vericto found no problem")
    assert evaluator.calls == [("SELECT id FROM users WHERE id = 1 LIMIT 10", "postgres")]


def test_delete_without_where_is_blocked_with_vericto_001() -> None:
    verdict = json.loads(_tool().invoke({"query": "DELETE FROM orders"}))
    assert verdict["decision"] == "BLOCKED"
    assert verdict["allowed"] is False
    assert verdict["blocked"] is True
    assert verdict["rule_codes"] == ["VERICTO-001"]
    assert verdict["severity"] == "critical"
    assert verdict["suggested_fix"] == "DELETE FROM orders WHERE id = $1"
    assert verdict["findings"] == [
        {
            "rule_code": "VERICTO-001",
            "severity": "critical",
            "suggested_fix": "DELETE FROM orders WHERE id = $1",
            "location": "DeleteStmt > WhereClause = NULL",
        }
    ]
    assert verdict["messages"] == [
        "VERICTO-001 (critical) matched at DeleteStmt > WhereClause = NULL."
    ]
    assert "NOT executed" in verdict["summary"]
    assert "Suggested fix: DELETE FROM orders WHERE id = $1" in verdict["summary"]
    assert verdict["mode"] == "offline"
    assert verdict["engine_version"] == "5.0.0"


def test_flagged_query_may_run_and_says_why() -> None:
    verdict = json.loads(_tool().invoke({"query": "SELECT * FROM users"}))
    assert verdict["decision"] == "FLAGGED"
    assert verdict["allowed"] is True
    assert verdict["rule_codes"] == ["VERICTO-050"]
    assert "VERICTO-050" in verdict["summary"]


def test_masked_rewrite_is_reported() -> None:
    verdict = json.loads(
        _tool(FakeEvaluator(masking)).invoke({"query": "SELECT id, email FROM customers LIMIT 10"})
    )
    assert verdict["allowed"] is True
    assert verdict["rewritten_query"] == "SELECT id, '***' AS email FROM customers LIMIT 10"
    assert verdict["event_id"] == "evt_123"
    assert "masked" in verdict["summary"]


def test_server_message_and_parse_error_are_messages() -> None:
    body = {"decision": "PARSE_ERROR", "parse_error": "syntax error at SELEC", "error": "unparsed"}
    verdict = json.loads(_tool(FakeEvaluator(lambda _sql: body)).invoke({"query": "SELEC 1"}))
    assert verdict["decision"] == "PARSE_ERROR"
    assert verdict["allowed"] is True
    assert verdict["messages"] == ["unparsed", "Parser: syntax error at SELEC"]


def test_unknown_decision_is_never_read_as_allowed() -> None:
    verdict = json.loads(
        _tool(FakeEvaluator(lambda _sql: {"decision": "MAYBE"})).invoke({"query": "SELECT 1"})
    )
    assert verdict["blocked"] is True
    assert verdict["allowed"] is False


def test_tool_call_returns_tool_message_with_artifact() -> None:
    tool = _tool()
    message = tool.invoke(
        {
            "args": {"query": "DELETE FROM orders"},
            "id": "call-1",
            "name": tool.name,
            "type": "tool_call",
        }
    )
    assert isinstance(message, ToolMessage)
    assert message.tool_call_id == "call-1"
    assert json.loads(str(message.content))["blocked"] is True
    assert message.artifact["rule_codes"] == ["VERICTO-001"]


async def test_async_invoke() -> None:
    verdict = json.loads(await _tool().ainvoke({"query": "DELETE FROM orders"}))
    assert verdict["rule_codes"] == ["VERICTO-001"]


async def test_async_tool_call() -> None:
    tool = _tool()
    message = await tool.ainvoke(
        {"args": {"query": "SELECT 1"}, "id": "call-2", "name": tool.name, "type": "tool_call"}
    )
    assert isinstance(message, ToolMessage)
    assert message.artifact["decision"] == "ALLOWED"


def test_dialect_argument_overrides_default_and_is_normalized() -> None:
    evaluator = FakeEvaluator()
    tool = _tool(evaluator, dialect="postgresql")
    assert tool.dialect == "postgres"
    tool.invoke({"query": "SELECT 1"})
    tool.invoke({"query": "SELECT 1", "dialect": "sqlite"})
    assert [d for _, d in evaluator.calls] == ["postgres", "sqlite"]


def test_input_schema_rejects_unknown_dialect_and_empty_query() -> None:
    with pytest.raises(ValidationError):
        VerictoSQLCheckInput(query="SELECT 1", dialect="db2")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        VerictoSQLCheckInput(query="")


def test_input_schema_is_described_for_the_model() -> None:
    schema = _tool().tool_call_schema.model_json_schema()  # type: ignore[union-attr]
    assert schema["required"] == ["query"]
    assert "description" in schema["properties"]["query"]
    dialects = schema["properties"]["dialect"]["anyOf"][0]["enum"]
    assert dialects == ["postgres", "mysql", "oracle", "mssql", "snowflake", "sqlite"]


def test_fail_closed_raises_when_vericto_cannot_answer() -> None:
    tool = _tool(FakeEvaluator(unavailable=True))
    with pytest.raises(VerictoUnavailable):
        tool.invoke({"query": "SELECT 1"})


def test_fail_open_returns_unevaluated_not_allowed() -> None:
    tool = _tool(FakeEvaluator(unavailable=True), fail_mode="open")
    verdict = json.loads(tool.invoke({"query": "SELECT 1"}))
    assert verdict["decision"] == "UNEVALUATED"
    assert verdict["evaluated"] is False
    assert verdict["allowed"] is False
    assert "could not evaluate" in verdict["summary"]


def test_unsupported_dialect_is_a_config_error() -> None:
    tool = _tool(FakeEvaluator(dialects=("postgres",)))
    with pytest.raises(VerictoConfigError):
        tool.check("SELECT 1", "mysql")


def test_guard_is_built_lazily_and_closed_by_the_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[dict[str, Any]] = []
    evaluator = FakeEvaluator()

    def fake_build(**kwargs: Any) -> Any:
        built.append(kwargs)
        return fake_guard(evaluator)

    monkeypatch.setattr("langchain_vericto.tools.build_guard", fake_build)
    tool = VerictoSQLCheck(api_key=SecretStr("vtro_secret"), database_id="db-1", timeout=2.0)
    assert built == []
    tool.invoke({"query": "SELECT 1"})
    tool.invoke({"query": "SELECT 2"})
    assert len(built) == 1
    assert built[0]["api_key"] == "vtro_secret"
    assert built[0]["database_id"] == "db-1"
    assert built[0]["fail_mode"] == "closed"
    assert built[0]["timeout"] == 2.0
    tool.close()
    assert evaluator.closed == 1


def test_close_leaves_a_shared_guard_open() -> None:
    evaluator = FakeEvaluator()
    tool = VerictoSQLCheck(guard=fake_guard(evaluator))
    tool.invoke({"query": "SELECT 1"})
    tool.close()
    assert evaluator.closed == 0


def test_api_key_is_secret_in_repr() -> None:
    tool = VerictoSQLCheck(api_key=SecretStr("vtro_secret"))
    assert "vtro_secret" not in repr(tool)


def test_offline_with_api_key_is_refused() -> None:
    tool = VerictoSQLCheck(offline=True, api_key=SecretStr("vtro_secret"))
    with pytest.raises(VerictoConfigError, match="choose one"):
        tool.invoke({"query": "SELECT 1"})


def test_no_mode_and_no_key_is_a_config_error() -> None:
    tool = VerictoSQLCheck()
    with pytest.raises(VerictoConfigError, match="API key"):
        tool.invoke({"query": "SELECT 1"})


def test_offline_without_cli_explains_how_to_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "")
    tool = VerictoSQLCheck(offline=True)
    with pytest.raises(VerictoConfigError, match="npm i -g @vericto/vericto-cli"):
        tool.invoke({"query": "SELECT 1"})
