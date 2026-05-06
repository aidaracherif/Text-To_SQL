-- =============================================================================
-- Migration 001 — Création de la table audit_log
-- =============================================================================
-- Table d'audit complète pour toutes les requêtes Text-to-SQL.
-- Stocke : question, SQL généré, statut, durée, utilisateur, IP, résultats
-- tronqués, erreur, contexte RAG, prompt complet.
--
-- Application :
--   psql -U <user> -d <db> -f 001_audit_log.sql
-- =============================================================================

CREATE TABLE IF NOT EXISTS audit_log (
    -- Identifiant
    id              BIGSERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Niveau MINIMAL : question, SQL, statut, durée
    question        TEXT        NOT NULL,
    sql             TEXT        NOT NULL DEFAULT '',
    success         BOOLEAN     NOT NULL,
    row_count       INTEGER     NOT NULL DEFAULT 0,
    duration_ms     REAL        NOT NULL DEFAULT 0.0,

    -- Niveau COMPLET : user, IP, résultats tronqués, erreur
    user_name       TEXT,                    -- NULL si pas d'auth pour l'instant
    ip_address      INET,                    -- type natif PostgreSQL pour les IPs
    user_agent      TEXT,                    -- pour debug navigateur/client
    columns_json    JSONB,                   -- noms des colonnes retournées
    rows_preview    JSONB,                   -- 10 premières lignes max (tronqué)
    error_message   TEXT,                    -- message d'erreur friendly
    error_raw       TEXT,                    -- erreur brute (debug)
    warning         TEXT,                    -- ex. "hors périmètre"

    -- Niveau AUDIT LOURD : contexte RAG, prompt complet
    rag_context     JSONB,                   -- {sql_examples, knowledge, schema_chunks}
    rag_route       TEXT,                    -- "direct" | "sql_only" | "knowledge" | "schema" | "full"
    system_prompt   TEXT,                    -- prompt système complet envoyé au LLM
    user_prompt     TEXT,                    -- prompt user (RAG ou question brute)
    llm_model       TEXT,                    -- ex. "qwen2.5-coder"
    llm_raw_output  TEXT                     -- réponse brute du LLM (avant extract SQL)
);

-- =============================================================================
-- Index pour les requêtes fréquentes du dashboard
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_audit_log_created_at  ON audit_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_success     ON audit_log (success);
CREATE INDEX IF NOT EXISTS idx_audit_log_user_name   ON audit_log (user_name);
CREATE INDEX IF NOT EXISTS idx_audit_log_rag_route   ON audit_log (rag_route);

-- Index trigramme pour rechercher dans les questions (utile dashboard)
-- Nécessite l'extension pg_trgm — décommentez si dispo :
-- CREATE EXTENSION IF NOT EXISTS pg_trgm;
-- CREATE INDEX IF NOT EXISTS idx_audit_log_question_trgm
--     ON audit_log USING gin (question gin_trgm_ops);

COMMENT ON TABLE  audit_log              IS 'Journal d''audit complet des requêtes Text-to-SQL';
COMMENT ON COLUMN audit_log.rows_preview IS 'Limité aux 10 premières lignes pour ne pas exploser la taille';
COMMENT ON COLUMN audit_log.rag_context  IS 'Contexte RAG complet : sql_examples, knowledge, schema_chunks';