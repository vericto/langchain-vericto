# SPDX-FileCopyrightText: 2026 Vericto S.A.S.
# SPDX-License-Identifier: Apache-2.0

import langchain_vericto
from langchain_vericto import __all__

EXPECTED_ALL = [
    "FindingDict",
    "VerdictDict",
    "VerictoSQLCheck",
    "VerictoSQLCheckInput",
    "VerictoSQLDatabase",
    "__version__",
    "verdict_to_dict",
]


def test_all_imports() -> None:
    assert sorted(EXPECTED_ALL) == sorted(__all__)


def test_every_name_resolves() -> None:
    for name in __all__:
        assert getattr(langchain_vericto, name) is not None


def test_version_matches_metadata() -> None:
    from importlib.metadata import version

    assert langchain_vericto.__version__ == version("langchain-vericto")
