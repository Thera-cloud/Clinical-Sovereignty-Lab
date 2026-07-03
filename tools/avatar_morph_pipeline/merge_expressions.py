#!/usr/bin/env python3
"""
merge_expressions.py — Little Nate expression merger
=====================================================
Merges N expression GLBs (same character, same topology, different poses)
into ONE GLB where every expression is a morph target (blendshape) on the
neutral model. Result: smooth 0..1 interpolation between expressions in
any GLTF renderer (three.js morphTargetInfluences), tiny file size vs
shipping N full models, and the ability to BLEND expressions.

Usage:
    python3 merge_expressions.py neutral.glb sad.glb proud.glb ... -o little_nate_morphs.glb

Phase 1 (always runs): topology compatibility report.
Phase 2 (only if compatible): writes merged GLB.

Requires: pip install pygltflib numpy
"""
import argparse
import struct
import sys
from pathlib import Path

import numpy as np
from pygltflib import (
    GLTF2, Accessor, BufferView, Attributes, FLOAT, ARRAY_BUFFER,
)

EPS = 1e-6  # positions closer than this are considered unmoved


# --------------------------------------------------------------------------
# Accessor readers
# --------------------------------------------------------------------------
COMPONENT_DTYPES = {5120: np.int8, 5121: np.uint8, 5122: np.int16,
                    5123: np.uint16, 5125: np.uint32, 5126: np.float32}
TYPE_SIZES = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4,
              "MAT2": 4, "MAT3": 9, "MAT4": 16}


def read_accessor(gltf: GLTF2, blob: bytes, accessor_idx: int) -> np.ndarray:
    acc = gltf.accessors[accessor_idx]
    bv = gltf.bufferViews[acc.bufferView]
    dtype = COMPONENT_DTYPES[acc.componentType]
    n_comp = TYPE_SIZES[acc.type]
    item = np.dtype(dtype).itemsize * n_comp
    stride = bv.byteStride or item
    start = (bv.byteOffset or 0) + (acc.byteOffset or 0)
    if stride == item:
        raw = blob[start:start + acc.count * item]
        arr = np.frombuffer(raw, dtype=dtype, count=acc.count * n_comp)
    else:  # interleaved
        out = np.empty(acc.count * n_comp, dtype=dtype)
        for i in range(acc.count):
            off = start + i * stride
            out[i * n_comp:(i + 1) * n_comp] = np.frombuffer(
                blob[off:off + item], dtype=dtype, count=n_comp)
        arr = out
    return arr.reshape(acc.count, n_comp).astype(np.float32) \
        if dtype == np.float32 else arr.reshape(acc.count, n_comp)


def primitive_signature(gltf: GLTF2, blob: bytes):
    """Per-primitive (mesh_name, vertex_count, index_hash) for topology compare."""
    sigs = []
    for mesh in gltf.meshes:
        for pi, prim in enumerate(mesh.primitives):
            vcount = gltf.accessors[prim.attributes.POSITION].count
            if prim.indices is not None:
                idx = read_accessor(gltf, blob, prim.indices)
                ihash = hash(idx.astype(np.uint32).tobytes())
                icount = idx.shape[0]
            else:
                ihash, icount = None, 0
            sigs.append({
                "mesh": mesh.name or f"mesh{gltf.meshes.index(mesh)}",
                "prim": pi, "vertices": int(vcount),
                "indices": int(icount), "index_hash": ihash,
            })
    return sigs


# --------------------------------------------------------------------------
# Phase 1: compatibility check
# --------------------------------------------------------------------------
def check_compatibility(files):
    loaded = []
    for f in files:
        g = GLTF2().load(str(f))
        blob = g.binary_blob()
        loaded.append((Path(f).stem, g, blob, primitive_signature(g, blob)))

    base_name, base_g, base_blob, base_sig = loaded[0]
    print(f"\n=== TOPOLOGY REPORT (base: {base_name}) ===")
    print(f"  primitives: {len(base_sig)}  "
          f"total vertices: {sum(s['vertices'] for s in base_sig):,}")

    all_ok = True
    for name, g, blob, sig in loaded[1:]:
        if len(sig) != len(base_sig):
            print(f"  ✗ {name}: {len(sig)} primitives vs {len(base_sig)} — INCOMPATIBLE")
            all_ok = False
            continue
        problems = []
        for a, b in zip(base_sig, sig):
            if a["vertices"] != b["vertices"]:
                problems.append(f"{a['mesh']}[{a['prim']}] verts {a['vertices']}≠{b['vertices']}")
            elif a["index_hash"] != b["index_hash"]:
                problems.append(f"{a['mesh']}[{a['prim']}] index buffer differs")
        if problems:
            print(f"  ✗ {name}: " + "; ".join(problems[:4]))
            all_ok = False
        else:
            print(f"  ✓ {name}: topology matches")
    return all_ok, loaded


# --------------------------------------------------------------------------
# Phase 2: bake morph targets into the base GLB
# --------------------------------------------------------------------------
def align4(b: bytearray):
    while len(b) % 4:
        b.append(0)


def merge(loaded, out_path):
    base_name, g, blob, _ = loaded[0]
    new_blob = bytearray(blob)
    target_names = [name for name, *_ in loaded[1:]]

    # Pre-read base positions per (mesh, prim)
    for m_i, mesh in enumerate(g.meshes):
        for p_i, prim in enumerate(mesh.primitives):
            base_pos = read_accessor(g, blob, prim.attributes.POSITION)
            prim.targets = prim.targets or []
            for name, eg, eblob, _ in loaded[1:]:
                epos = read_accessor(
                    eg, eblob,
                    eg.meshes[m_i].primitives[p_i].attributes.POSITION)
                delta = (epos - base_pos).astype(np.float32)
                if np.abs(delta).max() < EPS:
                    delta[:] = 0.0  # unmoved primitive: zero target keeps counts aligned
                align4(new_blob)
                offset = len(new_blob)
                new_blob += delta.tobytes()
                g.bufferViews.append(BufferView(
                    buffer=0, byteOffset=offset,
                    byteLength=delta.nbytes, target=ARRAY_BUFFER))
                g.accessors.append(Accessor(
                    bufferView=len(g.bufferViews) - 1, componentType=FLOAT,
                    count=delta.shape[0], type="VEC3",
                    min=delta.min(axis=0).tolist(),
                    max=delta.max(axis=0).tolist()))
                prim.targets.append(Attributes(POSITION=len(g.accessors) - 1))
        mesh.weights = [0.0] * len(target_names)
        mesh.extras = mesh.extras or {}
        mesh.extras["targetNames"] = target_names

    g.buffers[0].byteLength = len(new_blob)
    g.set_binary_blob(bytes(new_blob))
    g.save(str(out_path))

    size_in = sum(Path(f).stat().st_size for f in FILES)
    size_out = Path(out_path).stat().st_size
    print(f"\n=== MERGED ===")
    print(f"  targets: {target_names}")
    print(f"  input total: {size_in/1e6:.1f} MB ({len(FILES)} files)")
    print(f"  output:      {size_out/1e6:.1f} MB (1 file)")
    print(f"  → {out_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+",
                    help="neutral.glb FIRST, then expression GLBs")
    ap.add_argument("-o", "--out", default="little_nate_morphs.glb")
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()
    FILES = args.files

    ok, loaded = check_compatibility(args.files)
    if not ok:
        print("\nRESULT: meshes are NOT vertex-compatible. Morph merge is not "
              "possible on these exports — fall back to the Spline "
              "seven-state scene with crossfade transitions.")
        sys.exit(1)
    print("\nRESULT: COMPATIBLE — morph merge is possible.")
    if not args.check_only:
        merge(loaded, args.out)
