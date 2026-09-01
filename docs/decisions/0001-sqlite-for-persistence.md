# ADR 0001 — SQLite for persistence (Postgres-ready)

**Status:** accepted

## Context
The audit ledger must persist — the whole value of an audit trail is that it
survives a restart. But this is a hackathon build that a stranger should be
able to clone and run in one command, with no database to provision.

## Decision
Use SQLite via SQLAlchemy 2.0. Access goes through a repository, and the engine
is created from `DATABASE_URL`, so switching to Postgres is a one-line env
change with no code changes.

## Consequences
- Zero setup: the DB is a file, created on startup.
- The ORM keeps us honest about swappability (no SQLite-only SQL).
- For real scale you'd move to Postgres; the code already supports it.
