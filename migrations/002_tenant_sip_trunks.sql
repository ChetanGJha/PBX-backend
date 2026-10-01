-- Migration: 002_tenant_sip_trunks.sql
-- Allow SIP trunks to be assigned to zero, one, or multiple tenants

CREATE TABLE IF NOT EXISTS public.tenant_sip_trunks (
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    trunk_id uuid NOT NULL REFERENCES public.sip_trunks(id) ON DELETE CASCADE,
    created_at timestamp with time zone DEFAULT now(),
    PRIMARY KEY (tenant_id, trunk_id)
);

CREATE INDEX IF NOT EXISTS idx_tenant_sip_trunks_tenant ON public.tenant_sip_trunks (tenant_id);
CREATE INDEX IF NOT EXISTS idx_tenant_sip_trunks_trunk ON public.tenant_sip_trunks (trunk_id);

-- Migrate any single tenant assignments to junction table
INSERT INTO public.tenant_sip_trunks (tenant_id, trunk_id)
SELECT tenant_id, id FROM public.sip_trunks WHERE tenant_id IS NOT NULL
ON CONFLICT DO NOTHING;
