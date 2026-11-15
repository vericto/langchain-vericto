# SPDX-FileCopyrightText: 2026 Vericto S.A.S.
# SPDX-License-Identifier: Apache-2.0

"""The README's agent, with a scripted model instead of an LLM."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from langchain.agents import create_agent
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from langchain_vericto import VerictoSQLCheck, VerictoSQLDatabase
from tests.unit_tests.fakes import FakeEvaluator, fake_guard


class ScriptedModel(BaseChatModel):
    """Answers the n-th turn with the n-th scripted message."""

    script: list[AIMessage]

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        turn = sum(isinstance(m, AIMessage) for m in messages)
        return ChatResult(generations=[ChatGeneration(message=self.script[turn])])

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        return self


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    eng = create_engine(f"sqlite:///{tmp_path / 'shop.db'}")
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE orders (id INTEGER PRIMARY KEY, total INTEGER)"))
        conn.execute(text("INSERT INTO orders VALUES (1, 10), (2, 20)"))
    yield eng
    eng.dispose()


def test_agent_is_refused_and_told_why(engine: Engine) -> None:
    db = VerictoSQLDatabase(engine, guard=fake_guard(FakeEvaluator()))
    model = ScriptedModel(
        script=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "vericto_sql_check",
                        "args": {"query": "DELETE FROM orders"},
                        "id": "c1",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "sql_db_query", "args": {"query": "DELETE FROM orders"}, "id": "c2"}
                ],
            ),
            AIMessage(content="Vericto blocked deleting every order (VERICTO-001)."),
        ]
    )
    toolkit = SQLDatabaseToolkit(db=db, llm=model)
    agent = create_agent(
        model=model, tools=[*toolkit.get_tools(), VerictoSQLCheck.from_database(db)]
    )

    result = agent.invoke({"messages": [{"role": "user", "content": "Delete all orders."}]})

    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    check, query = tool_messages
    assert check.artifact["blocked"] is True
    assert check.artifact["rule_codes"] == ["VERICTO-001"]
    assert "Vericto blocked this query (VERICTO-001" in str(query.content)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM orders")).scalar_one() == 2
