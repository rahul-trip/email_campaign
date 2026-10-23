-- Local rehearsal only (deploy/compose.local.yml): the login roles an operator creates by hand
-- in Supabase (docs/DEPLOY.md, section 1.2). Migration 0009 gives them their grants.
CREATE ROLE outbound_app LOGIN NOBYPASSRLS PASSWORD 'outbound';
CREATE ROLE outbound_platform LOGIN NOBYPASSRLS PASSWORD 'outbound';
