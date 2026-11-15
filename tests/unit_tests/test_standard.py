# SPDX-FileCopyrightText: 2026 Vericto S.A.S.
# SPDX-License-Identifier: Apache-2.0

"""LangChain standard unit tests for `VerictoSQLCheck`."""

from __future__ import annotations

from typing import Any

from langchain_tests.unit_tests import ToolsUnitTests

from langchain_vericto import VerictoSQLCheck


class TestVerictoSQLCheckStandard(ToolsUnitTests):
    @property
    def tool_constructor(self) -> type[VerictoSQLCheck]:
        return VerictoSQLCheck

    @property
    def tool_constructor_params(self) -> dict[str, Any]:
        # The guard is built on first use, so construction needs no CLI or network.
        return {"offline": True, "dialect": "postgres"}

    @property
    def tool_invoke_params_example(self) -> dict[str, Any]:
        return {"query": "SELECT id FROM users WHERE id = 1 LIMIT 10"}

    @property
    def init_from_env_params(self) -> tuple[dict[str, str], dict[str, Any], dict[str, Any]]:
        return (
            {"VERICTO_API_KEY": "vtro_test_key", "VERICTO_DATABASE_ID": "db-123"},
            {},
            {"api_key": "vtro_test_key", "database_id": "db-123"},
        )
