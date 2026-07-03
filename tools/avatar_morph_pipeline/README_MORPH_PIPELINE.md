# Little Nate — Morph Expression Pipeline

## Status: BLOCKED on asset topology (checked 2026-07-03)

Ran `merge_expressions.py --check-only` against the real production exports
(`little_nate_v_1_3/mininate *.glb`). Result: **NOT vertex-compatible**.
See `COMPATIBILITY_REPORT_2026-07-03.txt` in this folder for the raw output.

```
primitives: 3   total vertices: 340,067   (base: mininate neutral)
✗ empathetic: geometry_0[0] verts 86115≠86121
✗ sad:        geometry_0[0] verts 86115≠86076
✗ proud:      geometry_0[0] verts 86115≠86076
✗ curious:    geometry_0[0] verts 86115≠86121
✗ calming:    geometry_0[0] verts 86115≠86121
✗ mad:        geometry_0[0] verts 86115≠86076
```

Every expression file was exported with a different vertex count than
neutral (86,115). They fall into two consistent groups (86,121 and 86,076),
which suggests two different export/decimation passes rather than the same
rigged base mesh posed 7 ways. True morph-target blending needs identical
vertex **and index** buffers across all 7 files — only the position deltas
should differ. Until the 3D asset owner re-exports with shared topology,
this merge cannot run.

This is on top of (not instead of) the separate finding that only 3 of the
7 exports are visually unique to begin with — `sad`/`proud`/`mad` are
byte-identical, and `empathetic`/`curious`/`calming` are byte-identical.
See `docs/AVATAR_EXPRESSION_DESIGN_BRIEF.md` for the full asset-owner brief.

**Current mitigation deployed**: `GlbAvatarWidget` (`mobile/lib/avatar.dart`)
now cross-fades between expression GLBs (450ms ease) instead of hard-cutting
to a loading spinner on every change. This is the README's own fallback path
("use the Spline seven-state scene with crossfade transitions") adapted to
the model-viewer-based renderer already wired into Avatar Mode, since the
Spline iframe path (`spline_iframe_web.dart`) is present in the repo but not
currently used by any screen.

## What this pipeline does (once assets are fixed)
Merges the seven `mininate *.glb` expression exports into ONE GLB where each
expression is a morph target on the neutral model, then renders it with
smooth tweened transitions (450ms ease) via a drop-in replacement for the
Spline iframe. Same postMessage contract (`spline_ready` / `setExpression`),
so `spline_iframe_web.dart` needs zero changes — only the iframe URL.

## Files
- merge_expressions.py — topology check + merge
- expression_viewer.html — three.js renderer + test sliders + contract
- COMPATIBILITY_REPORT_2026-07-03.txt — real result against production assets

## Re-run once new exports arrive
    pip install pygltflib numpy
    python3 merge_expressions.py \
      "mininate neutral.glb" "mininate empathetic.glb" "mininate sad.glb" \
      "mininate proud.glb" "mininate curious.glb" "mininate calming.glb" \
      "mininate mad.glb" -o little_nate_morphs.glb

NEUTRAL MUST BE FIRST — it becomes the base; the rest become targets.

Outcome A — "COMPATIBLE": you get little_nate_morphs.glb. Put it next to
expression_viewer.html, serve the folder (python3 -m http.server), open the
viewer, drag sliders / click expression buttons. If it looks right, deploy
both files to /spline-morph/ and point the Flutter iframe URL there (either
re-wire `buildSplineAvatarIframe()` from `spline_iframe_web.dart` into
Avatar Mode, or keep `GlbAvatarWidget` and swap its renderer to the
morph viewer — either is a small, isolated change once assets pass Phase 1).

Outcome B — "NOT vertex-compatible" (current state): the generator
re-meshed each export. Morphing is impossible on these files; the
crossfade mitigation above is the smoothest we can do without new assets.

## Wiring notes (for when Outcome A is reached)
- Viewer maps client wire name `frustrated` → GLB target `mad`, and
  synonyms (warm/validating→empathetic, encouraging→proud,
  attentive/thoughtful→neutral) so all 12 client expressions resolve.
- Blending is supported: set two influences manually for mixed states
  (e.g. 0.6 empathetic + 0.3 sad) — future server enhancement.
- Morphs carry POSITION deltas only (no normals). If lighting looks flat
  at full deformation on the real model, say so — normals deltas can be
  added to the pipeline.
- Size: expect the merged file ≈ neutral + small per-expression deltas,
  vs 7 × 13.5 MB today. Run gltf-transform optimize on the OUTPUT for
  further texture compression if needed.
