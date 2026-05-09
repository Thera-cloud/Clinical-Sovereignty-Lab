# Clinician-Authored Lexicon Overlays

This directory holds **clinician-authored** JSON lexicon overlays consumed by
sensitive-domain detector modules in `backend/app/services/`.

> **Empty by design.** This directory ships with `.gitkeep` only. Production
> lexicons must be authored by clinicians under the review process documented
> below. Do **not** seed pattern content from training data, sample text, or
> generated suggestions — every pattern that lands here is treated as an
> active clinical signal at runtime.

---

## File naming convention (Gap S — locale fallback chain)

Each detector loads its overlay using the locale-aware fallback chain defined
in plan v1.3 Gap S:

```
<requested_locale>  →  <language>  →  en-US  →  fail-safe (no overlay)
```

For example, a session with `preferred_locale = 'es-MX'` looks up:

1. `<detector>_lexicon_es-MX.json`
2. `<detector>_lexicon_es.json`
3. `<detector>_lexicon_en-US.json`
4. (no file) → detector runs on its compiled-in seed lexicon only

The detector MUST log a structured `locale_fallback_applied` event with
`{requested_locale, fallback_locale, files_missing}` whenever the requested
locale isn't directly served (per plan §Gap S audit event).

### Required filename pattern

```
<detector_module>_lexicon_<locale>.json
```

Where `<detector_module>` matches the detector's module name without `.py`
and `<locale>` is BCP-47 (`en-US`, `es`, `es-MX`, `pt-BR`, …).

| Detector module                   | Filename                                                 |
| --------------------------------- | -------------------------------------------------------- |
| `coercion_pattern_detector`       | `coercion_patterns_<locale>.json`                        |
| `dissociation_delta_detector`     | `dissociation_phrases_<locale>.json`                     |
| `linguistic_arousal_load`         | `clinical_arousal_lexicon_<locale>.json` *(Phase 2C)*    |
| `reengagement_pattern_detector`   | `reengagement_phrases_<locale>.json` *(Phase 2C)*        |
| `trafficking_disclosure_classifier` | `trafficking_phrases_<locale>.json` *(Phase 2C)*       |

> The exact filename each detector probes for is also declared in the
> detector's module docstring under "Lexicon overlay" — that string is the
> source of truth if these tables drift.

---

## Schema location

Each detector defines its own overlay schema as a Python `@dataclass` (or a
JSON-shaped dict) inside the detector module. The README does not duplicate
schemas — the dataclass *is* the contract:

| Detector module                   | Schema dataclass / loader                                                |
| --------------------------------- | ------------------------------------------------------------------------ |
| `coercion_pattern_detector`       | `_load_overlay_patterns()` + `SEED_PATTERNS` shape (CoercionPattern)     |
| `dissociation_delta_detector`     | `_load_overlay_phrases()` (`{"phrases": [str, ...]}`)                    |
| `linguistic_arousal_load`         | *Phase 2C — schema in module header*                                     |
| `reengagement_pattern_detector`   | *Phase 2C — schema in module header*                                     |
| `trafficking_disclosure_classifier` | *Phase 2C — schema in module header*                                   |

### Common rules

- **Regex strings only.** No code execution paths in lexicons. Loaders that
  see anything but a string in the regex slot must skip silently and emit
  a `lexicon_bad_entry` warning.
- **Weights in `[0.0, 1.0]`.** Out-of-range entries are clamped, not
  rejected, but the loader emits a `lexicon_weight_out_of_range` warning.
- **No raw user fixtures.** Lexicons must not embed example sentences from
  client transcripts. Use abstracted regex only.
- **`_meta` block required:** every lexicon ships with a top-level
  `"_meta": {...}` containing `version`, `authors`, `reviewed_by`,
  `review_date`, `locale`, and `notes`. Loaders ignore unknown `_meta` keys.

---

## Two-clinician review requirement (Gap D)

Per plan v1.3 Gap D ("Validator Layer 8 + lexicon review hardening"), every
lexicon file in this directory MUST satisfy the following before merge:

1. **Two independent clinician reviews.** The `_meta.reviewed_by` array
   contains at least two distinct clinician identifiers (initials + role +
   license jurisdiction acceptable; full names not required in repo).
2. **Authoring clinician is excluded from the reviewer list.** A clinician
   may not co-sign their own lexicon. PR description must name the
   authoring clinician separately.
3. **Reviewer attestation.** Each PR adding or modifying a lexicon must
   include a comment from each reviewer of the form
   `LEXICON-REVIEW-OK: <reviewer-id>: <date>`.
4. **Clinical reasoning recorded.** New patterns require a one-paragraph
   rationale in the PR description tying the pattern to a recognized
   clinical phenomenon (e.g., DSM-5 criterion, peer-reviewed framework, or
   named survivor-research source). Internal "vibes" or pattern-matching
   from non-clinical staff is not acceptable evidence.
5. **No content from automated suggestions.** AI-generated lexicon content
   is forbidden. Detectors are clinical instruments; their lexicons are
   clinical documents.

These checks are enforced at human review. The CI version-bump enforcement
below catches the *mechanical* change-without-version-bump failure; the
human review catches the *clinical* unsafe-content failure.

---

## CI version-bump enforcement (per `specialized_resources.py` pattern)

`backend/app/services/specialized_resources.py` ships with a SHA256 content
hash (`REGISTRY_CONTENT_HASH`) and a startup assertion
(`assert_version_aligned()`) that fails import when the resource data
changes without `REGISTRY_VERSION` also being bumped. The companion test
`backend/tests/test_specialized_resources_version_lock.py` enforces the
contract in CI.

Lexicon files in this directory follow the **same pattern** but at the
detector level:

- Each detector module declares `REGISTRY_VERSION` and a content-hash
  computation that includes (a) its compiled seed lexicon and (b) every
  lexicon file it loads from this directory.
- The detector's `_auditor_self_check()` verifies the version string is
  aligned with the hash. Mismatch → auditor reports unhealthy → Trust
  Enforcer flags as `LEXICON_DRIFT`.
- Each detector ships with a corresponding test under
  `backend/tests/test_<detector>_version_lock.py` that fails CI when:
  - a lexicon file in this directory changes content
  - AND the detector's `REGISTRY_VERSION` string is not bumped
  - AND the recomputed `REGISTRY_CONTENT_HASH` doesn't match the stored one

### Registering a new lexicon for CI enforcement

When a new lexicon is added (e.g., `coercion_patterns_es-MX.json`), a PR
must update the matching detector's content-hash function to include the
new file. The exact registration point is named in each detector's module
header under `REGISTRY_VERSION`. Example for the coercion detector:

```python
# In backend/app/services/coercion_pattern_detector.py
LEXICON_FILES_TO_HASH = (
    "coercion_patterns_en-US.json",
    "coercion_patterns_es.json",
    # add new locale files here; bump REGISTRY_VERSION in same PR
)
```

The matching CI test imports `LEXICON_FILES_TO_HASH`, recomputes the hash
from on-disk contents, and asserts it equals the detector's stored
`REGISTRY_CONTENT_HASH`. Any change to a referenced lexicon file without a
synchronized version bump fails the test.

---

## What this directory is NOT

- **Not a configuration store.** Runtime config lives in env vars and DB.
- **Not a translation memory.** Translated lexicons require independent
  clinician review per locale (Gap S explicitly rules out machine
  translation).
- **Not where coach-portal user data goes.** Per-user lexicon
  customization (codewords, trigger phrases) lives in
  `user_safety_codewords` and `user_trigger_dates` tables.
- **Not for experimental tuning.** A/B-tested or experimental lexicons go
  under `backend/tests/fixtures/` and are loaded only by the test suite,
  never by production paths.

---

## Phase 5 portal integration

The clinician-facing portal (Phase 5,
`sensitive_clinical_profile_screen.dart` + `sensitive_profile_api.py`) will
expose a "Lexicon Overlay" view that:

1. Lists files present in this directory with their `_meta.version`,
   `_meta.locale`, `_meta.reviewed_by`, and last-modified time.
2. Lets clinicians submit *proposed* additions or removals via a queue
   (writes to a staging area, NOT this directory).
3. Routes proposals through the two-clinician review process before any
   PR is opened.

This directory remains git-tracked and PR-gated; the portal does not write
here directly. The portal is the staging surface; PR review is the gate.
