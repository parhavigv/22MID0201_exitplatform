-- ============================================================================
-- Migration 0010 — IT and Finance become roles people can sign in as
--
-- `task_owner_role` has always been
--   ('employee','manager','hr','it','finance','admin')
-- so every case already carries IT and Finance work: "Revoke system access",
-- "Issue no-dues certificate", "Return laptop and IT-issued hardware".
--
-- But `app_role` stopped at ('employee','manager','hr'), so there was nobody to
-- do that work. `routers/inbox.py` says as much: "IT, Finance and Admin have no
-- dashboard in v1, so HR covers them." HR has been signing off IT clearances.
--
-- This migration only widens the enum. The policies that use the new values
-- live in 0011, because Postgres refuses to use an enum value in the same
-- transaction that adds it.
--
-- 'admin' is deliberately not added. Admin owns two asset-return tasks that
-- HR already handles, and an extra login nobody uses is a liability, not a
-- feature. Add it the day somebody needs to sign in as Admin.
-- ============================================================================

alter type app_role add value if not exists 'it';
alter type app_role add value if not exists 'finance';
