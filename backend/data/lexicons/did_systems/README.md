# D.I.D. systems lexicon (`did_systems/`)

Scaffold terminology sourced from [Multiplied By One — D.I.D. terminology](https://multipliedbyone.org/dissociative-identity-disorder-terminology/) with cross-references to [did-research.org](https://did-research.org/). **All YAML files ship as `status: scaffolded_unreviewed`; `lexicon_loader.py` skips them until clinically reviewed.**

## Activation (project owner)

1. Clinically review each YAML (`system_terminology`, `subsystem_terminology`, `affectionate_framing`, `crystal_seed`).
2. Adjust `detector_patterns` weights and notes; confirm verbatim patterns cite authoritative URLs (`citation_link` where applicable).
3. Change **`status: scaffolded_unreviewed`** → **`status: clinically_active`** on approved files.
4. Restart backend or call `lexicon_loader.invalidate_cache()` after edits.

Once active, `load_active_lexicons(["did_systems"], …)` and `load_did_systems_layer1_text_cues()` load patterns at inference time. **Crystal Factory Layer 1** merges YAML framings with per-client rows from `nate_intelligence_crystals` (see `_load_lexicon_crystals` in `sensitive_clinical_bridge.py`). Client-specific system names and framings continue to grow through crystallization into Layer 1.

## Loader verification (local)

```bash
cd backend && PYTHONPATH=. python3 -c "
from app.services.lexicon_loader import load_active_lexicons, load_did_systems_layer1_text_cues
assert len(load_active_lexicons(['did_systems'], categories={'system_terminology'})) == 0
assert len(load_did_systems_layer1_text_cues()) == 0
print('scaffold filter OK — zero until clinically_active')
"
```

After activation: expect non-empty merged dict when `categories` matches stems.
