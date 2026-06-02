-- pgvector enablement (explicit fallback).
--
-- Runs once, automatically, on the database's FIRST boot (empty volume) because
-- Postgres executes everything in /docker-entrypoint-initdb.d at init time. This
-- guarantees the `vector` extension exists the moment the DB is reachable, so any
-- client (psql, the ingest job, Agno) can use it without depending on application
-- start-up order. Idempotent: Agno's PgVector table creation also issues this.
CREATE EXTENSION IF NOT EXISTS vector;
