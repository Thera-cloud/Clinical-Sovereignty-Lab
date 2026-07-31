#!/usr/bin/env python3
"""Attempt 6 Phase A — generate completions via burst vLLM, freeze JSONL (no scoring).

Runs prompts on BLUE; completion HTTP hits droplet localhost via SSH.
# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from app.services.ln7_decoupled_bakeoff import (  # noqa: E402
    BakeoffContractError,
    FrozenCompletion,
    build_anchor_rows,
    prompt_hash_for,
    verify_frozen_completeness,
    write_frozen_jsonl,
)
from app.services.ln_sandbox_engineering_ci import (  # noqa: E402
    list_pack_names,
    load_pack,
    materialize_pack,
)


def _load_handoff(path: Path) -> Dict[str, str]:
    kv: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        kv[k.strip()] = v.strip().strip('"').strip("'")
    return kv


def _build_prompt(pack_id: str) -> str:
    workdir, task, err = materialize_pack(pack_id)
    if not workdir or not task:
        raise BakeoffContractError(f"materialize {pack_id}: {err}")
    parts = [task.get("prompt") or "Fix the broken pack so pytest passes."]
    for rel in task.get("target_files") or []:
        fp = workdir / rel
        if fp.is_file():
            parts.append(f"\n--- FILE {rel} ---\n{fp.read_text(encoding='utf-8')}")
    return "\n".join(parts)


_REMOTE_CHAT = r'''
import json, os, sys, time, urllib.request
port = os.environ["PORT"]
key = os.environ["API_KEY"]
model = os.environ["MODEL"]
max_tokens = int(os.environ.get("MAX_TOKENS", "2048"))
timeout_s = int(os.environ.get("TIMEOUT_S", "180"))
prompt = sys.stdin.read()
url = f"http://127.0.0.1:{port}/v1/chat/completions"
hdr = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
body = json.dumps({
    "model": model,
    "messages": [{"role": "user", "content": prompt}],
    "max_tokens": max_tokens,
    "temperature": 0.2,
}).encode()
t0 = time.time()
try:
    req = urllib.request.Request(url, data=body, headers=hdr, method="POST")
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        d = json.loads(r.read().decode())
    text = (((d.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    print(json.dumps({"ok": True, "text": text, "ms": int((time.time() - t0) * 1000)}))
except Exception as e:
    print(json.dumps({"ok": False, "error": str(e)[:500], "ms": int((time.time() - t0) * 1000)}))
'''


def _ssh_chat(
    burst_ssh: str,
    ssh_opts: Sequence[str],
    *,
    port: str,
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int = 2048,
    timeout_s: int = 180,
) -> Dict[str, Any]:
    """One chat completion via SSH → droplet localhost vLLM (prompt on stdin)."""
    env_prefix = (
        f"PORT={shlex.quote(port)} API_KEY={shlex.quote(api_key)} "
        f"MODEL={shlex.quote(model)} MAX_TOKENS={max_tokens} TIMEOUT_S={timeout_s}"
    )
    cmd = [
        "ssh",
        *ssh_opts,
        burst_ssh,
        f"{env_prefix} python3 -c {shlex.quote(_REMOTE_CHAT)}",
    ]
    t0 = time.time()
    proc = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=timeout_s + 60,
    )
    if proc.returncode != 0 and not (proc.stdout or "").strip():
        return {
            "ok": False,
            "error": (proc.stderr or proc.stdout or "ssh_fail")[:500],
            "ms": int((time.time() - t0) * 1000),
        }
    line = (proc.stdout or "").strip().splitlines()[-1] if (proc.stdout or "").strip() else "{}"
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return {"ok": False, "error": f"bad_json:{line[:200]}", "ms": int((time.time() - t0) * 1000)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--handoff", required=True)
    ap.add_argument("--burst-id", required=True)
    ap.add_argument("--rev-a", required=True)
    ap.add_argument("--rev-b", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--manifest-out", default="")
    ap.add_argument("--packs", default="", help="comma list; default first N from list_pack_names")
    ap.add_argument("--max-packs", type=int, default=int(os.environ.get("LN7_BAKEOFF_EXPECTED_PACKS", "18")))
    ap.add_argument("--burst-ssh", default=os.environ.get("LN7_BURST_SSH", ""))
    args = ap.parse_args()

    handoff = _load_handoff(Path(args.handoff))
    port = handoff.get("LN7_BURST_PORT", "11436")
    api_key = handoff.get("LN7_BURST_API_KEY", "")
    if not api_key:
        print("FATAL: no LN7_BURST_API_KEY in handoff", file=sys.stderr)
        return 2
    burst_ssh = args.burst_ssh or f"root@{handoff.get('LN7_BURST_HOST', '')}"
    if "root@" not in burst_ssh or burst_ssh.endswith("@"):
        print(f"FATAL: bad burst ssh {burst_ssh!r}", file=sys.stderr)
        return 3

    ssh_opts = os.environ.get(
        "LN7_SSH_OPTS",
        "-o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=30 "
        "-o ServerAliveInterval=15 -o ServerAliveCountMax=4",
    ).split()

    if args.packs.strip():
        packs = [p.strip() for p in args.packs.split(",") if p.strip()]
    else:
        packs = list_pack_names()[: max(1, args.max_packs)]
    arms = [args.rev_a, args.rev_b]
    print(f"phase_a packs={len(packs)} arms={arms} burst_id={args.burst_id}", file=sys.stderr)

    rows: List[FrozenCompletion] = []
    rows.extend(build_anchor_rows(args.burst_id, packs))

    for pack in packs:
        prompt = _build_prompt(pack)
        ph = prompt_hash_for(pack)
        for arm in arms:
            print(f"generate pack={pack} arm={arm}", file=sys.stderr)
            res = _ssh_chat(
                burst_ssh,
                ssh_opts,
                port=port,
                api_key=api_key,
                model=arm,
                prompt=prompt,
            )
            text = (res.get("text") or "").strip()
            err = "" if res.get("ok") and text else (res.get("error") or "empty_completion")
            if res.get("ok") and text:
                err = ""
            rows.append(
                FrozenCompletion(
                    burst_id=args.burst_id,
                    prompt_hash=ph,
                    pack_id=pack,
                    task_id="",
                    arm_revision_id=arm,
                    adapter_sha=arm,
                    raw_text=text or None,
                    gen_error=err or None,
                    gen_latency_ms=int(res.get("ms") or 0) or None,
                )
            )

    verify_frozen_completeness(rows, packs=packs, arms=arms, tasks_per_pack=1)
    out = Path(args.out)
    write_frozen_jsonl(out, rows)
    manifest = {
        "burst_id": args.burst_id,
        "packs": packs,
        "arms": arms,
        "expected_real": len(packs) * len(arms),
        "expected_anchors": len(packs),
        "total_rows": len(rows),
        "frozen_path": str(out.resolve()),
        "rev_a": args.rev_a,
        "rev_b": args.rev_b,
    }
    man_path = Path(args.manifest_out) if args.manifest_out else out.with_suffix(".manifest.json")
    man_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "frozen": str(out), "manifest": str(man_path), **manifest}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BakeoffContractError as e:
        print(f"FATAL contract: {e}", file=sys.stderr)
        raise SystemExit(5) from e
