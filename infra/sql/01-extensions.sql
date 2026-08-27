-- Extensions and databases created before the application ever connects.
--
-- pgvector backs the policy retrieval index. pgcrypto gives us digest() so the
-- audit chain can be verified in SQL as well as in Python - a useful property
-- when an auditor wants to check the chain without trusting our code.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Separate database for the tracing stack so its schema migrations never touch
-- application data.
SELECT 'CREATE DATABASE langfuse OWNER backstop'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'langfuse')\gexec

-- Schemas, one per plane. Keeps grants meaningful later: the API role will not
-- need write access to `audit`, only append via a function.
CREATE SCHEMA IF NOT EXISTS domain;      -- orders, customers, shipments, products
CREATE SCHEMA IF NOT EXISTS agent;       -- langgraph checkpoints, deliberations
CREATE SCHEMA IF NOT EXISTS knowledge;   -- policy documents and embeddings
CREATE SCHEMA IF NOT EXISTS audit;       -- hash-chained decision record
