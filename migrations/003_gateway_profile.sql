-- Add profile column to gateways table to support multiple SIP profiles (external for ITS SBC, external-crossconnect for Fixed Line SBC)
ALTER TABLE IF EXISTS public.gateways 
ADD COLUMN IF NOT EXISTS profile character varying(50) DEFAULT 'external';
