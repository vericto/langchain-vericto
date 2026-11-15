#!/bin/bash
# SPDX-FileCopyrightText: 2026 Vericto S.A.S.
# SPDX-License-Identifier: Apache-2.0
#
# The package itself imports langchain_core (and langchain_community for the `sql`
# extra), never the `langchain` or `langchain_experimental` packages. Tests may
# use langchain.agents.
set -eu

errors=0
git --no-pager grep --untracked -n -E "^\s*(from|import) langchain(\.| |$)" -- langchain_vericto && errors=$((errors+1))
git --no-pager grep --untracked -n -E "^\s*(from|import) langchain_experimental" -- . && errors=$((errors+1))

exit $(( errors > 0 ? 1 : 0 ))
