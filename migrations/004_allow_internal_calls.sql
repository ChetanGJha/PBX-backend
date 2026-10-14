-- 004_allow_internal_calls.sql
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS allow_internal_calls BOOLEAN DEFAULT true;
