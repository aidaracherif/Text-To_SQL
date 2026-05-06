-- =============================================================================
-- Migration 002 — Création de la table users
-- =============================================================================
-- Stocke les comptes utilisateurs avec mots de passe hashés (bcrypt).
-- NE JAMAIS stocker de mot de passe en clair.
--
-- Application :
--   psql -U <user> -d <db> -f 002_users.sql
-- =============================================================================

CREATE TABLE IF NOT EXISTS users (
    -- Identifiant
    id              BIGSERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Authentification
    username        TEXT        NOT NULL UNIQUE,    -- nom d'utilisateur unique
    email           TEXT        UNIQUE,             -- optionnel, peut être NULL
    password_hash   TEXT        NOT NULL,           -- bcrypt hash, JAMAIS en clair

    -- Métadonnées
    full_name       TEXT,                           -- nom complet (affichage)
    role            TEXT        NOT NULL DEFAULT 'user'
                                CHECK (role IN ('user', 'admin')),
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    last_login_at   TIMESTAMPTZ                     -- dernière connexion
);

-- =============================================================================
-- Index pour les requêtes fréquentes (login, lookup)
-- =============================================================================

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users (LOWER(username));
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email    ON users (LOWER(email)) WHERE email IS NOT NULL;
CREATE INDEX        IF NOT EXISTS idx_users_role     ON users (role);

-- =============================================================================
-- Trigger : mettre à jour updated_at automatiquement
-- =============================================================================

CREATE OR REPLACE FUNCTION users_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS users_updated_at_trigger ON users;
CREATE TRIGGER users_updated_at_trigger
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION users_set_updated_at();

COMMENT ON TABLE  users               IS 'Comptes utilisateurs de l''application Text-to-SQL';
COMMENT ON COLUMN users.password_hash IS 'Hash bcrypt du mot de passe — jamais le mot de passe en clair';
COMMENT ON COLUMN users.role          IS 'user = peut requêter, admin = peut gérer comptes + voir audit complet';
