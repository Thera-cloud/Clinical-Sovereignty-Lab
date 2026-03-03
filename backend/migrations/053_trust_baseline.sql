-- Trust Baseline & Governance Tables
-- Used by TrustEnforcer to track what "trusted" means and gate changes through admin approval

CREATE TABLE IF NOT EXISTS trust_baseline (
    id SERIAL PRIMARY KEY,
    parameter_key TEXT UNIQUE NOT NULL,
    parameter_value JSONB NOT NULL,
    description TEXT,
    approved_by TEXT NOT NULL DEFAULT 'DrNevedal1',
    approved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS trust_baseline_proposals (
    id SERIAL PRIMARY KEY,
    parameter_key TEXT NOT NULL,
    current_value JSONB,
    proposed_value JSONB NOT NULL,
    reason TEXT,
    proposed_by TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed baseline parameters for all 12 auditors
INSERT INTO trust_baseline (parameter_key, parameter_value, description, approved_by) VALUES
('l2_validation_rule', '{"type":"structural","rule":"non_null_and_has_keys","description":"L2 passes if response is non-null and (for dicts) has at least one key. Lists, primitives always pass."}', 'Defines what L2 structural validation considers a valid payload', 'DrNevedal1'),
('skyeye_endpoint_count', '{"expected":56,"auditor":"SkyEyeTabAuditor","activity_type":"skyeye_tab_audit_sent"}', 'Expected endpoint count for SkyEye dashboard auditor', 'DrNevedal1'),
('command_endpoint_count', '{"expected":25,"auditor":"SovereignCommandAuditor","activity_type":"command_tab_audit_sent"}', 'Expected endpoint count for Sovereign Command auditor', 'DrNevedal1'),
('eye_endpoint_count', '{"expected":21,"auditor":"TheEyeAuditor","activity_type":"eye_tab_audit_sent"}', 'Expected endpoint count for The Eye auditor', 'DrNevedal1'),
('client_app_endpoint_count', '{"expected":15,"auditor":"ClientAppAuditor","activity_type":"client_app_audit_sent"}', 'Expected endpoint count for Client App auditor', 'DrNevedal1'),
('login_test_accounts', '{"expected":2,"auditor":"LoginAuditor","activity_type":"login_audit_sent","accounts":["audit_client","audit_coach"]}', 'Expected login test count and account list', 'DrNevedal1'),
('coach_dojo_endpoint_count', '{"expected":28,"auditor":"CoachDojoAuditor","activity_type":"coach_dojo_audit_sent"}', 'Expected endpoint count for Coach & DOJO auditor', 'DrNevedal1'),
('billing_endpoint_count', '{"expected":24,"auditor":"BillingPipelineAuditor","activity_type":"billing_audit_sent"}', 'Expected endpoint count for Billing Pipeline auditor', 'DrNevedal1'),
('defense_subsystem_count', '{"expected":8,"auditor":"DefenseHealthAuditor","activity_type":"defense_audit_sent"}', 'Expected subsystem count for Defense Health auditor', 'DrNevedal1'),
('ai_pipeline_check_count', '{"expected":6,"auditor":"AIPipelineAuditor","activity_type":"ai_pipeline_audit_sent"}', 'Expected check count for AI Pipeline auditor', 'DrNevedal1'),
('ws_flow_test_count', '{"expected":10,"auditor":"WebSocketFlowAuditor","activity_type":"ws_flow_audit_sent"}', 'Expected WebSocket flow test count', 'DrNevedal1'),
('tier_gate_test_count', '{"expected":12,"auditor":"TierGatingAuditor","activity_type":"tier_gating_audit_sent"}', 'Expected tier gate test count', 'DrNevedal1'),
('nevedal_lab_endpoint_count', '{"expected":20,"auditor":"NevedalLabAuditor","activity_type":"nevedal_lab_audit_sent"}', 'Expected endpoint count for Nevedal Research Lab auditor (6 sub-tabs)', 'DrNevedal1'),
('trust_threshold', '{"green_pct":100,"yellow_below":100,"red_on_failed":true}', 'Overall trust scoring thresholds', 'DrNevedal1')
ON CONFLICT (parameter_key) DO NOTHING;
