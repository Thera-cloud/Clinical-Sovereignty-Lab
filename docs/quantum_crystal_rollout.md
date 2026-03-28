# Quantum Crystal Rollout and Rollback

## Feature Flags

- `ENABLE_QUANTUM_CRYSTAL_ORCHESTRATOR`
- `ENABLE_VOICE_TRANSCRIPT_CRYSTALLIZATION`
- `ENABLE_TIME_CRYSTAL_FORGE`

All three default to `false` and are evaluated at runtime.

## Progressive Rollout

1. **Admin cohort**
   - Enable `ENABLE_QUANTUM_CRYSTAL_ORCHESTRATOR=true`
   - Validate recall path logging in `crystal_recall_log`
2. **Coach cohort**
   - Keep orchestrator enabled
   - Enable `ENABLE_VOICE_TRANSCRIPT_CRYSTALLIZATION=true` for selected coach calls
3. **Selected clients**
   - Expand voice crystallization to selected client sessions
4. **Full rollout**
   - Enable `ENABLE_TIME_CRYSTAL_FORGE=true`
   - Verify weekly forge events and outreach candidate generation

## Rollback Path

If regressions are observed:

1. Disable `ENABLE_TIME_CRYSTAL_FORGE`
2. Disable `ENABLE_VOICE_TRANSCRIPT_CRYSTALLIZATION`
3. Disable `ENABLE_QUANTUM_CRYSTAL_ORCHESTRATOR`
4. Recreate containers so env updates apply (`docker compose -f docker-compose.prod.yml up -d`)

This reverts behavior to legacy recall and voice paths while retaining migration data.

## Validation Checklist

- `crystal_recall_log` receives rows from inference, bridge, quantum field, and SkyEye paths
- `conversation_history` receives voice transcript rows when voice crystallization is enabled
- `voice_session_biometrics` contains EC snapshots on completed calls
- `coherence_time_crystals` rows increase after forge windows
- confidence decrement attempts are blocked by `no_confidence_decay` trigger
