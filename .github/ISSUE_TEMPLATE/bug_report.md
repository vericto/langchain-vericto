---
name: Bug report
about: Something langchain-vericto gets wrong with LangChain, a SQLDatabase or the verdict
title: "[BUG] "
labels: bug
---

<!--
Security vulnerabilities: do not open an issue. Report them privately, see
https://github.com/vericto/langchain-vericto/security/policy

Rules and SQL parsing live in vericto-engine. If a specific statement got the wrong
verdict, you can report it here or in vericto-engine; we move issues to the right
repository.
-->

**What happened**
A clear description of what went wrong, and what you expected instead.

**Component**
- [ ] `VerictoSQLCheck`
- [ ] `VerictoSQLDatabase` (with `SQLDatabaseToolkit`, an agent, a chain)

**Mode**
- [ ] offline (Vericto CLI version: `vericto --version`)
- [ ] online

**Dialect**
- [ ] postgres
- [ ] mysql
- [ ] oracle
- [ ] mssql
- [ ] snowflake
- [ ] sqlite

**Environment**
- `python -c "import langchain_vericto, vericto; print(langchain_vericto.__version__, vericto.__version__)"`:
- `langchain-core` / `langchain-community` / `langchain` versions:
- Python version and OS:
- `fail_mode`:

**Steps to reproduce**
A minimal script, with the API key and connection details removed.
```python
from langchain_vericto import VerictoSQLCheck
```

**SQL statement (if a query was blocked or allowed when it should not have been)**
```sql
-- the exact statement
```

**Traceback or logs**
Output of the `vericto` logger and the full traceback. Remove anything sensitive.
```
paste relevant output here
```
