# D.I.D. systems lexicon (`did_systems/`)

Scaffold terminology sourced from [Multiplied By One — D.I.D. terminology](https://multipliedbyone.org/dissociative-identity-disorder-terminology/) with cross-references to [did-research.org](https://did-research.org/). **`lexicon_loader.py` skips any file with `status: scaffolded_unreviewed`** until clinically reviewed.

## Activation (project owner)

1. Clinically review each YAML (`system_terminology`, `subsystem_terminology`, `affectionate_framing`, `crystal_seed`).
2. Adjust `detector_patterns` weights and notes; confirm verbatim patterns cite authoritative URLs (`citation_link` where applicable).
3. Change **`status: scaffolded_unreviewed`** → **`status: clinically_active`** on approved files.
4. Restart backend or call `lexicon_loader.invalidate_cache()` after edits.

Once active, `load_active_lexicons(["did_systems"], …)` loads YAML. **`collect_did_lexicon_layer1_cues(client_message)`** / `load_did_systems_layer1_text_cues(client_message=…)` only emit cues when **`detector_patterns`** match normalized client text (then merge matched-file **`response_seeds`**). **Crystal Factory Layer 1** merges those cues with per-client rows from `nate_intelligence_crystals` via `_load_lexicon_crystals(..., client_message=…)` in `sensitive_clinical_bridge.py`. Audit payload includes `did_lexicon_detector_matches` when the bridge runs with `v1_4_crystal_factory_enabled`.

**Full activation:** `v1_4_crystal_factory_enabled` is in `_V1_4_FEATURE_FLAG_NAMES` and thus participates in `_any_sensitive_feature_active()` alongside the 16 gap flags via enrollment/gap resolution (`sensitive_clinical_bridge.py`).

## Loader verification (local)

```bash
cd backend && PYTHONPATH=. python3 -c "
from app.services.lexicon_loader import load_active_lexicons, load_did_systems_layer1_text_cues
assert load_active_lexicons(['did_systems'], categories={'system_terminology'})
assert len(load_did_systems_layer1_text_cues()) == 0  # pattern-gated: no message
assert load_did_systems_layer1_text_cues(client_message='fronting')
print('did_systems active + pattern gate OK')
"
```

After activation: expect non-empty merged dict when `categories` matches stems.
