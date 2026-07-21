"""Clinical psychoeducation curriculum for Little Nate Dispatch.

# QUANTUM-CRYSTAL-ARCH — Clinical editorial focus (CBT/DBT/ACT/IFS/ADEP/relationships)
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional


def clinical_editorial_mode() -> bool:
    """Default ON — culture/news trend hooks are off unless explicitly disabled."""
    return os.getenv("ENABLE_NEWSLETTER_CLINICAL_FOCUS", "true").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


# Rotating clinical curriculum. Selection scores these above trend/viral noise.
CLINICAL_CURRICULUM: List[Dict[str, Any]] = [
    {
        "topic_key": "cbt_thought_records",
        "title": "CBT thought records: catching the story before it runs you",
        "domain": "cbt",
        "modalities": ["CBT"],
        "psychoeducation": (
            "Cognitive Behavioral Therapy (CBT) treats thoughts as hypotheses, not facts. "
            "A thought record slows automatic appraisals so you can test evidence for and "
            "against a sticky belief — education only, not a diagnosis or treatment plan."
        ),
        "techniques": [
            {
                "step": 1,
                "modality": "CBT",
                "text": "Situation: write one concrete moment (who/where/what) in one sentence.",
            },
            {
                "step": 2,
                "modality": "CBT",
                "text": "Automatic thought: write the exact sentence your mind said (no polishing).",
            },
            {
                "step": 3,
                "modality": "CBT",
                "text": "Evidence for / against: list 2 facts that support it and 2 that challenge it.",
            },
            {
                "step": 4,
                "modality": "CBT",
                "text": "Balanced reframe: write one sentence that fits both columns without toxic positivity.",
            },
        ],
        "nate_prompts": [
            'Walk me through a CBT thought record on this belief: "___."',
            "Help me separate facts from interpretations in what just happened.",
            "Challenge this thought with me without dismissing how I feel.",
        ],
    },
    {
        "topic_key": "cbt_behavioral_activation",
        "title": "Behavioral activation: tiny actions that reopen a stuck day",
        "domain": "cbt",
        "modalities": ["CBT"],
        "psychoeducation": (
            "When mood drops, activity often shrinks — and the shrink feeds the drop. "
            "Behavioral activation schedules small valued actions before motivation returns."
        ),
        "techniques": [
            {
                "step": 1,
                "modality": "CBT",
                "text": "Name one valued domain (body, connection, mastery, joy) that has gone quiet.",
            },
            {
                "step": 2,
                "modality": "CBT",
                "text": "Pick a 10-minute action that fits that domain — smaller than pride allows.",
            },
            {
                "step": 3,
                "modality": "CBT",
                "text": "Schedule it on the calendar with a start time; treat it like an appointment.",
            },
            {
                "step": 4,
                "modality": "CBT",
                "text": "Afterward, rate mood 0–10 before/after — data, not judgment.",
            },
        ],
        "nate_prompts": [
            "Help me design a 10-minute behavioral activation for today.",
            "I am waiting for motivation — coach me to act first with one tiny step.",
            "What valued domain have I abandoned, and what is the smallest restart?",
        ],
    },
    {
        "topic_key": "dbt_distress_tolerance",
        "title": "DBT distress tolerance: riding the wave without making it worse",
        "domain": "dbt",
        "modalities": ["DBT"],
        "psychoeducation": (
            "Dialectical Behavior Therapy (DBT) distress-tolerance skills are for the moments "
            "you cannot solve the problem yet — TIPP, STOP, and urge surfing reduce harm "
            "while the peak passes."
        ),
        "techniques": [
            {
                "step": 1,
                "modality": "DBT",
                "text": "STOP: Stop · Take a breath · Observe · Proceed with one wise next step.",
            },
            {
                "step": 2,
                "modality": "DBT",
                "text": "TIPP cold: cool face/hands or sip cold water to drop physiological arousal.",
            },
            {
                "step": 3,
                "modality": "DBT",
                "text": "Urge surf: rate the urge 0–10 every 60 seconds for 5 minutes without acting.",
            },
            {
                "step": 4,
                "modality": "DBT",
                "text": "Opposite action lite: do the smallest safe opposite of the impulse (stand, text a check-in, step outside).",
            },
        ],
        "nate_prompts": [
            "Guide me through DBT STOP and TIPP right now.",
            "Help me urge-surf this craving/impulse without lectures.",
            "What is one opposite action that is safe for me in this moment?",
        ],
    },
    {
        "topic_key": "dbt_interpersonal_effectiveness",
        "title": "DBT DEAR MAN: asking clearly without collapsing or attacking",
        "domain": "dbt",
        "modalities": ["DBT", "relationships"],
        "psychoeducation": (
            "DBT interpersonal effectiveness (DEAR MAN) structures hard asks: Describe, Express, "
            "Assert, Reinforce — Mindful, Appear confident, Negotiate. Skills for relationships, "
            "not scripts to manipulate."
        ),
        "techniques": [
            {
                "step": 1,
                "modality": "DBT",
                "text": "Describe the facts of the situation in one neutral sentence (no character attacks).",
            },
            {
                "step": 2,
                "modality": "DBT",
                "text": "Express your feeling with an “I” statement tied to that fact.",
            },
            {
                "step": 3,
                "modality": "DBT",
                "text": "Assert the specific ask (time, behavior, boundary) in one sentence.",
            },
            {
                "step": 4,
                "modality": "DBT",
                "text": "Reinforce: name what improves for both of you if the ask is met; leave room to negotiate.",
            },
        ],
        "nate_prompts": [
            "Build a DEAR MAN script for this ask: ___",
            "Help me ask for what I need without over-explaining or apologizing for existing.",
            "Role-play their pushback so I can stay mindful and negotiate.",
        ],
    },
    {
        "topic_key": "act_values_and_defusion",
        "title": "ACT: defuse from sticky thoughts and move toward values",
        "domain": "act",
        "modalities": ["ACT"],
        "psychoeducation": (
            "Acceptance and Commitment Therapy (ACT) trains psychological flexibility: notice "
            "thoughts (defusion), make room for feeling (acceptance), and take valued action "
            "even when discomfort tags along."
        ),
        "techniques": [
            {
                "step": 1,
                "modality": "ACT",
                "text": "Name the thought as a thought: “I’m having the thought that …”",
            },
            {
                "step": 2,
                "modality": "ACT",
                "text": "Thank your mind for trying to protect you — then return to the room (5 senses).",
            },
            {
                "step": 3,
                "modality": "ACT",
                "text": "Pick one value word for today (kindness, courage, honesty, stewardship).",
            },
            {
                "step": 4,
                "modality": "ACT",
                "text": "Take one 5-minute action that serves that value while the feeling is still present.",
            },
        ],
        "nate_prompts": [
            "Help me defuse from this thought using ACT language.",
            "What value am I abandoning when I avoid this, and what is one step toward it?",
            "Sit with me in discomfort without trying to erase it — then pick a valued action.",
        ],
    },
    {
        "topic_key": "ifs_parts_mapping",
        "title": "IFS parts language: meeting protectors without exile-hunting",
        "domain": "ifs",
        "modalities": ["IFS"],
        "psychoeducation": (
            "Internal Family Systems (IFS) maps inner parts — protectors, managers, exiles — "
            "and Self energy (curiosity, calm, compassion). This Dispatch uses parts language "
            "for self-understanding, not clinical IFS therapy."
        ),
        "techniques": [
            {
                "step": 1,
                "modality": "IFS",
                "text": "Notice a strong reaction and ask: which part of me just got loud?",
            },
            {
                "step": 2,
                "modality": "IFS",
                "text": "Thank the protector for its job; ask what it fears would happen if it stood down.",
            },
            {
                "step": 3,
                "modality": "IFS",
                "text": "Check Self qualities: curious? calm? compassionate? If not, pause and breathe.",
            },
            {
                "step": 4,
                "modality": "IFS",
                "text": "Offer the part one sentence of appreciation and one boundary you will keep today.",
            },
        ],
        "nate_prompts": [
            "Help me map the parts that showed up when ___ happened.",
            "Talk with this protector part — what is it afraid of?",
            "How do I stay in Self energy when my manager part wants control?",
        ],
    },
    {
        "topic_key": "adep_attachment_repair",
        "title": "ADEP / attachment: naming the protest under the fight",
        "domain": "adep",
        "modalities": ["ADEP", "EFT", "relationships"],
        "psychoeducation": (
            "Attachment-oriented work (including ADEP-informed and Emotionally Focused frames) "
            "hears protest, withdraw, and pursue as bids for safety. Naming the soft emotion under "
            "the hard strategy opens repair — education, not couple therapy."
        ),
        "techniques": [
            {
                "step": 1,
                "modality": "ADEP",
                "text": "In the last conflict, were you more pursue, withdraw, or freeze?",
            },
            {
                "step": 2,
                "modality": "ADEP",
                "text": "Name the soft feeling under the strategy (lonely, scared, ashamed, unseen).",
            },
            {
                "step": 3,
                "modality": "ADEP",
                "text": "Write one attachment message: “When ___, I felt ___, and I needed ___.”",
            },
            {
                "step": 4,
                "modality": "ADEP",
                "text": "Practice saying it slowly once aloud (or to Nate) before any live conversation.",
            },
        ],
        "nate_prompts": [
            "Help me find the soft emotion under my last fight with my partner.",
            "Translate my protest into an attachment need I can say cleanly.",
            "I shut down when they raise their voice — sit with the fear and craft one repair line.",
        ],
    },
    {
        "topic_key": "grounding_5_4_3_2_1",
        "title": "Grounding 5-4-3-2-1: coming back when the body time-travels",
        "domain": "somatic",
        "modalities": ["grounding", "somatic"],
        "psychoeducation": (
            "Grounding skills re-orient attention to present sensory data when anxiety, trauma "
            "activation, or dissociation pulls you out of now. Simple, repeatable, portable."
        ),
        "techniques": [
            {
                "step": 1,
                "modality": "grounding",
                "text": "5 things you can see — name them out loud or on paper.",
            },
            {
                "step": 2,
                "modality": "grounding",
                "text": "4 things you can feel (feet, fabric, temperature, pressure).",
            },
            {
                "step": 3,
                "modality": "grounding",
                "text": "3 things you can hear; 2 you can smell; 1 you can taste or remember tasting.",
            },
            {
                "step": 4,
                "modality": "grounding",
                "text": "Orient: say today’s date and where you are — “I am here, now, safe enough.”",
            },
        ],
        "nate_prompts": [
            "Walk me through 5-4-3-2-1 grounding slowly.",
            "I feel floaty/activated — stay with me and keep me in the present.",
            "After grounding, help me name what triggered the spike without spiraling.",
        ],
    },
    {
        "topic_key": "polyvagal_window_of_tolerance",
        "title": "Window of tolerance: noticing hyperarousal, shutdown, and return",
        "domain": "somatic",
        "modalities": ["somatic", "polyvagal"],
        "psychoeducation": (
            "Polyvagal-informed psychoeducation maps hyperarousal (fight/flight), hypoarousal "
            "(shutdown), and a window where connection and thinking are available. The goal is "
            "recognition and gentle return — not perfect calm."
        ),
        "techniques": [
            {
                "step": 1,
                "modality": "somatic",
                "text": "Body scan 60 seconds: jaw, chest, belly, hands — tight, numb, or okay?",
            },
            {
                "step": 2,
                "modality": "somatic",
                "text": "Label state: hyper / in window / hypo — no shame, just data.",
            },
            {
                "step": 3,
                "modality": "somatic",
                "text": "If hyper: lengthen exhale; if hypo: stand, cold water, or gentle movement.",
            },
            {
                "step": 4,
                "modality": "somatic",
                "text": "Co-regulate: one safe contact (pet, trusted person, Nate) for two minutes.",
            },
        ],
        "nate_prompts": [
            "Am I hyperaroused or shut down right now? Help me check.",
            "Coach a return to my window of tolerance without flooding me.",
            "What signal in my body usually means I am leaving the window?",
        ],
    },
    {
        "topic_key": "mi_change_talk",
        "title": "Motivational Interviewing: hearing your own reasons for change",
        "domain": "mi",
        "modalities": ["MI"],
        "psychoeducation": (
            "Motivational Interviewing (MI) evokes change talk — desire, ability, reasons, need — "
            "instead of arguing for change. Useful when ambivalence is the real block."
        ),
        "techniques": [
            {
                "step": 1,
                "modality": "MI",
                "text": "Name the habit/decision you feel two ways about in one sentence.",
            },
            {
                "step": 2,
                "modality": "MI",
                "text": "Sustain talk: honestly list what staying the same still gives you.",
            },
            {
                "step": 3,
                "modality": "MI",
                "text": "Change talk: list desire/ability/reasons/need for shifting — in your words.",
            },
            {
                "step": 4,
                "modality": "MI",
                "text": "Commitment: one next step you are willing to try (not “should”).",
            },
        ],
        "nate_prompts": [
            "Use MI with me on this ambivalence: ___",
            "Do not push me — help me hear my own change talk.",
            "Reflect back my reasons for change without adding yours.",
        ],
    },
    {
        "topic_key": "relationship_repair_attempts",
        "title": "Repair attempts: the small bids that stop a fight from becoming a story",
        "domain": "relationships",
        "modalities": ["relationships", "Gottman-informed"],
        "psychoeducation": (
            "Relationship research highlights repair attempts — jokes, soft starts, “can we pause?” — "
            "as predictors of stability. Practice noticing and accepting repairs, not winning rounds."
        ),
        "techniques": [
            {
                "step": 1,
                "modality": "relationships",
                "text": "Soft start-up: complaint without contempt — “I feel __ about __, I need __.”",
            },
            {
                "step": 2,
                "modality": "relationships",
                "text": "Name a repair phrase you can use: “Timeout 20?” / “That landed hard — retry?”",
            },
            {
                "step": 3,
                "modality": "relationships",
                "text": "Accept a repair: practice saying “okay, let’s reset” even if you are still hurt.",
            },
            {
                "step": 4,
                "modality": "relationships",
                "text": "Aftercare: one appreciation within 24 hours unrelated to the fight.",
            },
        ],
        "nate_prompts": [
            "Help me soft-start this complaint without contempt.",
            "What repair attempt can I offer mid-fight when I am flooded?",
            "Coach me to accept their repair even when I want to keep arguing.",
        ],
    },
    {
        "topic_key": "relationship_listening_reflect",
        "title": "Reflective listening: hearing the need under the volume",
        "domain": "relationships",
        "modalities": ["relationships", "MI"],
        "psychoeducation": (
            "Reflective listening restates meaning and feeling before advice. It lowers threat "
            "in the nervous system of the speaker — a core communication tool for couples, families, "
            "and co-parents."
        ),
        "techniques": [
            {
                "step": 1,
                "modality": "relationships",
                "text": "Speaker gets 2 uninterrupted minutes; listener only tracks key words.",
            },
            {
                "step": 2,
                "modality": "relationships",
                "text": "Listener reflects: “What I hear is ___; the feeling sounds like ___.”",
            },
            {
                "step": 3,
                "modality": "relationships",
                "text": "Speaker rates accuracy 0–10; if under 8, speaker clarifies once; listener re-reflects.",
            },
            {
                "step": 4,
                "modality": "relationships",
                "text": "Only then: one question or one offer of help — not a rebuttal.",
            },
        ],
        "nate_prompts": [
            "Practice reflective listening with me — I will vent, you reflect.",
            "Help me reflect my partner’s point without agreeing or defending.",
            "What need might be under their volume right now?",
        ],
    },
    {
        "topic_key": "nate_usage_skill_coach",
        "title": "How to use Little Nate: ask for skills, not just comfort",
        "domain": "nate_usage",
        "modalities": ["Nate usage", "CBT", "DBT"],
        "psychoeducation": (
            "Little Nate is strongest when you give a modality, a moment, and a ask: "
            "“Use CBT on this thought,” “DBT TIPP with me,” “DEAR MAN this ask.” "
            "Vague chats get vague comfort; structured prompts get structured skills."
        ),
        "techniques": [
            {
                "step": 1,
                "modality": "Nate usage",
                "text": "Template: “Modality + situation + ask” — e.g. “DBT STOP — my teen just slammed a door.”",
            },
            {
                "step": 2,
                "modality": "Nate usage",
                "text": "Add constraint: “No pep talk — one skill, then check if I can do it.”",
            },
            {
                "step": 3,
                "modality": "Nate usage",
                "text": "Request practice: “Role-play their response” or “Quiz me on the steps.”",
            },
            {
                "step": 4,
                "modality": "Nate usage",
                "text": "Close the loop: “Summarize my plan in 3 bullets I can screenshot.”",
            },
        ],
        "nate_prompts": [
            "Use CBT on this automatic thought — one thought record, then stop.",
            "DBT interpersonal: build DEAR MAN for this ask, then role-play pushback.",
            "I want skills not soothing — coach ACT values action for the next hour.",
        ],
    },
    {
        "topic_key": "nate_usage_crisis_boundaries",
        "title": "How to use Little Nate safely: crisis lines stay human",
        "domain": "nate_usage",
        "modalities": ["Nate usage", "safety"],
        "psychoeducation": (
            "Nate can sit with hard feelings and coach skills, but emergency safety belongs with "
            "humans and local crisis resources (988 in the US). Use Nate for skills and reflection; "
            "use crisis lines when there is imminent risk."
        ),
        "techniques": [
            {
                "step": 1,
                "modality": "safety",
                "text": "If you are in immediate danger, call local emergency services first.",
            },
            {
                "step": 2,
                "modality": "safety",
                "text": "US: 988 Lifeline; veterans: 988 then press 1; worldwide: findahelpline.com.",
            },
            {
                "step": 3,
                "modality": "Nate usage",
                "text": "With Nate: ask for grounding, a safety plan draft, or who to text — not secrecy from helpers.",
            },
            {
                "step": 4,
                "modality": "Nate usage",
                "text": "After stabilization: “Help me practice one coping skill for the next 24 hours.”",
            },
        ],
        "nate_prompts": [
            "I am safe enough — help me ground and build a next-24-hours coping plan.",
            "Draft who I can contact and what I will say if tonight gets hard.",
            "Remind me when to use 988 vs when skills with you are enough.",
        ],
    },
    {
        "topic_key": "shame_self_compassion",
        "title": "Shame vs guilt: self-compassion without letting yourself off the hook",
        "domain": "self_compassion",
        "modalities": ["self-compassion", "CBT"],
        "psychoeducation": (
            "Guilt says “I did something bad”; shame says “I am bad.” Self-compassion research "
            "(common humanity, mindfulness, kindness) supports change better than self-attack."
        ),
        "techniques": [
            {
                "step": 1,
                "modality": "self-compassion",
                "text": "Label: shame or guilt? (identity vs behavior).",
            },
            {
                "step": 2,
                "modality": "self-compassion",
                "text": "Common humanity: name one other human who has felt this exact flavor.",
            },
            {
                "step": 3,
                "modality": "self-compassion",
                "text": "Kindness line: what would you tell a friend in the same spot — say it to yourself.",
            },
            {
                "step": 4,
                "modality": "CBT",
                "text": "If guilt: one repair action. If shame: one belonging action (reach out, group, Nate).",
            },
        ],
        "nate_prompts": [
            "Is this shame or guilt? Help me sort it and pick one repair or belonging step.",
            "Talk to me like a compassionate coach, not a critic.",
            "I spiraled into “I am the problem” — CBT + self-compassion with me.",
        ],
    },
    {
        "topic_key": "anxiety_exposure_ladder",
        "title": "Anxiety exposure ladder: graded steps instead of white-knuckle leaps",
        "domain": "cbt",
        "modalities": ["CBT", "exposure"],
        "psychoeducation": (
            "Exposure-based CBT reduces avoidance by facing feared cues in graded steps while "
            "prevention of safety behaviors lets learning occur. Education only — severe trauma "
            "or panic disorder work belongs with a licensed clinician."
        ),
        "techniques": [
            {
                "step": 1,
                "modality": "CBT",
                "text": "Name the avoided situation and rate fear 0–100.",
            },
            {
                "step": 2,
                "modality": "CBT",
                "text": "Build a 5-rung ladder from easiest to hardest versions.",
            },
            {
                "step": 3,
                "modality": "CBT",
                "text": "Pick rung 1; stay until fear drops ~50% or 15 minutes — no full escape.",
            },
            {
                "step": 4,
                "modality": "CBT",
                "text": "Drop one safety behavior (phone checking, excessive reassurance) during the rung.",
            },
        ],
        "nate_prompts": [
            "Build an exposure ladder for this fear: ___",
            "Coach me through rung 1 without letting me escape early.",
            "What safety behaviors am I using that keep the fear alive?",
        ],
    },
]


def curriculum_by_key(topic_key: str) -> Optional[Dict[str, Any]]:
    key = (topic_key or "").strip().lower()
    for item in CLINICAL_CURRICULUM:
        if item["topic_key"] == key:
            return item
    return None


def match_curriculum(topic: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Resolve curriculum row from topic_key, title keywords, or domain."""
    if not topic:
        return None
    hit = curriculum_by_key(str(topic.get("topic_key") or ""))
    if hit:
        return hit
    blob = f"{topic.get('title') or ''} {topic.get('topic_key') or ''} {topic.get('domain') or ''}".lower()
    for item in CLINICAL_CURRICULUM:
        if item["topic_key"].replace("_", " ") in blob:
            return item
        for mod in item.get("modalities") or []:
            m = str(mod).lower()
            if len(m) >= 3 and m in blob and item["domain"] in blob:
                return item
    # modality keyword soft match
    for item in CLINICAL_CURRICULUM:
        for token in (item["topic_key"].split("_")[:2]):
            if token and token in blob and token not in ("and", "the", "for"):
                # require a modality cue
                if any(str(m).lower() in blob for m in item.get("modalities") or []):
                    return item
    domain = (topic.get("domain") or "").lower()
    for item in CLINICAL_CURRICULUM:
        if item["domain"] == domain:
            return item
    return None


def curriculum_as_candidates() -> List[Dict[str, Any]]:
    """High-score candidates for the topic pool."""
    out: List[Dict[str, Any]] = []
    for i, item in enumerate(CLINICAL_CURRICULUM):
        out.append(
            {
                "topic_key": item["topic_key"],
                "title": item["title"],
                "seasonal_window": None,
                "domain": item["domain"],
                "headline": "",
                "angle": "",
                "rationale": "clinical_curriculum",
                "clinical_boost": 1.0,
                "curriculum_index": i,
                "psychoeducation": item["psychoeducation"],
                "modalities": list(item.get("modalities") or []),
            }
        )
    return out
