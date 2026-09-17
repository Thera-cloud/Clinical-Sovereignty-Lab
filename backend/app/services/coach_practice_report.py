"""Coach performance print report — metrics only, no client names.

QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import asyncio
import datetime as dt
import html
import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_NAME_TOKEN = re.compile(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})?\b")


def strip_client_names(text: str, banned: Optional[List[str]] = None) -> str:
    out = text or ""
    for name in banned or []:
        n = (name or "").strip()
        if len(n) < 3:
            continue
        out = re.sub(re.escape(n), "a client", out, flags=re.IGNORECASE)
    return out


def _esc(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _svg_chart(
    series: List[Dict[str, Any]],
    scatter: Optional[List[Dict[str, Any]]] = None,
    width: int = 720,
    height: int = 220,
) -> str:
    if not series:
        return f'<svg width="{width}" height="{height}"></svg>'
    pad_l, pad_r, pad_t, pad_b = 56, 16, 16, 48
    inner_w = width - pad_l - pad_r
    inner_h = height - pad_t - pad_b
    n = max(len(series) - 1, 1)
    idx = {str(s.get("date")): i for i, s in enumerate(series)}
    pts = []
    live_ticks = []
    for i, s in enumerate(series):
        x = pad_l + inner_w * (i / n)
        h = s.get("healing_mean")
        if h is not None:
            y = pad_t + inner_h * (1.0 - max(0.0, min(1.0, float(h))))
            pts.append((x, y))
        if s.get("live"):
            live_ticks.append(x)
    path = ""
    if pts:
        path = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    ticks = "".join(
        f'<line x1="{x:.1f}" y1="{pad_t}" x2="{x:.1f}" y2="{height - pad_b}" '
        f'stroke="#C9A962" stroke-opacity="0.35" stroke-width="1"/>'
        for x in live_ticks
    )
    dots = []
    for p in scatter or []:
        h = p.get("healing")
        di = idx.get(str(p.get("date") or ""))
        if h is None or di is None:
            continue
        x = pad_l + inner_w * (di / n)
        y = pad_t + inner_h * (1.0 - max(0.0, min(1.0, float(h))))
        kind = str(p.get("kind") or "")
        if kind == "cycle_dip":
            dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.2" fill="#EF4444"/>')
        elif kind == "live_session":
            dots.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="none" stroke="#C9A962" stroke-width="1.4"/>'
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" fill="#E8D5A3"/>'
            )
        elif kind == "carried":
            dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2" fill="#C9A962" fill-opacity="0.35"/>')
        else:
            dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.4" fill="#E8D5A3"/>')
    line = f'<path d="{path}" fill="none" stroke="#C9A962" stroke-width="2"/>' if path else ""
    y_labels = [
        f'<text transform="rotate(-90 12 {height / 2:.0f})" x="12" y="{height / 2:.0f}" '
        f'fill="#E8D5A3" font-size="11" text-anchor="middle">Healing 0–1</text>'
    ]
    for t in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
        y = pad_t + inner_h * (1.0 - t)
        y_labels.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" y2="{y:.1f}" '
            f'stroke="#FFFFFF" stroke-opacity="0.18"/>'
            f'<text x="22" y="{y + 3:.0f}" fill="#E8D5A3" font-size="10">{t:.1f}</text>'
        )
    x_max = max(len(series), 1)
    x_count = x_max if x_max <= 8 else 6
    x_labels = [
        f'<text x="{pad_l + inner_w / 2:.1f}" y="{height - 4}" fill="#E8D5A3" '
        f'font-size="11" text-anchor="middle">Days 0–{x_max}</text>'
    ]
    for k in range(x_count):
        day = 0 if x_count == 1 else round(k / (x_count - 1) * x_max)
        x = pad_l + inner_w * (day / x_max)
        i = min(day, len(series) - 1)
        date = _esc(series[i].get("date") or "")
        x_labels.append(
            f'<line x1="{x:.1f}" y1="{pad_t}" x2="{x:.1f}" y2="{pad_t + inner_h}" '
            f'stroke="#FFFFFF" stroke-opacity="0.12"/>'
            f'<text x="{x:.1f}" y="{height - 22}" fill="#C9A962" font-size="9" '
            f'text-anchor="middle">Day {day}</text>'
            f'<text x="{x:.1f}" y="{height - 12}" fill="#C9A962" font-size="8" '
            f'text-anchor="middle">{date}</text>'
        )
    axes = (
        f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{pad_t + inner_h}" stroke="#C9A962" stroke-width="1.6"/>'
        f'<line x1="{pad_l}" y1="{pad_t + inner_h}" x2="{width - pad_r}" y2="{pad_t + inner_h}" stroke="#C9A962" stroke-width="1.6"/>'
        f'<circle cx="{pad_l}" cy="{pad_t + inner_h}" r="3" fill="#E8D5A3"/>'
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="Practice trend">'
        f'<rect width="{width}" height="{height}" fill="#0A0A0A"/>'
        f"{''.join(y_labels)}{''.join(x_labels)}{axes}"
        f"{ticks}{line}{''.join(dots)}</svg>"
    )


def _fallback_guidance(snap: Dict[str, Any], prior: Optional[Dict[str, Any]], consult: Dict[str, Any]) -> Dict[str, Any]:
    skills = snap.get("skills") or []
    skill_txt = ", ".join(
        str(s.get("skill") or "")
        for s in skills[:4]
        if isinstance(s, dict) and s.get("skill")
    ) or "presence during live sessions"
    totals = _as_dict(snap.get("totals"))
    infl = _as_dict(snap.get("live_influence"))
    mean = totals.get("healing_mean")
    dips = totals.get("cycle_dips") or 0
    lift = infl.get("mean_lift")
    direction = infl.get("direction") or "flat"

    cee = (
        f"High-CEE windows cluster around {skill_txt}. "
        f"That is the skillset this coach reliably opens — unnamed, roster-level."
    )
    actions = [
        "Increase live-session follow-through within 48 hours (LN check-in after each live hour).",
        "Name cycle-dip weeks in supervision and plan one containment move per dip cluster.",
        "Keep one CEE skill as the session opener; do not add a new modality this window.",
    ]
    prior_comp: List[Dict[str, str]] = []
    prior_d = _as_dict(prior)
    if prior_d:
        metrics = _as_dict(prior_d.get("metrics"))
        pt = _as_dict(metrics.get("totals")) or (
            metrics if "healing_mean" in metrics else {}
        )
        pmean = pt.get("healing_mean")
        if mean is not None and pmean is not None:
            delta = float(mean) - float(pmean)
            prior_comp.append({
                "item": "Roster healing mean",
                "change": "improved" if delta > 0.02 else ("decreased" if delta < -0.02 else "stable"),
                "detail": f"{pmean:.3f} → {mean:.3f}",
            })
        pdips = pt.get("cycle_dips") or 0
        prior_comp.append({
            "item": "Cycle dips",
            "change": "improved" if dips < pdips else ("decreased" if dips > pdips else "stable"),
            "detail": f"{pdips} → {dips}",
        })
    decreases = []
    if direction == "down":
        decreases.append(
            "LN turns drop after live sessions (negative lift). Clients are quieter after contact — "
            "review session endings and next-day LN continuity."
        )
    if mean is not None and mean < 0.45:
        decreases.append("Healing mean is below 0.45 across the window — process work is stalling at roster scale.")
    if dips > 8:
        decreases.append("Cycle-dip count is elevated — more trough days than a stable book.")
    if not decreases:
        decreases.append("No material roster-level decrease observed in this window.")

    return {
        "cee_skillset": cee,
        "action_items": actions,
        "prior_items": prior_comp,
        "decrease_causes": decreases,
        "master_actions_completed": consult.get("completed") or [],
        "master_actions_open": consult.get("open") or [],
    }


async def compose_guidance(
    request,
    snap: Dict[str, Any],
    prior: Optional[Dict[str, Any]],
    consult: Dict[str, Any],
    banned_names: List[str],
) -> Dict[str, Any]:
    base = _fallback_guidance(snap, prior, consult)
    router = getattr(getattr(request, "app", None), "state", None)
    infer = getattr(router, "inference_router", None) if router else None
    if infer is None:
        return base
    totals = _as_dict(snap.get("totals"))
    prior_metrics = _as_dict(_as_dict(prior).get("metrics"))
    prior_totals = _as_dict(prior_metrics.get("totals")) or (
        prior_metrics if "healing_mean" in prior_metrics else {}
    )
    prompt = (
        "Write coach-only performance guidance. NEVER name a client, family, or city. "
        "Return JSON with keys: cee_skillset (string), action_items (3 strings), "
        "decrease_causes (array of strings).\n"
        f"Healing mean: {totals.get('healing_mean')}\n"
        f"Cycle dips: {totals.get('cycle_dips')}\n"
        f"LN turns: {totals.get('ln_turns')}\n"
        f"Live sessions: {totals.get('live_sessions')}\n"
        f"Live influence: {json.dumps(_as_dict(snap.get('live_influence')))}\n"
        f"Skill weights: {json.dumps(snap.get('skills') or [])}\n"
        f"Prior totals: {json.dumps(prior_totals)}\n"
    )
    try:
        result = await asyncio.wait_for(
            infer.generate(
                prompt,
                system=(
                    "You are Little Nate writing a coach performance review. "
                    "No client names. Skills only. JSON only."
                ),
                domain="coaching",
                max_tokens=700,
            ),
            timeout=4.0,
        )
        text = (result or {}).get("text") or ""
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return base
        parsed = json.loads(m.group(0))
        for key in ("cee_skillset",):
            if parsed.get(key):
                base[key] = strip_client_names(str(parsed[key]), banned_names)
        if isinstance(parsed.get("action_items"), list) and parsed["action_items"]:
            base["action_items"] = [
                strip_client_names(str(x), banned_names) for x in parsed["action_items"][:3]
            ]
        if isinstance(parsed.get("decrease_causes"), list) and parsed["decrease_causes"]:
            base["decrease_causes"] = [
                strip_client_names(str(x), banned_names) for x in parsed["decrease_causes"][:4]
            ]
    except Exception as e:
        logger.warning("practice report LN guidance fallback: %s", e)
    return base


def render_html(
    snap: Dict[str, Any],
    guidance: Dict[str, Any],
    window_days: int,
) -> str:
    coach = snap.get("coach") or {}
    master = snap.get("master")
    totals = snap.get("totals") or {}
    infl = snap.get("live_influence") or {}
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    master_line = ""
    if master:
        master_line = (
            f"<div class='meta'>Master coach: {_esc(master.get('display_name'))} "
            f"(@{_esc(master.get('username'))})</div>"
        )
    items = "".join(f"<li>{_esc(x)}</li>" for x in (guidance.get("action_items") or []))
    prior = guidance.get("prior_items") or []
    prior_html = "".join(
        f"<li><strong>{_esc(p.get('change'))}</strong> — {_esc(p.get('item'))}: {_esc(p.get('detail'))}</li>"
        for p in prior
    ) or "<li>No prior printed report on file.</li>"
    dec = "".join(f"<li>{_esc(x)}</li>" for x in (guidance.get("decrease_causes") or []))
    done = guidance.get("master_actions_completed") or []
    open_a = guidance.get("master_actions_open") or []
    done_html = "".join(f"<li>{_esc(x.get('text') if isinstance(x, dict) else x)}</li>" for x in done) or "<li>None completed this window.</li>"
    open_html = "".join(f"<li>{_esc(x.get('text') if isinstance(x, dict) else x)}</li>" for x in open_a) or "<li>No open consult requests.</li>"
    svg = _svg_chart(snap.get("series") or [], snap.get("scatter") or [])
    hm = totals.get("healing_mean")
    hm_s = f"{hm:.3f}" if isinstance(hm, (int, float)) else "—"
    lift = infl.get("mean_lift")
    lift_s = f"{lift:+.0%}" if isinstance(lift, (int, float)) else "—"
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<title>Coach Practice Review — {_esc(coach.get('display_name'))}</title>
<style>
  @page {{ margin: 18mm; }}
  body {{ margin:0; background:#050505; color:#E8D5A3; font-family:'DM Sans',Helvetica,Arial,sans-serif; }}
  .page {{ max-width:800px; margin:0 auto; padding:28px 32px 48px; }}
  .letterhead {{ border-bottom:1px solid #C9A962; padding-bottom:14px; margin-bottom:18px; }}
  .brand {{ font-family:'Cormorant Garamond',Georgia,serif; font-size:28px; color:#C9A962; letter-spacing:.04em; }}
  .sub {{ color:#8B7355; font-size:12px; letter-spacing:.18em; text-transform:uppercase; margin-top:4px; }}
  h1 {{ font-family:'Cormorant Garamond',Georgia,serif; font-size:22px; color:#E8D5A3; font-weight:500; }}
  h2 {{ color:#C9A962; font-size:13px; letter-spacing:.14em; text-transform:uppercase; margin:22px 0 8px; }}
  .meta {{ color:#8B7355; font-size:13px; margin:2px 0; }}
  .cards {{ display:flex; gap:10px; flex-wrap:wrap; margin:14px 0; }}
  .card {{ flex:1; min-width:140px; background:#111; border:1px solid #222; padding:10px 12px; }}
  .card b {{ display:block; color:#C9A962; font-size:18px; }}
  .card span {{ color:#8B7355; font-size:11px; letter-spacing:.08em; text-transform:uppercase; }}
  .chart {{ background:#0A0A0A; border:1px solid #222; padding:8px; }}
  li {{ margin:6px 0; color:#E8D5A3; }}
  .foot {{ margin-top:36px; border-top:1px solid #333; padding-top:10px; color:#8B7355; font-size:11px; }}
  @media print {{
    body {{ background:#fff; color:#111; }}
    .brand,h1,h2,.card b {{ color:#8B7355; }}
    .card,.chart {{ border-color:#ccc; background:#fff; }}
    li,.meta {{ color:#222; }}
  }}
</style>
</head><body>
<div class="page">
  <div class="letterhead">
    <div class="brand">Sovereign Sanctuary</div>
    <div class="sub">Coach practice review · Confidential · Metrics only</div>
  </div>
  <h1>{_esc(coach.get('display_name'))} · @{_esc(coach.get('username'))}</h1>
  {master_line}
  <div class="meta">Window: {window_days} days · Printed {now} UTC · Book {_esc(totals.get('roster') or 0)}</div>
  <div class="cards">
    <div class="card"><b>{hm_s}</b><span>Healing mean</span></div>
    <div class="card"><b>{_esc(totals.get('cycle_dips') or 0)}</b><span>Cycle dips</span></div>
    <div class="card"><b>{_esc(totals.get('ln_turns') or 0)}</b><span>LN turns</span></div>
    <div class="card"><b>{_esc(totals.get('live_sessions') or 0)}</b><span>Live sessions</span></div>
    <div class="card"><b>{_esc(lift_s)}</b><span>LN after live</span></div>
    <div class="card"><b>{_esc(totals.get('roster') or 0)}</b><span>Roster size</span></div>
  </div>
  <h2>Practice trend</h2>
  <div class="chart">{svg}</div>
  <p class="meta">Gold line = roster healing mean. Vertical ticks = live-session days. No client names.</p>
  <h2>1. CEE skillset Little Nate observed</h2>
  <p>{_esc(guidance.get('cee_skillset'))}</p>
  <h2>2. Three actions to improve</h2>
  <ol>{items}</ol>
  <h2>3. Prior print-out actions</h2>
  <ul>{prior_html}</ul>
  <h2>4. What caused any decrease</h2>
  <ul>{dec}</ul>
  <h2>5. Master consult requests Little Nate is monitoring</h2>
  <p class="meta">Completed</p>
  <ul>{done_html}</ul>
  <p class="meta">Still open</p>
  <ul>{open_html}</ul>
  <div class="foot">
    © {dt.datetime.now().year} Sovereign Sanctuary · Greatest in the Kingdom Ministry (84-3879515).
    This document is a coach performance measurement. It contains no client names.
    Reproduction limited to the named coach and supervising master.
  </div>
</div>
<script>window.addEventListener('load', function() {{ setTimeout(function() {{ window.print(); }}, 300); }});</script>
</body></html>"""


def anonymize_snapshot(snap: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(snap)
    clean_scatter = []
    for p in snap.get("scatter") or []:
        q = {k: v for k, v in p.items() if k not in ("client", "user")}
        clean_scatter.append(q)
    out["scatter"] = clean_scatter
    selected = snap.get("selected_clients") or []
    out.pop("roster_members", None)
    out.pop("selected_clients", None)
    out["selected_count"] = len(selected)
    sample = dict(out.get("sample") or {})
    sample.pop("names", None)
    out["sample"] = sample
    return out
