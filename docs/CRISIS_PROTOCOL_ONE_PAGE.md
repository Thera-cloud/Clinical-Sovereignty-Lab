# Little Nate — Crisis Protocol (One Page)

**Scope:** Client chat (WebSocket) and voice. **Not emergency services.** Nate surfaces **population-aware crisis lines** and alerts the assigned coach; humans act on alerts.

---

## If the user says X → tier

| User language (examples) | Tier | Primary detector |
|---|---|---|
| “I want to die,” “kill myself,” “end my life,” “better off without me,” “I have a plan/gun/pills,” self-harm | **P0** | `suicide_ideation_lexicon` → coach alert + risk window |
| “suicide,” “hurt myself,” “end it,” “overdose,” “crisis,” “help me” (keyword hit) | **P0/P1** | Bridge metrics `crisis_words` |
| “I’m going to kill them,” homicidal intent toward named person | **P0** | Violence lexicon → coach alert |
| Moral injury / lethality themes (“cleared hot,” “can’t live with what I did,” rage at self) | **P1** | Prompt **OVERRIDE 3 — Witnessing** + TMC `crisis` class |
| Trafficking imminent danger (enrolled Sensitive Bridge) | **P0** | Mandatory reporting path + **1-888-373-7888** when applicable |
| Post-P0 silence / anniversary window | **P2 (tight)** | `checkin_risk_windows` — 24h cadence (not 62/72) |
| Family concern flag (consented) | **P2 (tight)** | Cadence tip; **no content shared** |
| 62h no activity (client, no risk window) | **P2** | `NateCheckInAgent` → coach alert |
| 72h no activity | **P2** | Client + coach outreach nudges |

**Coach alert dedup:** same client suppressed **24h** after a dispatched SI/violence alert (`SI_COACH_ALERT_DEDUP_HOURS`). Risk-window check-ins use a shorter dedup so post-crisis silence is not treated as neutral.

---

## Population-aware resources (`profile_data.population`)

| Population | Primary resources |
|---|---|
| `veteran` | **Veterans Crisis Line** — 988 press 1 / text **838255** |
| `first_responder_le` | **Copline** 1-800-267-5463 + 988 |
| `first_responder_fire_ems` | 988 + Crisis Text Line 741741 |
| `military_family` | 988 + VCL for the veteran in their life |
| `general` (default) | 988 + Crisis Text Line 741741 + 911 |

Flag: `ENABLE_POPULATION_CRISIS_RESOURCES` (default on).

---

## What happens, in order (chat turn)

Clock starts when the client message hits the bridge (`chat_message` / `nate_query`).

| Step | When | ≤ N sec | What fires |
|---|---|---|---|
| **1** | T+0 | **0.1** | Message accepted; `turn_id` assigned. |
| **2** | T+0 | **0.5** | **SI/violence lexicon scan** (CLIENT only). If match → coach notification + `crisis_events` + open **post_p0 risk window** (7d / ~24h cadence). |
| **3** | T+0–3 | **3** | If coach alert **dispatched** → client WebSocket **`crisis_resources`** (population-aware) + “Your coach has been alerted.” |
| **4** | T+0–2 | **2** | **Sensitive Bridge pre-flight** (if enrolled). |
| **5** | T+1–5 | **5** | First Nate tokens. Prompt may include peer-culture voice, night register, confidentiality, OVERRIDE 5 lethal-means (flagged off by default). |
| **6** | T+5–30 | **30** | Full reply. Post-guard injects population-correct resources if missing. |
| **7** | T+after reply | **35** | Metrics / watchlist feed. |
| **8** | Human | **5 min (P0 doc target)** | Assigned coach reviews alert + risk-window status (`GET /api/high-risk-crisis/coach/risk-windows`). |

**Voice calls:** Same registry + population voice suffix; Polly greeting separate from Grok.

---

## Nate’s response rules (all P0/P1)

1. **Stay present** — no “I have to end this chat.”  
2. **Population-correct crisis line** in every crisis-class reply.  
3. **Witness, don’t fix** — moral injury: no hero talk, no condemnation, no absolution.  
4. **No parts/grounding homework** while CRISIS tier is active.  
5. **Confidentiality (high-risk pops):** no line to employer/command; coach may get safety alerts; mandatory reporting only when law requires.  
6. **Lethal means (flagged):** voluntary temporary secure storage only — never confiscation language.  
7. **Sensitive Bridge:** 6-step warm referral when enrolled.

---

## Who gets notified

| Role | Trigger | Channel |
|---|---|---|
| **Client** | SI/violence dispatch | In-app `crisis_resources` banner |
| **Assigned coach** | SI/violence; risk windows; 62h inactivity | Coach notifications + `/coach/risk-windows` |
| **Admin** | Watchlist / Crisis Center | WebSocket `admin_get_crisis_watchlist` |
| **Guardian** | Minor P0/P1 (policy) | SMS/email/call per analytics protocol |
| **Employer / corp** | — | **Never** if `population_shielded` |

---

## Hard limits

- Nate **cannot** geolocate, dispatch 911, or guarantee coach pickup time.  
- Crisis lines are the immediate safety layer; platform alerts are **parallel**.  
- Test accounts can suppress alerts (`CRISIS_ALERT_SUPPRESS_USERNAMES`).

*Code: `crisis_resource_registry.py`, `checkin_risk_windows.py`, `population_prompt_modifiers.py`, `high_risk_crisis_api.py`, `bridge_server.py` `process_interaction`, `nate_checkin_agent.py`.*
