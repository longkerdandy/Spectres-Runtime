#!/bin/bash
set -e

# Create development and test databases.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE spectres_runtime;
    CREATE DATABASE spectres_runtime_test;
EOSQL

# Install pgvector extension in both databases.
for db in spectres_runtime spectres_runtime_test; do
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" <<-EOSQL
        CREATE EXTENSION IF NOT EXISTS vector;
EOSQL
done
