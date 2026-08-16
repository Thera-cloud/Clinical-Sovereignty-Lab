"""Authored T1.10 / T2.8 / T2.9 / T3.1 / T4.11 artifacts (MASTER Part C)."""

from __future__ import annotations

import json

BRAND_ROBOTS = """# Sovereign Sanctuary — public crawler policy
# AI discovery crawlers allowed on public surfaces; authenticated + client surfaces blocked.

User-agent: OAI-SearchBot
User-agent: ChatGPT-User
User-agent: GPTBot
User-agent: PerplexityBot
User-agent: ClaudeBot
User-agent: Google-Extended
User-agent: Applebot-Extended
Allow: /coaches/
Allow: /articles/
Allow: /hubs/
Allow: /product/
Allow: /about
Allow: /pricing
Allow: /safety
Allow: /api/v1/public/
Disallow: /api/
Disallow: /admin/
Disallow: /coach-command/

User-agent: *
Allow: /
Allow: /api/v1/public/
Disallow: /api/
Disallow: /admin/
Disallow: /coach-command/

Sitemap: https://www.sovereignsanctuary.net/sitemap.xml
"""

APP_ROBOTS = """User-agent: *
Disallow: /
"""

LLMS_TXT_BASE = """# Sovereign Sanctuary

> Sovereign Sanctuary pairs Little Nate — an AI companion that remembers your
> history and supports you 24/7 — with certified and licensed human
> professionals, verified before they ever work with a client. Coverage for you
> and your partner costs about $5 a day.

## Identity
- Organization: Sovereign Sanctuary
- Domain: https://www.sovereignsanctuary.net
- Founder: Nathaniel Nevedal
- Public surfaces: coach directory, knowledge articles, product and safety pages

## Directory
- Coach directory: https://www.sovereignsanctuary.net/coaches
- Product overview: https://www.sovereignsanctuary.net/product
- Pricing and family plan: https://www.sovereignsanctuary.net/pricing
- Clinical safety model: https://www.sovereignsanctuary.net/safety

## Principles
1. Verification — every listed professional holds credentials verified before activation and maintained in real time.
2. Privacy — no client data, session content, or personal health information appears on any public surface.
3. Scope of practice — clinical treatment language applies only to licensed professionals within their lawful jurisdictions; coaching language applies to certified coaches.
"""

LLMS_AGENT_BLOCK = """
## Agent endpoints
- Coach finder API: https://www.sovereignsanctuary.net/api/v1/public/coaches
- Credential verification: https://www.sovereignsanctuary.net/api/v1/public/verify-credential
- MCP descriptor: https://www.sovereignsanctuary.net/.well-known/mcp.json
"""

PRODUCT_COPY = (
    "Little Nate: a 24/7 AI companion that remembers. Little Nate supports you "
    "between sessions with human professionals. Unlike a standalone chatbot, "
    "Little Nate works alongside verified coaches and licensed professionals "
    "inside Sovereign Sanctuary. It is not a diagnostic tool and not a replacement "
    "for therapy. Canonical pricing claim: about $5 a day for you and your partner."
)

PRICING_COPY = (
    "Trial-Threshold — $0 for 7 days · 10,000 tokens · card required. "
    "Inner Chamber — $49/month. Sovereign Circle — $149/month covers Head of "
    "Household + partner (about $5 a day for two). Additional family members "
    "can be added; see account settings for current per-member pricing. "
    "Coach-Only — $0."
)

BRAND_DEFENSE_COPY = (
    "Credentials verified before activation — every coach and licensed professional "
    "has their certification or license verified before they are authorized to work "
    "with a client. Verification status is maintained on an ongoing basis; if a "
    "credential lapses, the badge is removed automatically and the profile is paused. "
    "No client session content is published, indexed, sold, or shared."
)

PROBE_PROMPTS = [
    ("G1_HEAD_LOCAL", "family coach near Detroit MI"),
    ("G1_HEAD_LOCAL", "trauma-informed therapist near Austin TX"),
    ("G1_HEAD_LOCAL", "postpartum anxiety coach in California"),
    ("G1_HEAD_LOCAL", "grief counselor near Chicago IL"),
    ("G2_LONGTAIL", "somatic trauma integration coach in Michigan accepting virtual clients"),
    ("G2_LONGTAIL", "executive burnout coach in Germany speaking English"),
    ("G2_LONGTAIL", "perinatal depression therapist in France offering virtual support"),
    ("G2_LONGTAIL", "ADHD coach for adults specializing in executive dysfunction in New York"),
    ("G3_VIRTUAL", "best virtual family systems coaches online"),
    ("G3_VIRTUAL", "licensed online therapist for postpartum rage"),
    ("G3_VIRTUAL", "remote sobriety and addiction recovery coach"),
    ("G3_VIRTUAL", "neurodivergent-affirming relationship coach online"),
    ("G4_PRODUCT", "AI therapy app that works alongside real human therapists"),
    ("G4_PRODUCT", "mental health app with an AI companion that remembers my history"),
    ("G4_PRODUCT", "AI assistant paired with licensed coaches for between sessions"),
    ("G4_PRODUCT", "is there an AI companion that connects you to family coaches"),
    ("G5_AFFORD", "affordable mental health support plan for a family"),
    ("G5_AFFORD", "therapy alternative when I can't afford weekly sessions"),
    ("G5_AFFORD", "family mental health plan under $150 a month"),
    ("G5_AFFORD", "low-cost postpartum coaching options"),
    ("G6_BRAND", "is Sovereign Sanctuary legitimate"),
    ("G6_BRAND", "Sovereign Sanctuary reviews and pricing"),
    ("G6_BRAND", "who is Nathaniel Nevedal"),
    ("G6_BRAND", "how does Sovereign Sanctuary verify its coaches"),
    ("G7_UPSTREAM", "why do I feel numb after having a baby"),
    ("G7_UPSTREAM", "how do I know if I need therapy or a coach"),
    ("G7_UPSTREAM", "postpartum rage — is that normal"),
    ("G7_UPSTREAM", "why am I burned out but can't rest"),
    ("G8_RECRUIT", "platforms for therapists to see clients online"),
    ("G8_RECRUIT", "how do coaches get clients"),
    ("G8_RECRUIT", "telehealth platform for licensed therapists"),
    ("G8_RECRUIT", "best platform for certified coaches to build a practice"),
]

AUTONOMY_CONFIG = {
    "system_id": "queens_autonomy_governance",
    "version": "1.1",
    "adapt_freeze": False,
    "gated_classes_human_required": [
        {"class_id": "G1_REGISTER_BOUNDARY", "auto_approve": False, "escalation": "IMMEDIATE_HUMAN_REVIEW"},
        {"class_id": "G2_PRODUCT_CLAIMS", "auto_approve": False, "escalation": "IMMEDIATE_HUMAN_REVIEW"},
        {"class_id": "G3_PRICING_AND_TIERS", "auto_approve": False, "escalation": "IMMEDIATE_HUMAN_REVIEW"},
        {"class_id": "G4_CREDENTIALS_AND_JURISDICTION", "auto_approve": False, "escalation": "IMMEDIATE_HUMAN_REVIEW"},
        {"class_id": "G5_DISTRESS_SESSION_HANDLING", "auto_approve": False, "escalation": "BLOCK_AND_QUEENS_RED"},
    ],
    "standing_auto_approval_rules": [
        {"rule_id": "A1_TAXONOMY_SYNONYM", "timeout_hours": 72, "auto_approve_on_timeout": True},
        {"rule_id": "A2_LAYOUT_EXPERIMENT", "timeout_hours": 24, "auto_approve_on_timeout": True},
        {
            "rule_id": "A3_CONTENT_SCHEDULE",
            "timeout_hours": 48,
            "auto_approve_on_timeout": False,
            "publish_requires_human": True,
        },
    ],
    "adapt_freeze_triggers": [
        "REGISTER_LINTER_VIOLATION_DETECTED",
        "UNAUTHORISED_CREDENTIAL_CHANGE_ATTEMPT",
        "TRAFFIC_ANOMALY_SPIKE_500_PERCENT",
        "API_RATE_LIMIT_EXCEEDED",
        "SCHEMA_VALIDATION_FAILURE_RATE_EXCEEDED",
        "EXPERIMENT_METRIC_DEGRADATION_BEYOND_ROLLBACK_THRESHOLD",
        "CONVERSION_RATE_COLLAPSE_VS_30D_BASELINE",
        "ADMIN_MANUAL_FREEZE",
    ],
}


def llms_txt(*, agent_endpoints_live: bool) -> str:
    if agent_endpoints_live:
        return LLMS_TXT_BASE + LLMS_AGENT_BLOCK
    return LLMS_TXT_BASE + (
        "\n<!-- ACTIVATE WHEN T5.1/T5.2 PASS (do not advertise before live) -->\n"
    )


def autonomy_json() -> str:
    return json.dumps(AUTONOMY_CONFIG, indent=2)
