-- Creates a separate test database on the same Postgres instance.
-- Mounted into /docker-entrypoint-initdb.d/ so it runs automatically
-- on first container creation.

CREATE DATABASE orchestrator_test
    OWNER orchestrator
    ENCODING 'UTF8';
