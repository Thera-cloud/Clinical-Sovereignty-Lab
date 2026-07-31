-- LN7 G1 epoch flag (non-weld). Flip after verified ci_pack shadow_outcome.
-- Does NOT enable AUTO_PROMOTE or DUAL_COO_MECHANICAL_PROMOTE (G2 weld keys).
-- QUANTUM-CRYSTAL-ARCH
-- Additive only.

INSERT INTO ln7_feature_flags (key, enabled, notes) VALUES
    (
        'LN7_G1_OPEN',
        FALSE,
        'G1 transition: shadow oracle live; CEO activate still authoritative until G2 weld flip'
    )
ON CONFLICT (key) DO NOTHING;
