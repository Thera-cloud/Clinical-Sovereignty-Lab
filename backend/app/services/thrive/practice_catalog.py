"""Thrive practice catalog — QUANTUM-CRYSTAL-ARCH.

Evidence-based positive-psychology practices Little Nate can turn into
conversational moves, homework, reminders, and coach-visible cadence.

Four focus areas (client-facing), each anchored by one quick-start exercise:

  Daily Happiness          -> Three Good Things       (Seligman)
  Future Direction         -> Best Possible Self      (Laura King)
  Self-Compassion & Confidence -> Strength Dates      (Seligman & Peterson / VIA)
  Handling Stress          -> Self-Compassion Break   (Neff)

Everything else in the catalog (PTG domains, PERMA-V, VIA 24, Broaden-and-
Build, Appreciative Inquiry 4-D, antifragile moves) is what LN *thinks with*
and offers when the anchor practices are established or the client asks for
more. Nothing here is a script — LN keeps its own voice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# --------------------------------------------------------------------------
# Focus areas
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FocusArea:
    key: str
    label: str
    anchor_practice: str
    develops: str
    perma_pillars: Tuple[str, ...]
    ptg_domains: Tuple[str, ...]


FOCUS_AREAS: Dict[str, FocusArea] = {
    "daily_happiness": FocusArea(
        key="daily_happiness",
        label="Daily Happiness",
        anchor_practice="three_good_things",
        develops="gratitude & positive focus",
        perma_pillars=("positive_emotion", "engagement"),
        ptg_domains=("appreciation_of_life",),
    ),
    "future_direction": FocusArea(
        key="future_direction",
        label="Future Direction",
        anchor_practice="best_possible_self",
        develops="optimism & hope",
        perma_pillars=("meaning", "achievement"),
        ptg_domains=("new_possibilities",),
    ),
    "self_compassion_confidence": FocusArea(
        key="self_compassion_confidence",
        label="Self-Compassion & Confidence",
        anchor_practice="strength_date",
        develops="self-awareness & energy",
        perma_pillars=("engagement", "achievement", "vitality"),
        ptg_domains=("personal_strength",),
    ),
    "handling_stress": FocusArea(
        key="handling_stress",
        label="Handling Stress",
        anchor_practice="self_compassion_break",
        develops="emotional resilience",
        perma_pillars=("positive_emotion", "relationships"),
        ptg_domains=("personal_strength", "spiritual_existential"),
    ),
}


# --------------------------------------------------------------------------
# Practices
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Practice:
    key: str
    label: str
    source: str
    focus_area: str
    default_cadence: str            # daily | weekly | as_needed
    default_time_of_day: str        # morning | midday | evening | any
    minutes: int
    steps: Tuple[str, ...]
    # How LN opens it in conversation (LN rephrases; this is the *move*, not copy)
    ln_move: str
    # What LN asks afterwards to log a completion + harvest a crystal
    ln_harvest: str
    reminder_subject: str
    reminder_line: str


PRACTICES: Dict[str, Practice] = {
    "three_good_things": Practice(
        key="three_good_things",
        label="Three Good Things",
        source="Seligman (2005) — gratitude intervention",
        focus_area="daily_happiness",
        default_cadence="daily",
        default_time_of_day="evening",
        minutes=5,
        steps=(
            "Before bed, name three things that went well today (big or small).",
            "For each, write why it went well — what you did, or what made it possible.",
        ),
        ln_move="Invite three good things from today and, for each one, the 'why' — the part the client made happen.",
        ln_harvest="Ask which of the three surprised them most, and what it says about who they are becoming.",
        reminder_subject="Three good things tonight?",
        reminder_line="Before you sleep — three things that went well today, and why. I'd love to hear them tomorrow.",
    ),
    "best_possible_self": Practice(
        key="best_possible_self",
        label="Best Possible Self",
        source="Laura King (2001) — future-self writing",
        focus_area="future_direction",
        default_cadence="weekly",
        default_time_of_day="morning",
        minutes=15,
        steps=(
            "Imagine your life 1-5 years from now where everything has gone as well as it possibly could.",
            "Write for 15 minutes about that life — relationships, work, health, faith, play — in the present tense.",
            "Pull one concrete thread you can act on this week.",
        ),
        ln_move="Invite the client to describe the best-case future in present tense, then find the first thread to pull this week.",
        ln_harvest="Ask which detail felt most alive, and turn it into one goal with a date.",
        reminder_subject="Fifteen minutes with your best possible self",
        reminder_line="This week's writing window: your life a few years out, everything going as well as it could. Present tense. Then tell me the one thread you want to pull.",
    ),
    "strength_date": Practice(
        key="strength_date",
        label="Strength Date",
        source="Seligman & Peterson — VIA signature strengths in a new way",
        focus_area="self_compassion_confidence",
        default_cadence="weekly",
        default_time_of_day="any",
        minutes=30,
        steps=(
            "Name your top five character strengths (in-house strengths conversation or VIA survey).",
            "Pick one and plan a block of time this week to use it in a brand-new way.",
            "Afterwards, notice the energy and confidence it produced.",
        ),
        ln_move="Surface one of the client's top strengths from memory and design a way to use it somewhere it has never been used.",
        ln_harvest="Ask how it felt in the body to use that strength on purpose, and where else it wants to go.",
        reminder_subject="Your strength date this week",
        reminder_line="Pick one of your top strengths and take it somewhere new this week — a place it has never been used. Tell me what happened.",
    ),
    "self_compassion_break": Practice(
        key="self_compassion_break",
        label="Self-Compassion Break",
        source="Kristin Neff — Mindful Self-Compassion",
        focus_area="handling_stress",
        default_cadence="as_needed",
        default_time_of_day="any",
        minutes=3,
        steps=(
            "Mindfulness: 'This is a moment of suffering.'",
            "Common humanity: 'Suffering is a part of life.'",
            "Kindness: 'May I be kind to myself in this moment.'",
            "Hand on heart or another soothing touch while you say it.",
        ),
        ln_move="When stress shows up, walk the three sentences with the client in the present moment rather than analysing the stressor.",
        ln_harvest="Ask what shifted after the third sentence, and what the kind voice sounded like.",
        reminder_subject="A three-breath self-compassion break",
        reminder_line="If today gets heavy: this is a moment of suffering; suffering is part of life; may I be kind to myself right now. Three breaths. That's the whole practice.",
    ),
    # ---- extended catalog (offered once anchors are established) -------------
    "gratitude_letter": Practice(
        key="gratitude_letter",
        label="Gratitude Letter / Visit",
        source="Seligman — gratitude visit",
        focus_area="daily_happiness",
        default_cadence="weekly",
        default_time_of_day="any",
        minutes=20,
        steps=("Write a letter to someone who changed your life for the better and never heard it.", "Read it to them if you can."),
        ln_move="Ask who never got thanked, and what the client would say.",
        ln_harvest="Ask what it did to the relationship — and to the client.",
        reminder_subject="Who never got the thank-you?",
        reminder_line="One letter this week to someone who changed things for you. Read it to them if you can.",
    ),
    "savoring_walk": Practice(
        key="savoring_walk",
        label="Savoring Walk",
        source="Bryant & Veroff — savoring; Fredrickson broaden-and-build",
        focus_area="daily_happiness",
        default_cadence="weekly",
        default_time_of_day="midday",
        minutes=20,
        steps=("Walk for 20 minutes noticing only what is pleasant.", "Name each pleasant thing silently as you pass it."),
        ln_move="Suggest widening attention to what is good in the ordinary environment.",
        ln_harvest="Ask what they noticed that they usually walk past.",
        reminder_subject="A savoring walk",
        reminder_line="Twenty minutes outside noticing only what is pleasant. Name each one. Tell me your favorite.",
    ),
    "goal_ladder": Practice(
        key="goal_ladder",
        label="Goal Ladder (hope theory)",
        source="Snyder — hope theory: goals, pathways, agency",
        focus_area="future_direction",
        default_cadence="weekly",
        default_time_of_day="morning",
        minutes=15,
        steps=("Name the goal.", "List three pathways to it.", "Name the smallest agency step for today."),
        ln_move="Translate a Best-Possible-Self thread into goal / pathways / today's step.",
        ln_harvest="Log the goal with a target date; ask what would make the path fail and how to route around it.",
        reminder_subject="What can you complete today?",
        reminder_line="Which goal is live this week — and what is the one step you can complete today?",
    ),
    "strengths_spotting": Practice(
        key="strengths_spotting",
        label="Strengths Spotting",
        source="VIA Institute — strengths spotting in others and self",
        focus_area="self_compassion_confidence",
        default_cadence="daily",
        default_time_of_day="evening",
        minutes=3,
        steps=("Name one strength you used today and how.", "Name one strength you saw in someone else."),
        ln_move="Reframe a day's events as strengths in action.",
        ln_harvest="Add the spotted strength to the client's strengths profile if it is new.",
        reminder_subject="Which strength showed up today?",
        reminder_line="One strength you used today, one you saw in someone else. Two sentences.",
    ),
    "antifragile_review": Practice(
        key="antifragile_review",
        label="Antifragile Review",
        source="Taleb — Antifragile: hormesis, via negativa, optionality, barbell",
        focus_area="handling_stress",
        default_cadence="weekly",
        default_time_of_day="evening",
        minutes=10,
        steps=(
            "Name one stressor this week that left you *better* (hormesis).",
            "Name one thing to remove that makes you fragile (via negativa).",
            "Name one small bet with capped downside and open upside (optionality).",
        ),
        ln_move="Reframe the week's hard moments as data on what strengthens the client, and find one thing to subtract.",
        ln_harvest="Record the hormetic win and the subtraction as goals; celebrate the small bet placed.",
        reminder_subject="This week's antifragile review",
        reminder_line="What made you stronger this week? What should you remove? What small bet can you place? Three answers.",
    ),
    "appreciative_inquiry": Practice(
        key="appreciative_inquiry",
        label="Appreciative Inquiry 4-D",
        source="Cooperrider & Srivastva — Discover, Dream, Design, Destiny",
        focus_area="future_direction",
        default_cadence="weekly",
        default_time_of_day="any",
        minutes=20,
        steps=("Discover: when was this area of life at its best?", "Dream: what would 'more of that' look like?", "Design: what structure makes it likely?", "Destiny: what do you commit to?"),
        ln_move="Run a 4-D pass on a relationship, role, or project the client cares about.",
        ln_harvest="Capture the Design + Destiny answers as goals with dates.",
        reminder_subject="When was it at its best?",
        reminder_line="Pick one area of life. When was it at its best? What would more of that look like? Bring me your answer.",
    ),
}

ANCHOR_PRACTICES: Tuple[str, ...] = tuple(fa.anchor_practice for fa in FOCUS_AREAS.values())


def practices_for_focus_area(key: str) -> List[Practice]:
    return [p for p in PRACTICES.values() if p.focus_area == key]


# --------------------------------------------------------------------------
# Reference models LN thinks with
# --------------------------------------------------------------------------

PTG_DOMAINS: Dict[str, str] = {
    "new_possibilities": "New life possibilities — paths that were not visible before",
    "relationships": "Deeper, more authentic relationships",
    "personal_strength": "Personal strength — 'if I survived that, I can face this'",
    "appreciation_of_life": "Greater appreciation for life and the ordinary day",
    "spiritual_existential": "Spiritual / existential growth — meaning, faith, purpose",
}

PERMA_V: Dict[str, str] = {
    "positive_emotion": "Positive emotion — joy, gratitude, serenity, hope",
    "engagement": "Engagement — flow, absorption, using strengths",
    "relationships": "Relationships — feeling loved, supported, valued",
    "meaning": "Meaning — belonging to and serving something bigger",
    "achievement": "Achievement — mastery, competence, goals completed",
    "vitality": "Vitality — sleep, movement, nutrition, energy",
}

# VIA Classification — 24 character strengths under six virtues.
VIA_STRENGTHS: Dict[str, Tuple[str, ...]] = {
    "wisdom": ("creativity", "curiosity", "judgment", "love_of_learning", "perspective"),
    "courage": ("bravery", "perseverance", "honesty", "zest"),
    "humanity": ("love", "kindness", "social_intelligence"),
    "justice": ("teamwork", "fairness", "leadership"),
    "temperance": ("forgiveness", "humility", "prudence", "self_regulation"),
    "transcendence": ("appreciation_of_beauty", "gratitude", "hope", "humor", "spirituality"),
}
VIA_FLAT: Tuple[str, ...] = tuple(s for group in VIA_STRENGTHS.values() for s in group)

# CliftonStrengths is licensed — LN maps to its four public domains only.
CLIFTON_DOMAINS: Dict[str, Tuple[str, ...]] = {
    "executing": ("perseverance", "self_regulation", "prudence", "fairness"),
    "influencing": ("leadership", "zest", "bravery", "social_intelligence", "humor"),
    "relationship_building": ("love", "kindness", "forgiveness", "teamwork", "gratitude", "humility"),
    "strategic_thinking": ("creativity", "curiosity", "judgment", "love_of_learning", "perspective", "hope"),
}

MSC_CORE = (
    "mindfulness (name the pain without over-identifying)",
    "common humanity (you are not alone in this)",
    "self-kindness (speak to yourself as you would to someone you love)",
)

BROADEN_AND_BUILD = (
    "Positive emotions widen the thought-action repertoire — savor before you strategize.",
    "Small daily positives compound into resources: skills, relationships, resilience.",
    "Positivity ratio: notice, name, and lengthen the good moments.",
)

ANTIFRAGILE_MOVES: Dict[str, str] = {
    "hormesis": "Choose stretch on purpose — a stressor small enough to metabolize leaves you stronger.",
    "via_negativa": "Subtract before you add — remove what fragilizes (people, habits, inputs) before adding practices.",
    "optionality": "Prefer small bets with capped downside and open upside; you don't need to predict to win.",
    "barbell": "Be extremely safe in the essentials and bold in the experiments; avoid the fragile middle.",
    "skin_in_the_game": "Commit visibly — tell someone the goal and the date.",
    "iatrogenics": "Don't intervene where the system is healing itself — a wobble is data, not relapse.",
}

# --------------------------------------------------------------------------
# In-house strengths conversation (free; replaces external VIA/Gallup)
# --------------------------------------------------------------------------

STRENGTHS_INTERVIEW: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("Tell me about a time in the last year you lost track of time because you were absorbed in something.",
     ("curiosity", "creativity", "love_of_learning", "zest")),
    ("When people come to you for help, what do they usually come for?",
     ("kindness", "judgment", "perspective", "social_intelligence", "leadership")),
    ("What have you kept doing even when it was hard and nobody was watching?",
     ("perseverance", "honesty", "self_regulation", "bravery")),
    ("What do you notice that other people walk past?",
     ("appreciation_of_beauty", "gratitude", "curiosity", "social_intelligence")),
    ("Where does your sense of meaning come from on a good day?",
     ("spirituality", "love", "hope", "humility")),
    ("What makes you laugh, and who do you make laugh?",
     ("humor", "zest", "love")),
    ("When something goes wrong between you and someone you care about, what do you do first?",
     ("forgiveness", "fairness", "teamwork", "prudence")),
)


def strengths_from_answers(tags_per_answer: List[List[str]]) -> List[Tuple[str, int]]:
    """Naive tally used by the in-house conversation; LN refines with judgment."""
    counts: Dict[str, int] = {}
    for tags in tags_per_answer:
        for t in tags:
            if t in VIA_FLAT:
                counts[t] = counts.get(t, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
