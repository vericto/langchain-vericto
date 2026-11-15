# SPDX-FileCopyrightText: 2026 Vericto S.A.S.
# SPDX-License-Identifier: Apache-2.0

"""Quickstart: the code of the README and the LangChain docs page, end to end.

Offline (default): needs the Vericto CLI 2.1.0 or later on PATH (or `VERICTO_CLI`)
and `pip install "langchain-vericto[sql]"`. No account, nothing leaves the machine.

    python examples/quickstart.py

Online, with your workspace's rules (no CLI needed):

    VERICTO_API_KEY=vtro_... VERICTO_DATABASE_ID=... python examples/quickstart.py --online
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

from langchain_vericto import VerictoSQLCheck, VerictoSQLDatabase


def main(*, online: bool) -> int:
    """Run the quickstart; return the process exit code."""
    offline = not online

    # 1. The check tool: a verdict, nothing runs.
    tool = VerictoSQLCheck(offline=offline, dialect="postgres")
    try:
        safe = json.loads(
            tool.invoke({"query": "SELECT id, email FROM users WHERE id = 42 LIMIT 1"})
        )
        print("safe SELECT  ->", safe["decision"], safe["summary"])
        risky = json.loads(tool.invoke({"query": "DELETE FROM users"}))
        print(
            "DELETE       ->",
            risky["decision"],
            risky["rule_codes"],
            "fix:",
            risky["suggested_fix"],
        )
        message = tool.invoke(
            {
                "args": {"query": "DROP TABLE users"},
                "id": "1",
                "name": tool.name,
                "type": "tool_call",
            }
        )
        print("ToolMessage  ->", message.artifact["decision"], message.artifact["rule_codes"])
    finally:
        tool.close()

    # 2. The guarded SQLDatabase: blocked statements never reach the database.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "shop.db"
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, total INTEGER)")
            conn.execute("INSERT INTO orders VALUES (1, 10), (2, 20)")
        conn.close()

        db = VerictoSQLDatabase.from_uri(f"sqlite:///{path}", offline=offline)
        try:
            print("dialect      ->", db.vericto_dialect)
            print("SELECT       ->", db.run("SELECT id, total FROM orders WHERE id = 1 LIMIT 10"))
            print("DELETE       ->", db.run("DELETE FROM orders"))
            print("rows left    ->", db.run("SELECT count(*) FROM orders LIMIT 1"))
        finally:
            db.close()
    blocked = risky["blocked"] and "VERICTO-001" in risky["rule_codes"]
    return 0 if blocked and safe["allowed"] else 1


if __name__ == "__main__":
    sys.exit(main(online="--online" in sys.argv[1:]))
