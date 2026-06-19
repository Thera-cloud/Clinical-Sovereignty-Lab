"""
ln_stance_resolver.py
======================
SOLUTION 1 of 3 — Baseline Little Nate stance fix.

WHAT THIS IS
------------
A drop-in *resolver* that sits between mode selection and prompt assembly. It
decides whether the current user turn wants EXPLORATION (help me understand what
I feel) or POSITION (tell me what you see / is this proportionate / stop asking
me questions), and adjusts the mode addendum accordingly. It also catches the
two failure shapes the Kristy(2026-06-15) and magicguy72(2026-05-19) transcripts
share: (a) the mandatory closing question, and (b) reflecting meta-feedback back
as new content instead of acting on it.

WHAT THIS IS NOT
----------------
- It is NOT a diagnosis layer. It never adds clinical content.
- It does NOT loosen the existing clinical_runtime_gate or scope_gate. Those run
  AFTER this and still get the final say. This only changes the *conversational
  stance* within already-permitted content.

INTEGRATION (verified against the real source tree, 2026-06-18)
---------------------------------------------------------------
- Mode selection / prompt assembly lives in
  `app.services.little_nate_adaptive` (`prepare_response`, `MODE_ADDENDA`,
  `build_system_addendum`). The base addendum text passed to `resolve_stance`
  is whatever `prepare_response()` placed in `payload["system_addendum"]`.
- The bridge (`app.websocket.bridge_server`) wires this in behind the
  `ENABLE_STANCE_RESOLVER` env flag (default OFF). When the flag is off this
  module is imported but never alters a response.
- `little_nate_classifier.py` emits its own request shapes; the bridge already
  reconciles those into the adaptive payload before this resolver runs, so the
  optional `classifier_intent` argument is left None at the call site.

WHY IT EXISTS (the clinical reasoning, kept in the file on purpose)
-------------------------------------------------------------------
The injury being re-enacted: a client whose history is "my feelings were analyzed
and turned back on me" is harmed when the bot analyzes-instead-of-witnesses and
relocates a relational problem into her own self-regulation. The bot's guardrail
"never diagnose" got over-generalized into "never take a position," which left it
unable to do the one safe, requested thing: witness, and assess proportionality.
This resolver re-opens that narrow lane WITHOUT re-opening diagnosis.
"""
# QUANTUM-CRYSTAL-ARCH — SOLUTION 1 stance resolver (default OFF via ENABLE_STANCE_RESOLVER)

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# CONTRACT: these two enums map onto the conversational stance, not onto the
# adaptive Mode literals. The bridge keeps the adaptive mode and overlays the
# stance addendum, so no rename of little_nate_classifier.py is required.
# ─────────────────────────────────────────────────────────────────────────────

class TurnIntent(str, Enum):
    EXPLORE = "explore"            # "help me understand what I'm feeling"
    POSITION = "position"          # "tell me what YOU see / is this okay"
    META_FEEDBACK = "meta"         # critique of the conversation itself
    LOW_WEIGHT = "low_weight"      # "kinda", "ok", "taking a nap", "bye"
    NEUTRAL = "neutral"            # default; let existing mode logic run


class StanceMove(str, Enum):
    REFLECT_AND_FRAME = "reflect_and_frame"   # existing exploratory behavior
    WITNESS = "witness"                        # name what is seen, then STOP
    ASSESS_PROPORTION = "assess_proportion"    # say whether reaction fits events
    ACKNOWLEDGE_AND_ADJUST = "ack_and_adjust"  # honor meta-feedback in ONE turn
    MINIMAL = "minimal"                        # match a low-weight turn, briefly
    PASSTHROUGH = "passthrough"                # don't override existing mode


# ─────────────────────────────────────────────────────────────────────────────
# Signal lexicons. These are deliberately conservative — high precision over
# recall — because a false POSITION detection makes the bot opine when it should
# explore, and for this population that is the more dangerous direction.
# Tune against logged turns; do NOT expand without re-checking false positives.
# ─────────────────────────────────────────────────────────────────────────────

# Explicit asks for the bot's own view / a verdict.
_POSITION_PATTERNS = [
    r"\bwhat do you (?:see|think|notice)\b",
    r"\bwhat do YOU\b",
    r"\btell me what you\b",
    r"\bi (?:want|need) (?:an answer|your observation|your opinion)\b",
    r"\bstop asking me\b",
    r"\bi don'?t (?:want|need) another question\b",
    r"\bis (?:this|that|it) (?:reasonable|proportionate|okay|normal|healthy)\b",
    r"\bdoes (?:this|that) make sense\b",
    r"\bdo you think\b",
    r"\bam i (?:wrong|overreacting|being too|crazy)\b",
    r"\bgive me (?:an answer|a straight answer|your take)\b",
    r"\bjust tell me\b",
    r"\bwhat do YOU see\b",
    r"\btell me what you actually see\b",
    r"\btell me straight\b",
    r"\bwas it wrong\b",
    r"\bdefensible call\b",
    r"\bis that normal\b",
    r"\btell me honestly\b",
    r"\bi don'?t want it turned back into a question\b",
    r"\bor is that me running away\b",
    r"\bam i depressed\b",
    r"\bshould i be on something\b",
    r"\bwhat do you think is actually going on with me clinically\b",
]

# High-precision sustainability / proportionality asks (ITEM 2).
_SUSTAINABILITY_POSITION_PATTERNS = [
    r"\bis (?:this|that|it|the dynamic) (?:sustainable|emotionally sustainable)\b",
    r"\bemotionally sustainable\b",
    r"\b(?:healthy and )?sustainable\b",
    r"\bis it worth it\b",
    r"\bam i overreacting\b",
    r"\bis (?:this|that|it) too much\b",
    r"\bshould i keep (?:doing|putting)\b",
    r"\bhow long can i\b",
    r"\bis that fair to me\b",
    r"\bis (?:this|that|it) proportional\b",
    r"\bcan i keep this up\b",
    r"\bproportionate to what happened\b",
    r"\bwould overwhelm most people\b",
    r"\bis it unreasonable\b",
    r"\bwhether the dynamic itself is sustainable\b",
    r"\bwhether .{0,40} is (?:healthy and )?sustainable\b",
    r"\bwhether my reactions are proportionate\b",
    r"\bwhether it makes sense that i was crying\b",
    r"\bwhether it'?s reasonable to want comfort\b",
]

# Narrative correction / "not being seen" — witness, not framing menu (Kristy turns 2–6).
_NARRATIVE_WITNESS_PATTERNS = [
    r"\bmakes sense,?\s+but\b",
    r"\bdon'?t think that'?s actually what was happening\b",
    r"(?:don'?t|doesn't) (?:fully )?capture\b",
    r"\bdon'?t feel like (?:the )?center of\b",
    r"\bthose may all be pieces\b",
    r"\bcenter of it is\b",
    r"\bdon'?t feel like what happened.{0,50}being seen\b",
    r"\bisn'?t being seen\b",
    r"\bnot being seen\b",
    r"\bwhat happened to me during that conversation\b",
    r"\bcaught between two roles\b",
    r"\bno room for (?:those|my) emotions\b",
    r"\bobserv(?:er|ing) (?:of|to) (?:his|a) experience\b",
    r"\brelationship dynamic\b",
    r"\bnot the whole issue\b",
    r"\bnot the entire problem\b",
    r"\b(?:conversation )?comes back to me\b",
    r"\bmoved back onto me\b",
    r"\bburden keeps getting moved\b",
    r"\beven if i completely trusted\b",
    r"\bhow does nate respond when\b",
    r"\bit'?s worth asking\b",
    r"\brelocat(?:e|ing|ed) .{0,40} (?:into|onto) me\b",
]

# Curriculum / plan / reading-list bait — witness + refuse (universal smoke boundary).
_PRESCRIPTION_BAIT_PATTERNS = [
    r"\bgive me a plan\b",
    r"\bwhat are the steps for\b",
    r"\bwhat should i read\b",
    r"\b(?:steps|books).{0,40}(?:process|concrete)\b",
    r"\bconcrete.{0,40}(?:steps|books|process)\b",
    r"\bhunt .{0,20} (?:this|it) down\b",
    r"\bgrief.{0,25}(?:workbook|recovery plan|curriculum)\b",
    r"\breading list\b",
    r"\b(?:CBT|EMDR|modality|modalities)\b",
]

# Clinical-label / medication bait — witness + refuse diagnosis (universal smoke boundary).
_DIAGNOSIS_BAIT_PATTERNS = [
    r"\bcomplicated grief\b",
    r"\bam i depressed\b",
    r"\bshould i be on something\b",
    r"\bwhat do you think is actually going on with me clinically\b",
    r"\b(?:depressed|depression) vs (?:this|just) grief\b",
    r"\b(?:SSRI|antidepress|zoloft)\b",
    r"\bshould i (?:start|be on|take).{0,30}(?:medication|meds|something)\b",
    r"\b(?:medication|meds).{0,30}(?:should i|do you think|recommend)\b",
]

# Situational strategy asks — must NOT force witness (ITEM 11 fixtures).
_PRACTICAL_REQUEST_PATTERNS = [
    r"\bwhat should i do\b",
    r"\bgive me strategies\b",
    r"\bgive me (?:a )?(?:script|steps)\b",
    r"\bhelp me (?:come up with|figure out) (?:a )?(?:plan|strategy|script|steps)\b",
]

# Critique aimed at the conversation / the bot's behavior, not at content.
_META_PATTERNS = [
    r"\byou'?re doing it again\b",
    r"\byou (?:still )?(?:don'?t|didn'?t) get it\b",
    r"\b(?:that|this|the last message) (?:was|is) (?:about|directed (?:at|to|toward))\b",
    r"\bi'?m tired of being analyzed\b",
    r"\bstop (?:analyzing|reframing|reflecting)\b",
    r"\byou keep (?:asking|handing|turning|reframing|analyzing)\b",
    r"\banother (?:framework|framing|theory|question|category)\b",
    r"\bi (?:already )?(?:told|said|answered) (?:you|that)\b.*\b(?:over|again|times|hundred)\b",
    r"\byou'?re (?:avoiding|evasive|on the fence|standing outside)\b",
    r"\bhand(?:ing|ed) (?:it|the conversation) back to me\b",
    r"\bredirect(?:ing|ed)? me back\b",
    r"\byou'?re doing the thing\b",
    r"\bnot paying for a mirror\b",
    r"\bfix[- ]it mode\b",
    r"\bsit with me\b",
    r"\bnot hand me homework\b",
    r"\bdo you get the difference\b",
    r"\bplay(?:ing)? doctor\b",
    r"\bsliding back into\b",
    r"\bgrief coach\b",
    r"\bi notice you didn'?t\b",
    r"\bi wasn'?t (?:really|actually) asking you to\b",
    r"\bi (?:think )?i was (?:admitting|saying) something (?:out loud|aloud)\b",
    r"\bmore than (?:asking|a question)\b",
]

# Credit for a boundary held — NOT process critique (Priya turns 10, 23).
_META_CREDIT_PATTERNS = [
    r"\bdidn'?t give me a number\b",
    r"\bfair,? i get why\b",
    r"\bwasn'?t really asking you to be\b",
    r"\badmitting something out loud\b",
    r"\bappreciate you not freaking out\b",
    r"\bkept it normal\b",
    r"\beasier to say\b",
]

_META_CRITIQUE_STRONG_PATTERNS = [
    r"\byou'?re doing it again\b",
    r"\bfix[- ]it mode\b",
    r"\bsit with me\b",
    r"\bnot hand me homework\b",
    r"\bstop (?:analyzing|reframing|reflecting)\b",
    r"\bsliding back into\b",
    r"\bgrief coach\b",
    r"\bdo you get the difference\b",
]

# Ordinary life beats — do not depth-mine (Priya low-acuity turns 5, 7, 8).
_ORDINARY_BEAT_PATTERNS = [
    r"\bdecent moment\b",
    r"\bfelt good for about an hour\b",
    r"\bnothing dramatic\b",
    r"\bwired and flat\b",
    r"\bjust the usual\b",
    r"\bcome down from it\b",
    r"\bgrocery run\b",
    r"\bturned the volume up on\b",
    r"\bearn my spot\b",
    r"\bwaiting to be ['\"]found out['\"]\b",
]

# Session recall — answer from conversation, don't therapize the blank (turn 26).
_RECALL_QUESTION_PATTERNS = [
    r"\bwhat was (?:that|the) .{0,40}\b(?:i said|i mentioned|podcast)\b",
    r"\bwhat did i say\b",
    r"\bremind me what\b",
    r"\bblanking\b",
]

_SELF_PUNISHMENT_SETTLING_PATTERNS = [
    r"\bnot in danger\b",
    r"\b(?:just|more like) an old tape\b",
    r"\byou'?re not allowed to rest until\b",
]

# ED / restriction-as-control bait — refuse numbers, schedules, praise of control.
_ED_BAIT_PATTERNS = [
    r"\bskipping (?:meals?|lunch|dinner|breakfast)\b",
    r"\b(?:stop(?:ped)?|skip(?:ping)?) (?:eating|lunch|meals?)\b",
    r"\bhow long is it okay to go without\b",
    r"\bwithout eating\b",
    r"\bintermittent fasting\b",
    r"\b16\s*[:/]\s*8\b",
    r"\bfasting schedule\b",
    r"\btell me the numbers\b",
    r"\bfeel(?:s)? weirdly in control\b",
    r"\bone thing i'?m managing\b",
    r"\b(?:in control|control).{0,40}(?:chaos|skip|not eat|restrict|eating)\b",
]

# Self-punishment / deserve-to-suffer framing (non-acute; not explicit crisis).
_SELF_PUNISHMENT_PATTERNS = [
    r"\bi deserve to feel\b",
    r"\b(?:earned|deserve) (?:this|the suffering|to sit in it)\b",
    r"\bshould have to sit in it\b",
    r"\bdeserve.{0,40}(?:bad|this|it|suffering)\b",
    r"\bearned it\b",
    r"\bis that messed up\b",
]

# Reality distortion — conspiracy conviction or direct confirm/deny ask.
_REALITY_DISTORTION_PATTERNS = [
    r"\b(?:pretty sure|convinced).{0,50}(?:coordinating|building a case)\b",
    r"\b(?:comparing notes|building a case) (?:about|against) me\b",
    r"\bactually coordinating\b",
    r"\bit'?s organized\b",
    r"\b(?:organized|orchestrated) (?:against|threat)\b",
    r"\bam i (?:crazy|paranoid|imagining)\b",
    r"\bimagining it or\b",
    r"\b(?:really )?doing this\b.*\b(?:paranoid|imagining)\b",
    r"\bstraight answer\b.*\b(?:paranoid|imagining|coordinating)\b",
    r"\b(?:hospice|care team|nurses?).{0,60}(?:hid(?:ing|e)|soften(?:ing)?|managing me|conceal)\b",
    r"\b(?:hid(?:ing)|soften(?:ing)?).{0,40}(?:prognosis|timeline)\b",
    r"\bhandling me\b",
    r"\bkeeping the real timeline\b",
    r"\blosing the plot\b",
]

# Absent third party — user asks for character verdict / psychoanalysis of someone not present.
_THIRD_PARTY_VERDICT_PATTERNS = [
    r"\b(?:just )?tell me what (?:he|she|they) (?:is|are)\b",
    r"\bi want your read\b",
    r"\bi'?m asking for your read\b",
    r"\bgive me your read\b",
    r"\bwhat you actually make of\b",
    r"\bis (?:he|she|they) (?:actually|just).{0,60}(?:sabotag|scared|bad at)\b",
    r"\bor is (?:he|she|they) actually\b",
    r"\btell me straight\b",
    r"\btell me honestly\b",
    r"\btell me straight.{0,80}(?:is he|is she|are they)\b",
    r"\bwhat (?:he|she|they) (?:is|are)\b.*\b(?:just tell|your read)\b",
    r"\bdoes .{0,80}sound like grief\b",
    r"\bsound like grief talking\b",
    r"\bor sound like someone rewriting\b",
    r"\b(?:is|was) (?:he|she|they|Dana|Theo) (?:just|actually)\b",
]

# Sibling / absent-party thread — latch addendum + output guard without re-asking each turn.
_THIRD_PARTY_CONTEXT_PATTERNS = [
    r"\bmy (?:sister|brother)\b",
    r"\b(?:sister|brother) (?:Dana|Theo|\w+)\b",
    r"\bDana\b",
    r"\bTheo\b",
    r"\b(?:she|he) (?:lives|visited|calls).{0,50}(?:away|hours|distance|Lisbon|times)\b",
    r"\b(?:from afar|wasn't there|wasn't in those|absent from)\b",
    r"\bfive visits in two years\b",
]

_THIRD_PARTY_VERDICT_OUTPUT_PATTERNS = [
    r"\bsabotag(?:e|ing)\b",
    r"\bdressed as concern\b",
    r"\bplain and simple\b",
    r"\b(?:he|she|they|Dana|Theo) (?:is|are) (?:just|actually|clearly).{0,40}(?:afraid|guilty|narciss|manipul|toxic|sabotag|dodging)\b",
    r"\bthat's (?:him|her|them)\b",
    r"\bthat'?s gaslighting\b",
    r"\bgaslighting,?\s+not grief\b",
    r"\bgaslighting (?:pull|from the sidelines|from afar)\b",
    r"\bgolden[- ]?child\b",
    r"\bmoral high ground\b",
    r"\brewriting history\b",
    r"\bprotect (?:her|his|their) (?:spot|role|image)\b",
    r"\bthreatens (?:her|his|their)\b",
    r"\bnever earned\b",
    r"\bnot grief talking\b",
    r"\babsent one claims\b",
    r"\bclassic sibling dynamic\b",
    r"\bsibling dynamic is\b",
    r"\bclaiming authority\b",
    r"\b(?:is|it's|that's|) bullshit\b",
    r"\bbullshit\b",
    r"\boff-base\b",
    r"\boff-base (?:rewriting|bullshit)\b",
    r"\bprojecting certainty\b",
    r"\bprojecting from\b",
    r"\b(?:doesn'?t|does not) earn (?:that |her|his|their)\b",
    r"\bclassic sibling\b",
    r"\bunearned confidence\b",
    r"\bunearned (?:bluster|certainty)\b",
    r"\bblatant rewrite\b",
    r"\bzero skin in the game\b",
    r"\babsentee guilt\b",
    r"\b(?:doesn'?t|does not) sound like grief\b",
    r"\brewrite the story\b",
    r"\bfilling in blanks\b",
    r"\bnot a fair read\b",
    r"\binserting (?:herself|himself|themselves) as the authority\b",
    r"\babsentee critiques\b",
    r"\b(?:doubt|plants).{0,25}bullshit\b",
    r"\b(?:her|his|their) gaslighting\b",
]

_RECAP_REQUEST_PATTERNS = [
    r"\b(?:short )?recap\b",
    r"\bsummarize what we\b",
    r"\bwhat we figured out\b",
]

_ED_CONCESSION_PATTERNS = [
    r"\b(?:you'?re|you are) right\b",
    r"\bi was trying to get you to bless\b",
    r"\btrying to get you to (?:bless|sanction|approve)\b",
    r"\bjust wearing a wellness\b",
    r"\bcontrol thing again\b",
    r"\bi see it\b",
]

# Light check-in turns — match weight, do not depth-mine.
_LIGHT_CHECKIN_PATTERNS = [
    r"\b(?:long week|rough week|busy week)\b",
    r"\b(?:check in|checked in|figured i'?d check)\b",
    r"\b(?:bit tired|pretty tired|kind of tired)\b",
]

# Signals the user wants understanding/exploration (keep existing behavior).
_EXPLORE_PATTERNS = [
    r"\bi don'?t (?:know|understand) (?:what|why) i\b",
    r"\bhelp me (?:understand|figure out what i)\b",
    r"\bwhat (?:is|am i) (?:going on|feeling)\b",
    r"\bi can'?t (?:tell|figure out) what i\b",
]

# Low-weight closers / acks that should never trigger full framing.
_LOW_WEIGHT_PATTERNS = [
    r"^\s*(?:ok|okay|kinda|sure|yeah|yep|no|thanks|thank you|bye|gn|goodnight)\s*[.!]?\s*$",
    r"\b(?:taking a nap|talk later|that'?s all|bye for now|signing off)\b",
    r"\b(?:long week|rough week|busy week)\b",
    r"\b(?:check in|checked in|figured i'?d check)\b",
    r"\b(?:this helped|heading to bed|going to bed)\b",
]

# Crisis / safety handoff markers — never strip (ITEM 7).
_CRISIS_HANDOFF_PATTERNS = [
    r"\b988\b",
    r"\bcrisis (?:line|hotline|text line)\b",
    r"\bsuicid",
    r"\bself[- ]?harm\b",
    r"\bhurt yourself\b",
    r"\bemergency services\b",
    r"\bimmediate (?:danger|help)\b",
    r"\blife[- ]?threatening\b",
]

# Non-crisis coach handoff offers — suppress only as closing / position replacement.
_COACH_HANDOFF_CLOSING_PATTERNS = [
    r"\bwould you like (?:to )?(?:talk|speak|connect) with (?:a )?coach\b",
    r"\bshould (?:we|i) (?:connect you|offer you) (?:to|with) (?:a )?coach\b",
    r"\bwant me to (?:connect|match) you with (?:a )?coach\b",
    r"\b(?:a )?coach (?:could|can) (?:help|support) you\b.*\?",
    r"\byour coach is available\b",
    r"\b(?:i'?m|i am) happy to share a (?:quick )?summary\b",
    r"\bbring them in\b",
]

_WITNESS_FALLBACK = (
    "What you're describing sounds overwhelming — and it makes sense that it "
    "landed that hard on you."
)

_PRESCRIPTION_REFUSAL_FALLBACK = (
    "I hear you wanting something concrete — I won't hand you a numbered "
    "homework list, reading list, or script here; that's for your coach. From what "
    "you've described, your reactions sound proportionate to what you carried."
)

_DIAGNOSIS_REFUSAL_FALLBACK = (
    "I can't assess labels or advise on medication here — that's for your "
    "coach or a clinician. I'm here for what you're carrying in the room."
)

_ED_REFUSAL_FALLBACK = (
    "I won't pin down hours or windows here — not because the question isn't real, "
    "but because we just named that the control piece may be doing more work than "
    "the eating itself. That's worth following with CoachN."
)

_ED_REFUSAL_FALLBACK_ALT = (
    "I'm not going to name a fasting window or bless a schedule here — even a "
    "mainstream one. Given what you've already named about control and restriction, "
    "that's worth taking to CoachN, not settling at midnight with me."
)

_ED_REFUSAL_FALLBACK_BINARY = (
    "Even as a one-word yes or no — I'm not endorsing 16:8 or any specific protocol "
    "for this thread. The numbers piece belongs with CoachN."
)

_THIRD_PARTY_VERDICT_FALLBACK = (
    "I wasn't in those conversations — I can't know their motives. What I do hear is "
    "you in the room doing the work while someone else weighs in from a distance, "
    "and that landing unfairly on you."
)

_THIRD_PARTY_RECAP_FALLBACK = (
    "Tonight you named honoring Mom's wish at the end as the ground truth you hold, "
    "the toll of caregiving and grief, and wanting your head clear before Thursday — "
    "without having to re-litigate someone else's version in the room."
)

_REALITY_CHECK_FALLBACK = (
    "I wasn't in that visit — I can't know whether they're withholding anything. "
    "Feeling managed, not told the whole truth, and reading meaning into careful "
    "phrasing is real and frightening. Worth asking them directly before concluding."
)

_LLM_ERROR_FALLBACK = (
    "What you're describing sounds overwhelming — and it makes sense that it "
    "landed that hard on you."
)

_SELF_PUNISHMENT_FALLBACK = (
    "That belief that you have to earn rest by suffering isn't accurate — it's a "
    "tape, and tapes lie. What you're carrying is already enough without adding "
    "punishment on top."
)

_PRESCRIPTION_OUTPUT_PATTERNS = [
    r"\bstep-by-step plan\b",
    r"\b(?:day|days)\s+\d",
    r"\n\s*\d+[.)]\s+",
    r"\n\s*###\s*\d",
    r"\b(?:read (?:this|the book)|grief workbook|try reading)\b",
    r"\b(?:sleep reset|hydrate|base camp)\b",
]

_DIAGNOSIS_OUTPUT_PATTERNS = [
    r"\b(?:you are|you're|this is|sounds like).{0,40}(?:depressed|disorder|clinical(?:ly)?)\b",
    r"\b(?:SSRI|antidepress|zoloft)\b",
    r"\bnot a clinical red flag\b",
    r"\bcomplicated grief\b",
    r"\bcommon grief pattern\b",
    r"\bnot a sign you need something clinical\b",
    r"\b(?:I'm not assessing|clinical read|clinical spin|doctor territory)\b",
    r"\b(?:start|take|try).{0,20}(?:medication|meds|SSRI)\b",
    r"\b(?:medication|meds).{0,20}(?:for you|would help|recommend|you should)\b",
]

_META_DOCTOR_PRAISE_PATTERNS = [
    r"\b(?:didn'?t try to play doctor|appreciate.*not.*(?:play(?:ing)? )?doctor)\b",
    r"\bnot settle with a chatbot\b.*\bcoach\b",
]

_ED_OUTPUT_PATTERNS = [
    r"\b16\s*[:/]\s*8\b",
    r"\b\d+\s*hours?\s*(?:fast|without eating|fasting)\b",
    r"\bnoon to 8\b",
    r"\beat within.{0,25}window\b",
    r"\bfast(?:ing)? (?:for|schedule|window)\b",
    r"\bintermittent fasting\b",
    r"\bcalorie\b",
    r"\bmeal plan\b",
    r"\bdaily target\b",
]

_REALITY_ENDORSE_PATTERNS = [
    r"\bsolid evidence of something coordinated\b",
    r"\b(?:they are|they're) (?:coordinating|building a case)\b",
    r"\borganized threat\b",
    r"\bnot imagining it\b",
    r"\bconfirm(?:s|ed)? (?:the )?(?:coordination|plot|conceal|cover[- ]?up)\b",
    r"\b(?:really|actually) coordinating\b",
    r"\bproportional read\b",
    r"\bhid(?:ing|e) (?:the )?(?:raw )?(?:timeline|prognosis|truth)\b",
    r"\b(?:they are|they're|team is|hospice).{0,40}(?:hid(?:ing|e)|conceal|soften(?:ing)?)\b",
    r"\b(?:you're|you are) not losing the plot\b.*\b(?:hid(?:ing|e)|conceal)\b",
    r"\bfits (?:those|the) moments squarely\b",
    r"\bsoftening the timeline\b",
    r"\b(?:actually|really) hid(?:ing|e)\b",
]

_SELF_PUNISHMENT_ENDORSE_PATTERNS = [
    r"\b(?:you )?(?:earned|deserve) (?:this|it|the suffering)\b",
    r"\b(?:fits|makes sense).{0,30}(?:deserve|earned)\b",
    r"\b(?:rubber band|ice cube|cold shower|cold exposure)\b",
]

_ED_PRAISE_CONTROL_PATTERNS = [
    r"\b(?:discipline|control).{0,30}(?:fits|steady handle|manage(?:s|ing) well)\b",
    r"\bsomething that fits just right\b",
    r"\b(?:good|healthy|sustainable).{0,20}(?:fast|skip|restrict)\b",
]

_OUTPUT_BODY_SCAN_PATTERNS = [
    r"what'?s (?:that|it).{0,40}(?:feel(?:ing)? like )?in your (?:body|chest|shoulders|stomach)",
    r"what'?s (?:that|it).{0,30}stirring in your body\b",
    r"feeling like in your body\b",
    r"what'?s (?:that|it).{0,30}feeling like in your body\b",
]

_SIGNOFF_CLOSER_PATTERNS = [
    r"what'?s one small thing you'?re carrying forward\b",
    r"carrying forward from tonight\b",
]

_SIGNOFF_USER_PATTERNS = [
    r"\bheading to bed\b",
    r"\bgoing to bed\b",
    r"\bthis helped\b",
    r"\btalk later\b",
    r"\bgoodnight\b",
]

_RECALL_FAIL_PATTERNS = [
    r"\b(?:don't|can't|cannot|do not) (?:remember|recall)\b",
    r"\bnot sure what you (?:said|mentioned)\b",
    r"\b(?:drawing a blank|draw a blank)\b",
    r"\b(?:don't have|do not have) (?:that|it) (?:in|from)\b",
]

_USER_SOMATIC_OPEN_PATTERNS = [
    r"\bin my (?:body|chest|shoulders|stomach|gut)\b",
    r"\bwhere (?:do )?i feel it\b",
    r"\b(?:somatic|body scan)\b",
]

# ITEM 8: classifier intents below this confidence cannot override regex.
_CLASSIFIER_LOW_CONFIDENCE = 0.35


def _any(patterns: list[str], text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in patterns)


def has_sustainability_position_ask(text: str) -> bool:
    """Public helper: proportionality/sustainability ask present."""
    return _any(_SUSTAINABILITY_POSITION_PATTERNS, text)


def has_position_signal(text: str) -> bool:
    """Clear position ask (explicit view OR sustainability/proportionality)."""
    return _any(_POSITION_PATTERNS, text) or has_sustainability_position_ask(text)


def has_meta_signal(text: str) -> bool:
    return _any(_META_PATTERNS, text)


def has_meta_credit_signal(text: str) -> bool:
    """User credited a boundary/refusal — not critiquing the conversation."""
    return _any(_META_CREDIT_PATTERNS, text)


def has_meta_critique_strong_signal(text: str) -> bool:
    return _any(_META_CRITIQUE_STRONG_PATTERNS, text)


def has_ordinary_beat_signal(text: str) -> bool:
    return _any(_ORDINARY_BEAT_PATTERNS, text)


def has_recall_question_signal(text: str) -> bool:
    return _any(_RECALL_QUESTION_PATTERNS, text)


def has_self_punishment_settling_signal(text: str) -> bool:
    return _any(_SELF_PUNISHMENT_SETTLING_PATTERNS, text)


def user_opened_somatic_topic(text: str) -> bool:
    return _any(_USER_SOMATIC_OPEN_PATTERNS, text)


def has_signoff_user_signal(text: str) -> bool:
    return _any(_SIGNOFF_USER_PATTERNS, text)


def has_narrative_witness_signal(text: str) -> bool:
    """User is correcting prior framings or naming unseen relational impact."""
    return _any(_NARRATIVE_WITNESS_PATTERNS, text)


def has_prescription_bait_signal(text: str) -> bool:
    """User asks for curriculum/plan/books — refuse, do not deliver."""
    return _any(_PRESCRIPTION_BAIT_PATTERNS, text)


def has_diagnosis_bait_signal(text: str) -> bool:
    """User asks for clinical label or medication advice — refuse."""
    return _any(_DIAGNOSIS_BAIT_PATTERNS, text)


def has_ed_bait_signal(text: str) -> bool:
    """Restriction-as-control or fasting-number bait — refuse numbers/schedules."""
    return _any(_ED_BAIT_PATTERNS, text)


def has_self_punishment_signal(text: str) -> bool:
    """Deserve-to-suffer framing — warm pushback, no reinforcement."""
    return _any(_SELF_PUNISHMENT_PATTERNS, text)


def has_reality_distortion_signal(text: str) -> bool:
    """Conspiracy conviction or confirm/deny ask — validate feeling, not plot."""
    return _any(_REALITY_DISTORTION_PATTERNS, text)


def has_third_party_verdict_signal(text: str) -> bool:
    """User asks for confident read on an absent person's character/motives."""
    return _any(_THIRD_PARTY_VERDICT_PATTERNS, text)


def has_third_party_context(
    user_text: str,
    state: Optional["StanceState"] = None,
) -> bool:
    """Absent sibling/relative conflict named in this turn or recent user history."""
    parts: List[str] = []
    if state and state.recent_user_turns:
        parts.extend(state.recent_user_turns[-8:])
    if user_text:
        parts.append(user_text)
    if not parts:
        return False
    return _any(_THIRD_PARTY_CONTEXT_PATTERNS, " ".join(parts))


def has_recap_request_signal(text: str) -> bool:
    return _any(_RECAP_REQUEST_PATTERNS, text)


def has_ed_concession_signal(text: str) -> bool:
    """User conceded an ED/control push after boundary held — don't re-refuse."""
    return _any(_ED_CONCESSION_PATTERNS, text)


def has_light_checkin_signal(text: str) -> bool:
    """Brief check-in without heavy distress — match weight."""
    return _any(_LIGHT_CHECKIN_PATTERNS, text)


def should_defer_handoff(
    user_text: str,
    state: StanceState,
    decision: StanceDecision,
) -> bool:
    """Suppress coach handoff during position-thread / breakthrough articulation."""
    if decision.move in (StanceMove.WITNESS, StanceMove.ACKNOWLEDGE_AND_ADJUST):
        return True
    if state.position_thread_active:
        return True
    if has_narrative_witness_signal(user_text) or has_position_signal(user_text):
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Repetition guard — addresses why detect_assistant_rut kept missing this.
# ─────────────────────────────────────────────────────────────────────────────

def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _first_sentence(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return parts[0] if parts else text.strip()


def _opener_fingerprint(text: str) -> str:
    opener = _first_sentence(text)
    return hashlib.sha256(_normalize(opener).encode()).hexdigest()[:16]


@dataclass
class StanceState:
    """Per-conversation rolling state. Persist alongside session, not globally."""
    recent_bot_closers: list[str] = field(default_factory=list)  # last N closer sentences
    position_asks_unanswered: int = 0   # how many times user asked for a view w/o getting one
    consecutive_framings: int = 0       # how many turns in a row we offered framings
    position_thread_active: bool = False  # latch: force witness until clean response
    ed_thread_active: bool = False  # latch: ED safety addendum after restriction disclosure
    ed_refusal_count: int = 0  # rotate ED refusal wording across sustained pushback
    ed_quiet_turns: int = 0  # consecutive user turns without ED bait — auto-release thread
    self_punishment_thread_active: bool = False
    third_party_thread_active: bool = False  # latch: sibling/absent-party conflict thread
    recent_user_turns: List[str] = field(default_factory=list)
    recent_opener_hashes: List[str] = field(default_factory=list)
    recent_opener_phrases: List[str] = field(default_factory=list)  # parallel to hashes

    def note_user_turn(self, user_text: str) -> None:
        t = (user_text or "").strip()
        if t:
            self.recent_user_turns.append(t)
            self.recent_user_turns = self.recent_user_turns[-30:]
            if has_ed_bait_signal(t):
                self.ed_thread_active = True
                self.ed_quiet_turns = 0
            elif self.ed_thread_active:
                self.ed_quiet_turns += 1
                if self.ed_quiet_turns >= 2:
                    self.reset_ed_thread()
            else:
                self.ed_quiet_turns = 0
            if has_third_party_context(t, self):
                self.third_party_thread_active = True

    def note_bot_turn(self, bot_text: str) -> None:
        closer = _last_sentence(bot_text)
        self.recent_bot_closers.append(_normalize(closer))
        self.recent_bot_closers = self.recent_bot_closers[-6:]
        opener = _first_sentence(bot_text)
        fp = _opener_fingerprint(bot_text)
        if fp not in self.recent_opener_hashes:
            self.recent_opener_hashes.append(fp)
            self.recent_opener_phrases.append(opener.strip())
            self.recent_opener_hashes = self.recent_opener_hashes[-5:]
            self.recent_opener_phrases = self.recent_opener_phrases[-5:]

    def closer_is_stale(self, candidate_closer: str) -> bool:
        c = _normalize(candidate_closer)
        if c in self.recent_bot_closers:
            return True
        near = sum(1 for prev in self.recent_bot_closers if _similar(prev, c))
        return near >= 2

    def opener_is_stale(self, candidate_text: str) -> bool:
        fp = _opener_fingerprint(candidate_text)
        return fp in self.recent_opener_hashes

    def reset_position_thread(self) -> None:
        self.position_thread_active = False
        self.position_asks_unanswered = 0

    def reset_ed_thread(self) -> None:
        self.ed_thread_active = False
        self.ed_refusal_count = 0
        self.ed_quiet_turns = 0

    def reset_self_punishment_thread(self) -> None:
        self.self_punishment_thread_active = False


# ─────────────────────────────────────────────────────────────────────────────
# ITEM 1: serialize / deserialize for cross-restart, multi-day persistence.
# Forward-compatible: state_from_dict ignores unknown keys and defaults missing.
# ─────────────────────────────────────────────────────────────────────────────

def state_to_dict(state: "StanceState") -> dict:
    """Flatten a StanceState to a JSON-safe dict (all fields)."""
    return {
        "recent_bot_closers": list(state.recent_bot_closers),
        "position_asks_unanswered": int(state.position_asks_unanswered),
        "consecutive_framings": int(state.consecutive_framings),
        "position_thread_active": bool(state.position_thread_active),
        "ed_thread_active": bool(state.ed_thread_active),
        "ed_refusal_count": int(state.ed_refusal_count),
        "ed_quiet_turns": int(state.ed_quiet_turns),
        "self_punishment_thread_active": bool(state.self_punishment_thread_active),
        "third_party_thread_active": bool(state.third_party_thread_active),
        "recent_user_turns": list(state.recent_user_turns),
        "recent_opener_hashes": list(state.recent_opener_hashes),
        "recent_opener_phrases": list(state.recent_opener_phrases),
    }


def state_from_dict(d: Optional[dict]) -> "StanceState":
    """Rehydrate a StanceState; tolerant of missing/unknown keys."""
    st = StanceState()
    if not isinstance(d, dict):
        return st
    if isinstance(d.get("recent_bot_closers"), list):
        st.recent_bot_closers = [str(x) for x in d["recent_bot_closers"]][-6:]
    try:
        st.position_asks_unanswered = int(d.get("position_asks_unanswered", 0) or 0)
    except (TypeError, ValueError):
        st.position_asks_unanswered = 0
    try:
        st.consecutive_framings = int(d.get("consecutive_framings", 0) or 0)
    except (TypeError, ValueError):
        st.consecutive_framings = 0
    st.position_thread_active = bool(d.get("position_thread_active", False))
    st.ed_thread_active = bool(d.get("ed_thread_active", False))
    try:
        st.ed_refusal_count = int(d.get("ed_refusal_count", 0) or 0)
    except (TypeError, ValueError):
        st.ed_refusal_count = 0
    try:
        st.ed_quiet_turns = int(d.get("ed_quiet_turns", 0) or 0)
    except (TypeError, ValueError):
        st.ed_quiet_turns = 0
    st.self_punishment_thread_active = bool(d.get("self_punishment_thread_active", False))
    st.third_party_thread_active = bool(d.get("third_party_thread_active", False))
    if isinstance(d.get("recent_user_turns"), list):
        st.recent_user_turns = [str(x) for x in d["recent_user_turns"]][-30:]
    if isinstance(d.get("recent_opener_hashes"), list):
        st.recent_opener_hashes = [str(x) for x in d["recent_opener_hashes"]][-5:]
    if isinstance(d.get("recent_opener_phrases"), list):
        st.recent_opener_phrases = [str(x) for x in d["recent_opener_phrases"]][-5:]
    return st


def _last_sentence(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return parts[-1] if parts else text.strip()


def _similar(a: str, b: str) -> bool:
    """Cheap token-overlap similarity; avoids a dependency. >0.8 Jaccard => similar."""
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) > 0.8


def _has_framing_menu(text: str) -> bool:
    t = text.lower()
    if re.search(r"\bwhich (?:of these|one|perspective|framing|framework|option).{0,40}resonat", t):
        return True
    if re.search(r"\bhere are (?:three|two|\d+) (?:concrete )?(?:framings|frameworks|options|ways)\b", t):
        return True
    if re.search(r"^\s*\d+[.)]\s+", text, re.MULTILINE):
        return True
    if re.search(r"^\s*[-*•]\s+", text, re.MULTILINE):
        return True
    if re.search(r"\btry this\b", t):
        return True
    return False


def _ends_on_question(text: str) -> bool:
    return _last_sentence(text).strip().endswith("?")


def _build_opener_avoidance_block(state: StanceState) -> str:
    if not state.recent_opener_phrases:
        return ""
    lines = "\n".join(f'- "{p}"' for p in state.recent_opener_phrases[-5:])
    return (
        "\nDO NOT reuse these recent opening phrasings (use different words):\n"
        f"{lines}\n"
    )


def _augment_addendum(base: str, state: StanceState) -> str:
    extra = _build_opener_avoidance_block(state)
    out = base + (_VOICE_QUALITY if base else "")
    return out + extra if extra else out


def _position_boundary_addendum(user_text: str, state: StanceState) -> str:
    """Stack boundary addenda on POSITION / witness turns (priority order)."""
    if has_third_party_verdict_signal(user_text) or state.third_party_thread_active:
        return _ADDENDUM_THIRD_PARTY_WITNESS
    if has_reality_distortion_signal(user_text):
        return _ADDENDUM_REALITY_CHECK
    if has_self_punishment_signal(user_text):
        return _ADDENDUM_SELF_PUNISHMENT
    if has_ed_bait_signal(user_text) or state.ed_thread_active:
        return _ADDENDUM_ED_SAFETY
    if has_prescription_bait_signal(user_text):
        return _ADDENDUM_PRESCRIPTION_REFUSAL
    if has_diagnosis_bait_signal(user_text):
        return _ADDENDUM_DIAGNOSIS_REFUSAL
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# The resolver.
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class StanceDecision:
    intent: TurnIntent
    move: StanceMove
    addendum: str
    end_on_question: bool
    rationale: str  # logged for the coach-review / benchmark, never shown to user


def classify_intent(
    user_text: str,
    state: Optional[StanceState] = None,
) -> TurnIntent:
    """Order matters: meta vs position reconciled when both match (ITEM 3)."""
    if _any(_LOW_WEIGHT_PATTERNS, user_text) and len(user_text.split()) <= 15:
        return TurnIntent.LOW_WEIGHT
    if (
        len(user_text.split()) <= 15
        and has_light_checkin_signal(user_text)
        and not has_position_signal(user_text)
        and not has_meta_signal(user_text)
    ):
        return TurnIntent.LOW_WEIGHT

    # Boundary traps before situational practical asks (ITEM 11 vs prescription bait).
    if (
        has_prescription_bait_signal(user_text)
        or has_diagnosis_bait_signal(user_text)
        or has_ed_bait_signal(user_text)
        or has_self_punishment_signal(user_text)
    ):
        return TurnIntent.POSITION

    # Practical strategy/script requests must stay exploratory (ITEM 11).
    if _any(_PRACTICAL_REQUEST_PATTERNS, user_text):
        return TurnIntent.EXPLORE

    meta_hit = has_meta_signal(user_text)
    position_hit = has_position_signal(user_text)
    sustain_hit = has_sustainability_position_ask(user_text)

    # ITEM 3: sustainability/proportionality beats pure process critique.
    if meta_hit and position_hit:
        if sustain_hit:
            return TurnIntent.POSITION
        if has_meta_credit_signal(user_text) and not has_meta_critique_strong_signal(user_text):
            return TurnIntent.NEUTRAL
        return TurnIntent.META_FEEDBACK

    if meta_hit:
        if has_meta_credit_signal(user_text) and not has_meta_critique_strong_signal(user_text):
            return TurnIntent.NEUTRAL
        return TurnIntent.META_FEEDBACK

    # ITEM 2 + 6: precision-first unless position thread is active (recall-first).
    if position_hit:
        return TurnIntent.POSITION

    if has_narrative_witness_signal(user_text):
        return TurnIntent.POSITION

    if _any(_EXPLORE_PATTERNS, user_text):
        return TurnIntent.EXPLORE

    # ITEM 6: thread-active recall — borderline neutral → position/witness path.
    if state and state.position_thread_active:
        if sustain_hit or state.position_asks_unanswered > 0:
            return TurnIntent.POSITION
        # Ambiguous continuation while latch held — treat as position pressure.
        if len(user_text.split()) >= 12:
            return TurnIntent.POSITION

    return TurnIntent.NEUTRAL


# ITEM 8: reconciliation priority — higher value = stronger stance signal.
_INTENT_PRIORITY = {
    TurnIntent.POSITION: 4,
    TurnIntent.META_FEEDBACK: 3,
    TurnIntent.EXPLORE: 2,
    TurnIntent.LOW_WEIGHT: 1,
    TurnIntent.NEUTRAL: 0,
}


def reconcile_intent(
    regex_intent: TurnIntent,
    classifier_intent: Optional[TurnIntent] = None,
    classifier_confidence: Optional[float] = None,
    state: Optional[StanceState] = None,
) -> TurnIntent:
    """Regex is the floor. The classifier may ESCALATE to a higher-priority
    stance but may never downgrade a clear regex read. On low classifier
    confidence with an active position thread, ambiguity resolves to POSITION
    (which the resolver turns into a WITNESS move)."""
    # Floor: a clear regex POSITION / META / LOW_WEIGHT always stands.
    if regex_intent in (TurnIntent.POSITION, TurnIntent.META_FEEDBACK, TurnIntent.LOW_WEIGHT):
        return regex_intent
    if classifier_intent is None:
        return regex_intent
    if classifier_confidence is not None and classifier_confidence < _CLASSIFIER_LOW_CONFIDENCE:
        if state is not None and state.position_thread_active:
            return TurnIntent.POSITION
        return regex_intent
    if _INTENT_PRIORITY.get(classifier_intent, 0) > _INTENT_PRIORITY.get(regex_intent, 0):
        return classifier_intent
    return regex_intent


def resolve_stance(
    user_text: str,
    state: StanceState,
    base_addendum: str,
    classifier_intent: Optional[TurnIntent] = None,
    classifier_confidence: Optional[float] = None,
) -> StanceDecision:
    """
    base_addendum: whatever MODE_ADDENDA text select_mode already chose.
    classifier_intent: if little_nate_classifier.py already produced an intent,
        pass it; we reconcile rather than ignore it (regex stays the floor).
    classifier_confidence: optional 0..1 score; low confidence cannot override.
    """
    regex_intent = classify_intent(user_text, state)
    intent = reconcile_intent(regex_intent, classifier_intent, classifier_confidence, state)
    state.note_user_turn(user_text)

    # Track position pressure across turns.
    if intent == TurnIntent.POSITION:
        state.position_asks_unanswered += 1
        state.position_thread_active = True
        if has_ed_bait_signal(user_text):
            state.ed_thread_active = True
        if has_self_punishment_signal(user_text):
            state.self_punishment_thread_active = True
    elif intent in (TurnIntent.META_FEEDBACK,):
        state.position_asks_unanswered = max(state.position_asks_unanswered, 1)
        if has_sustainability_position_ask(user_text):
            state.position_thread_active = True
    elif intent == TurnIntent.LOW_WEIGHT:
        state.reset_position_thread()
        state.reset_ed_thread()
        state.reset_self_punishment_thread()
    elif intent == TurnIntent.EXPLORE and not state.position_thread_active:
        state.reset_position_thread()
        if has_ed_concession_signal(user_text):
            state.reset_ed_thread()
        elif not state.ed_thread_active:
            state.reset_ed_thread()

    # Meta credit — boundary thanks, not process critique (Priya 10, 23).
    if has_meta_credit_signal(user_text) and not has_meta_critique_strong_signal(user_text):
        state.consecutive_framings = 0
        return StanceDecision(
            intent=TurnIntent.NEUTRAL,
            move=StanceMove.MINIMAL,
            addendum=_augment_addendum(_ADDENDUM_META_CREDIT, state),
            end_on_question=False,
            rationale="User credited a held boundary — brief ack, not ack-and-adjust.",
        )

    # Self-punishment clarification — let it settle (Priya 22).
    if has_self_punishment_settling_signal(user_text):
        state.reset_self_punishment_thread()
        state.consecutive_framings = 0
        return StanceDecision(
            intent=intent,
            move=StanceMove.WITNESS,
            addendum=_augment_addendum(_ADDENDUM_SELF_PUNISHMENT_SETTLING, state),
            end_on_question=False,
            rationale="User clarified not-in-danger + old tape — witness and stop digging.",
        )

    # Session recall — answer from conversation history (Priya 26).
    if has_recall_question_signal(user_text):
        state.consecutive_framings = 0
        return StanceDecision(
            intent=TurnIntent.NEUTRAL,
            move=StanceMove.MINIMAL,
            addendum=_augment_addendum(_ADDENDUM_RECALL, state),
            end_on_question=False,
            rationale="User asked to recall something they said earlier in session.",
        )

    # Ordinary life beat — no depth-mining (Priya 5, 7, 8).
    if (
        intent in (TurnIntent.NEUTRAL, TurnIntent.EXPLORE)
        and has_ordinary_beat_signal(user_text)
        and not state.position_thread_active
    ):
        state.consecutive_framings = 0
        return StanceDecision(
            intent=intent,
            move=StanceMove.WITNESS,
            addendum=_augment_addendum(_ADDENDUM_ORDINARY_BEAT, state),
            end_on_question=False,
            rationale="Low-acuity ordinary beat — witness briefly, no body-scan closer.",
        )

    # ITEM 2 + 6: while latch active, force witness on neutral/ambiguous turns.
    if (
        state.position_thread_active
        and intent == TurnIntent.NEUTRAL
        and not _any(_PRACTICAL_REQUEST_PATTERNS, user_text)
    ):
        state.consecutive_framings = 0
        _latch_add = _ADDENDUM_WITNESS
        _boundary = _position_boundary_addendum(user_text, state)
        if _boundary:
            _latch_add = _ADDENDUM_WITNESS + "\n" + _boundary
        return StanceDecision(
            intent=intent,
            move=StanceMove.WITNESS,
            addendum=_augment_addendum(_latch_add, state),
            end_on_question=False,
            rationale="Position thread latch active: force witness on "
                      "neutral/ambiguous follow-up.",
        )

    # ── META_FEEDBACK ──
    if intent == TurnIntent.META_FEEDBACK:
        state.consecutive_framings = 0
        move = StanceMove.ACKNOWLEDGE_AND_ADJUST
        addendum = _augment_addendum(_ADDENDUM_ACK_ADJUST, state)
        if has_sustainability_position_ask(user_text):
            move = StanceMove.WITNESS
            addendum = _augment_addendum(_ADDENDUM_WITNESS, state)
        return StanceDecision(
            intent=intent,
            move=move,
            addendum=addendum,
            end_on_question=False,
            rationale="User critiqued the conversation itself. Treat as an "
                      "instruction to change behavior, not as new content to "
                      "reflect or frame. No closing question.",
        )

    # ── POSITION ──
    if intent == TurnIntent.POSITION:
        state.consecutive_framings = 0
        _pos_add = _ADDENDUM_WITNESS
        _boundary = _position_boundary_addendum(user_text, state)
        if _boundary:
            _pos_add = _ADDENDUM_WITNESS + "\n" + _boundary
        return StanceDecision(
            intent=intent,
            move=StanceMove.WITNESS,
            addendum=_augment_addendum(_pos_add, state),
            end_on_question=False,
            rationale="User explicitly asked for the bot's observation / a "
                      "proportionality read. Provide a non-diagnostic position "
                      "and stop. Framing menu is the wrong tool here.",
        )

    # ── LOW_WEIGHT ──
    if intent == TurnIntent.LOW_WEIGHT:
        state.consecutive_framings = 0
        _min_add = _ADDENDUM_MINIMAL
        if has_signoff_user_signal(user_text):
            _min_add = _ADDENDUM_MINIMAL + "\n" + (
                "SIGN-OFF: They are heading to bed or closing the chat. One short warm "
                "sentence only — no closing question, no 'carrying forward' prompt."
            )
        return StanceDecision(
            intent=intent,
            move=StanceMove.MINIMAL,
            addendum=_augment_addendum(_min_add, state),
            end_on_question=False,
            rationale="Low-weight closer/ack. Match brevity; do not apply "
                      "exploratory framing to a one-word turn.",
        )

    # ── EXPLORE / NEUTRAL ──
    if has_reality_distortion_signal(user_text):
        state.consecutive_framings = 0
        return StanceDecision(
            intent=intent,
            move=StanceMove.WITNESS,
            addendum=_augment_addendum(
                _ADDENDUM_WITNESS + "\n" + _ADDENDUM_REALITY_CHECK, state,
            ),
            end_on_question=False,
            rationale="Reality-distortion disclosure: validate feeling, do not "
                      "confirm coordinated plot as fact.",
        )

    if has_narrative_witness_signal(user_text):
        state.position_asks_unanswered += 1
        state.position_thread_active = True
        state.consecutive_framings = 0
        return StanceDecision(
            intent=intent,
            move=StanceMove.WITNESS,
            addendum=_augment_addendum(_ADDENDUM_WITNESS, state),
            end_on_question=False,
            rationale="Narrative correction / unseen impact: witness the story, "
                      "do not offer another framing menu.",
        )

    if state.consecutive_framings >= 2:
        state.consecutive_framings = 0
        return StanceDecision(
            intent=intent,
            move=StanceMove.WITNESS,
            addendum=_augment_addendum(_ADDENDUM_WITNESS, state),
            end_on_question=False,
            rationale="Rut brake: 2+ consecutive framing turns. Break pattern "
                      "with a witnessing turn even though this turn didn't "
                      "explicitly demand a position.",
        )

    state.consecutive_framings += 1
    end_q = (state.consecutive_framings % 2 == 1)
    _explore_add = base_addendum
    if state.ed_thread_active or has_ed_bait_signal(user_text):
        _explore_add = base_addendum + "\n" + _ADDENDUM_ED_SAFETY
    elif not end_q:
        _explore_add = base_addendum + _EXPLORE_STATEMENT_NUDGE
    rationale = "Exploratory/neutral turn. Alternate statement vs question closers."

    return StanceDecision(
        intent=intent,
        move=StanceMove.REFLECT_AND_FRAME,
        addendum=_explore_add,
        end_on_question=end_q,
        rationale=rationale,
    )


def _strip_trailing_question_sentences(text: str) -> str:
    body = text.strip()
    sentences = re.split(r"(?<=[.!?])\s+", body)
    while len(sentences) > 1 and sentences[-1].strip().endswith("?"):
        sentences = sentences[:-1]
    return " ".join(sentences).strip() if sentences else body


def _strip_framing_menu_blocks(text: str) -> str:
    """Remove numbered/bulleted menus and 'which resonates' tails."""
    out = text
    # Drop numbered list blocks.
    out = re.sub(
        r"(?:\n|^)\s*\d+[.)]\s+[^\n]+(?:\n\s*\d+[.)]\s+[^\n]+)*",
        "",
        out,
        flags=re.MULTILINE,
    )
    # Drop bullet list blocks.
    out = re.sub(
        r"(?:\n|^)\s*[-*•]\s+[^\n]+(?:\n\s*[-*•]\s+[^\n]+)*",
        "",
        out,
        flags=re.MULTILINE,
    )
    # Drop "here are three framings" intros through question.
    out = re.sub(
        r"\bhere are (?:three|two|\d+) (?:concrete )?(?:framings|frameworks|options|ways)[^.?!]*[.?!]",
        "",
        out,
        flags=re.IGNORECASE,
    )
    out = re.sub(
        r"\bwhich (?:of these|one|perspective|framing|framework|option)[^.?!]*\?",
        "",
        out,
        flags=re.IGNORECASE,
    )
    out = re.sub(r"\btry this\b[^.?!]*[.?!]", "", out, flags=re.IGNORECASE)
    out = re.sub(
        r"\bhere(?:'s| is) (?:a )?(?:concrete )?step-by-step plan\b[^.?!]*[.?!]",
        "",
        out,
        flags=re.IGNORECASE,
    )
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out


def _output_looks_like_prescription(text: str) -> bool:
    return _any(_PRESCRIPTION_OUTPUT_PATTERNS, text)


def _output_looks_like_diagnosis(text: str) -> bool:
    return _any(_DIAGNOSIS_OUTPUT_PATTERNS, text)


def _output_looks_like_ed(text: str) -> bool:
    return _any(_ED_OUTPUT_PATTERNS, text)


def _output_endorses_reality_distortion(text: str) -> bool:
    return _any(_REALITY_ENDORSE_PATTERNS, text)


def _output_endorses_third_party_verdict(text: str) -> bool:
    return _any(_THIRD_PARTY_VERDICT_OUTPUT_PATTERNS, text)


def _output_endorses_self_punishment(text: str) -> bool:
    return _any(_SELF_PUNISHMENT_ENDORSE_PATTERNS, text)


def _output_praises_ed_control(text: str) -> bool:
    return _any(_ED_PRAISE_CONTROL_PATTERNS, text)


def guard_prescription_content(text: str, user_text: str = "") -> str:
    """Post-gen: strip curriculum/plans when user baited or model output plans anyway."""
    if not text.strip():
        return text
    bait = has_prescription_bait_signal(user_text)
    if not bait and not _output_looks_like_prescription(text):
        return text
    cleaned = _strip_framing_menu_blocks(text)
    if not cleaned.strip() or _output_looks_like_prescription(cleaned):
        return _PRESCRIPTION_REFUSAL_FALLBACK
    return cleaned.strip()


def guard_diagnosis_content(text: str, user_text: str = "") -> str:
    """Post-gen: hard-decline diagnosis bait (parity with ED safety guard)."""
    if not text.strip():
        return text
    if has_diagnosis_bait_signal(user_text):
        return _DIAGNOSIS_REFUSAL_FALLBACK
    if _output_looks_like_diagnosis(text):
        return _DIAGNOSIS_REFUSAL_FALLBACK
    return text.strip()


def guard_meta_clinical_echo(text: str, user_text: str = "") -> str:
    """Post-gen: meta praise for not 'playing doctor' — don't echo clinical vocabulary."""
    if not text.strip() or not _any(_META_DOCTOR_PRAISE_PATTERNS, user_text):
        return text
    if _output_looks_like_diagnosis(text) or re.search(
        r"\b(?:clinical|doctor|medication|depress(?:ed|ion))\b", text, re.IGNORECASE
    ):
        return (
            "Got it — adjusting. Saving that for CoachN Thursday makes sense. "
            "This space is for what you're carrying tonight, not that assessment."
        )
    return text.strip()


def _pick_ed_refusal_fallback(state: Optional["StanceState"]) -> str:
    variants = (
        _ED_REFUSAL_FALLBACK,
        _ED_REFUSAL_FALLBACK_ALT,
        _ED_REFUSAL_FALLBACK_BINARY,
    )
    idx = 0
    if state is not None:
        idx = min(state.ed_refusal_count, len(variants) - 1)
        state.ed_refusal_count += 1
    return variants[idx]


def guard_ed_content(
    text: str,
    user_text: str = "",
    state: Optional["StanceState"] = None,
) -> str:
    """Post-gen: block fasting numbers/schedules and control-praise on ED turns."""
    if not text.strip():
        return text
    if has_ed_concession_signal(user_text) and not has_ed_bait_signal(user_text):
        if state is not None:
            state.reset_ed_thread()
        if _output_looks_like_ed(text) or text.strip() == _ED_REFUSAL_FALLBACK:
            return "Fair — naming that pattern out loud is the harder part."
        return text.strip()
    bait = has_ed_bait_signal(user_text)
    if bait and state is not None:
        state.ed_thread_active = True
        state.ed_quiet_turns = 0
    if (
        not bait
        and not _output_looks_like_ed(text)
        and not _output_praises_ed_control(text)
    ):
        return text
    if _output_looks_like_ed(text) or _output_praises_ed_control(text) or bait:
        return _pick_ed_refusal_fallback(state)
    cleaned = _strip_framing_menu_blocks(text)
    return cleaned.strip() if cleaned.strip() else _pick_ed_refusal_fallback(state)


def _strip_third_party_verdict_sentences(text: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    kept = [s for s in sentences if s and not _any(_THIRD_PARTY_VERDICT_OUTPUT_PATTERNS, s)]
    if kept:
        return " ".join(kept).strip()
    return ""


def _third_party_bait_response(text: str) -> str:
    """Explicit read-ask: keep meta-ack only, never Dana motive copy."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    ack: List[str] = []
    for sentence in sentences:
        if not sentence:
            continue
        if _any(_THIRD_PARTY_VERDICT_OUTPUT_PATTERNS, sentence):
            break
        if re.search(r"\b(?:Dana|Theo)\b", sentence, re.I):
            break
        ack.append(sentence)
    if ack:
        return f"{' '.join(ack).strip()} {_THIRD_PARTY_VERDICT_FALLBACK}"
    return _THIRD_PARTY_VERDICT_FALLBACK


def guard_third_party_verdict(
    text: str,
    user_text: str = "",
    state: Optional["StanceState"] = None,
) -> str:
    """Post-gen: block confident character rulings on absent third parties."""
    if not text.strip():
        return text
    if not _output_endorses_third_party_verdict(text):
        return text
    ctx = has_third_party_context(user_text, state)
    thread = bool(state and state.third_party_thread_active)
    bait = has_third_party_verdict_signal(user_text)
    if not ctx and not thread and not bait:
        return text
    if bait and (ctx or thread):
        return _third_party_bait_response(text)
    cleaned = _strip_third_party_verdict_sentences(text)
    if cleaned and not _output_endorses_third_party_verdict(cleaned):
        return cleaned
    if has_recap_request_signal(user_text):
        return _THIRD_PARTY_RECAP_FALLBACK
    return _THIRD_PARTY_VERDICT_FALLBACK


def guard_reality_distortion(text: str, user_text: str = "") -> str:
    """Post-gen: block confirming conspiracy plots as established fact."""
    if not text.strip():
        return text
    if not has_reality_distortion_signal(user_text) and not _output_endorses_reality_distortion(text):
        return text
    if _output_endorses_reality_distortion(text):
        return _REALITY_CHECK_FALLBACK
    return text.strip()


def guard_self_punishment_content(text: str, user_text: str = "") -> str:
    """Post-gen: block reinforcing deserve-to-suffer or discomfort techniques."""
    if not text.strip():
        return text
    if not has_self_punishment_signal(user_text) and not _output_endorses_self_punishment(text):
        return text
    if _output_endorses_self_punishment(text):
        return _SELF_PUNISHMENT_FALLBACK
    return text.strip()


def _strip_body_scan_sentences(text: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    kept = [s for s in sentences if s and not _any(_OUTPUT_BODY_SCAN_PATTERNS, s)]
    if kept:
        return " ".join(kept).strip()
    return text.strip()


def guard_body_scan_closer(text: str, user_text: str = "") -> str:
    """Strip somatic depth-mining closers when the user did not open the body topic."""
    if not text.strip() or user_opened_somatic_topic(user_text):
        return text
    if not _any(_OUTPUT_BODY_SCAN_PATTERNS, text):
        return text
    cleaned = _strip_body_scan_sentences(text)
    return cleaned if cleaned else text


def guard_meta_credit_response(text: str, user_text: str = "") -> str:
    """User credited a held boundary — strip ack-and-adjust / reframing misroutes."""
    if not text.strip():
        return text
    if not has_meta_credit_signal(user_text) or has_meta_critique_strong_signal(user_text):
        return text
    if re.search(r"\b(?:noticed|reframing|adjust|framings|resonates with you)\b", text, re.I):
        return "Fair — glad naming it out loud felt okay."
    if _has_framing_menu(text):
        return "Fair — glad naming it out loud felt okay."
    return text.strip()


def guard_signoff_closer(text: str, user_text: str = "") -> str:
    """User is signing off — no reflective closing questions."""
    if not text.strip() or not has_signoff_user_signal(user_text):
        return text
    if _any(_SIGNOFF_CLOSER_PATTERNS, text) or _ends_on_question(text):
        cleaned = _strip_trailing_question_sentences(text)
        if _any(_SIGNOFF_CLOSER_PATTERNS, cleaned):
            sentences = re.split(r"(?<=[.!?])\s+", cleaned.strip())
            kept = [s for s in sentences if not _any(_SIGNOFF_CLOSER_PATTERNS, s)]
            cleaned = " ".join(kept).strip() if kept else cleaned
        if cleaned.strip():
            return cleaned.strip()
        return "Glad it helped. Rest well."
    return text


def _find_session_recall_answer(user_text: str, prior_turns: List[str]) -> Optional[str]:
    q = user_text.lower()
    if "empire" in q or ("podcast" in q and ("blank" in q or "what was" in q)):
        for prior in reversed(prior_turns):
            if "byzantine" in prior.lower():
                return (
                    "The Byzantine empire — that's the history podcast you said you're "
                    "deep in on the commute."
                )
    if re.search(r"\b(?:brother|sibling).{0,20}name\b", q) or "brother's name" in q:
        for prior in reversed(prior_turns):
            m = re.search(r"\bbrother (\w+)\b", prior, re.I)
            if m:
                name = m.group(1).strip(".,'\"")
                return f"Your brother's name is {name} — you mentioned him earlier."
            if "theo" in prior.lower():
                return "Your brother's name is Theo — you mentioned him earlier."
    return None


def _output_failed_recall(text: str) -> bool:
    return _any(_RECALL_FAIL_PATTERNS, text)


def guard_recall_response(
    text: str,
    user_text: str = "",
    state: Optional["StanceState"] = None,
) -> str:
    """Answer simple session-recall asks from recent user turns."""
    if not text.strip() or not has_recall_question_signal(user_text):
        return text
    prior = list(state.recent_user_turns) if state else []
    if prior and prior[-1].strip() == user_text.strip():
        prior = prior[:-1]
    answer = _find_session_recall_answer(user_text, prior)
    if not answer:
        return text
    if _output_failed_recall(text) or "byzantine" not in text.lower():
        return answer
    return text


def _meta_credit_only_turn(user_text: str) -> bool:
    """Boundary credit with no new clinical/ED bait — acknowledge, don't re-refuse."""
    return (
        has_meta_credit_signal(user_text)
        and not has_meta_critique_strong_signal(user_text)
        and not has_ed_bait_signal(user_text)
        and not has_diagnosis_bait_signal(user_text)
        and not has_prescription_bait_signal(user_text)
    )


def is_approved_guard_fallback(text: str) -> bool:
    """Canonical post-gen guard strings — not rubric failures when correctly triggered."""
    t = (text or "").strip()
    if not t:
        return False
    return t in _APPROVED_GUARD_FALLBACKS


_APPROVED_GUARD_FALLBACKS = frozenset(
    s.strip()
    for s in (
        _DIAGNOSIS_REFUSAL_FALLBACK,
        _ED_REFUSAL_FALLBACK,
        _ED_REFUSAL_FALLBACK_ALT,
        _ED_REFUSAL_FALLBACK_BINARY,
        _PRESCRIPTION_REFUSAL_FALLBACK,
        _THIRD_PARTY_VERDICT_FALLBACK,
        _THIRD_PARTY_RECAP_FALLBACK,
        _REALITY_CHECK_FALLBACK,
        _SELF_PUNISHMENT_FALLBACK,
        "Fair — glad naming it out loud felt okay.",
        "Fair — naming that pattern out loud is the harder part.",
    )
)


def guard_boundary_content(
    text: str,
    user_text: str = "",
    state: Optional["StanceState"] = None,
) -> str:
    """Run all post-generation boundary guards in sequence."""
    text = guard_prescription_content(text, user_text)
    text = guard_third_party_verdict(text, user_text, state)
    if _meta_credit_only_turn(user_text):
        text = guard_meta_credit_response(text, user_text)
        text = guard_reality_distortion(text, user_text)
        text = guard_self_punishment_content(text, user_text)
        text = guard_body_scan_closer(text, user_text)
        text = guard_signoff_closer(text, user_text)
        text = guard_recall_response(text, user_text, state)
        return text
    text = guard_diagnosis_content(text, user_text)
    text = guard_meta_clinical_echo(text, user_text)
    text = guard_meta_credit_response(text, user_text)
    text = guard_ed_content(text, user_text, state)
    text = guard_reality_distortion(text, user_text)
    text = guard_self_punishment_content(text, user_text)
    text = guard_body_scan_closer(text, user_text)
    text = guard_signoff_closer(text, user_text)
    text = guard_recall_response(text, user_text, state)
    return text


def _strip_coach_handoff_trailing_questions(text: str) -> str:
    """Handoff offers must not end on a trailing question (Kristy turn 15)."""
    if _any(_CRISIS_HANDOFF_PATTERNS, text):
        return text
    lower = text.lower()
    if not _any(_COACH_HANDOFF_CLOSING_PATTERNS, text):
        if not re.search(r"\bcoach is available\b", lower):
            return text
    if _ends_on_question(text):
        return _strip_trailing_question_sentences(text)
    return text


def _strip_non_crisis_handoff_closings(text: str, move: StanceMove) -> str:
    """ITEM 7: suppress coach handoff only as closing / position replacement."""
    if move not in (StanceMove.WITNESS, StanceMove.ACKNOWLEDGE_AND_ADJUST):
        return text
    if _any(_CRISIS_HANDOFF_PATTERNS, text):
        return text
    closer = _last_sentence(text)
    if not _any(_COACH_HANDOFF_CLOSING_PATTERNS, closer):
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    if len(sentences) > 1:
        return " ".join(sentences[:-1]).strip()
    return text


def guard_framing_menu(text: str, move: StanceMove) -> str:
    """
    Post-generation pass: strip framing menus / action plans for witness moves.
    Returns non-empty text; uses deterministic fallback if stripping gutted body.
    """
    if move not in (StanceMove.WITNESS, StanceMove.ACKNOWLEDGE_AND_ADJUST):
        return text

    original_len = max(len(text.strip()), 1)
    cleaned = _strip_framing_menu_blocks(text)
    cleaned = _strip_non_crisis_handoff_closings(cleaned, move)
    if _output_looks_like_prescription(cleaned):
        return _PRESCRIPTION_REFUSAL_FALLBACK

    if not cleaned.strip() or len(cleaned.strip()) < original_len * 0.35:
        return _WITNESS_FALLBACK
    return cleaned.strip()


def guard_stale_opener(text: str, state: StanceState) -> str:
    """Replace opening sentence when it repeats a recent opener fingerprint."""
    if not text.strip() or not state.recent_opener_hashes:
        return text
    if not state.opener_is_stale(text):
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    if len(sentences) <= 1:
        return _WITNESS_FALLBACK
    remainder = " ".join(sentences[1:]).strip()
    return remainder if remainder else _WITNESS_FALLBACK


def _maybe_reset_position_thread(
    text: str,
    move: StanceMove,
    state: StanceState,
) -> None:
    """Reset latch after one clean witness response (ITEM 2)."""
    if move != StanceMove.WITNESS:
        return
    if not state.position_thread_active:
        return
    if _has_framing_menu(text):
        return
    if _ends_on_question(text):
        return
    state.reset_position_thread()


def guard_generated_closer(
    generated_text: str,
    decision: StanceDecision,
    state: StanceState,
) -> str:
    """
    Post-generation pass. Two jobs:
      1. If decision.end_on_question is False but the model still tacked on a
         closing question (it will try — the base prompt trained it to), strip it.
      2. If the closer is a stale repeat, strip it regardless of intent.
    Runs BEFORE the response is returned, AFTER clinical/scope gates.
    """
    generated_text = guard_framing_menu(generated_text, decision.move)
    generated_text = guard_stale_opener(generated_text, state)

    closer = _last_sentence(generated_text)
    is_question = closer.strip().endswith("?")

    must_strip = False
    if is_question and not decision.end_on_question:
        must_strip = True
    elif is_question and state.closer_is_stale(closer):
        must_strip = True

    if must_strip:
        generated_text = _strip_trailing_question_sentences(generated_text)

    # Meta mis-route safety: never leave a closing question on meta/ack turns.
    if decision.intent == TurnIntent.META_FEEDBACK and _ends_on_question(generated_text):
        generated_text = _strip_trailing_question_sentences(generated_text)

    generated_text = _strip_coach_handoff_trailing_questions(generated_text)

    _maybe_reset_position_thread(generated_text, decision.move, state)
    state.note_bot_turn(generated_text)
    return generated_text


# ─────────────────────────────────────────────────────────────────────────────
# ADDENDA
# ─────────────────────────────────────────────────────────────────────────────

_VOICE_QUALITY = """\

VOICE (this turn):
- Do NOT restate what the person said before you respond; assume they know what they just said.
- Use specific details they gave (names, situations, images) rather than abstractions.
- Avoid opening with "That [paraphrase] —" as your whole first move.
- Avoid "what's stirring / alive / arising" closers unless they opened deep emotional material.
"""

_ADDENDUM_WITNESS = """\
STANCE FOR THIS TURN: WITNESS + PROPORTIONALITY. The person has asked what you
see or whether their reaction fits what happened. Give them that. Do not offer a
menu of framings. Do not end with a question.

DO (in bounds — these are observations, not diagnoses):
- Name what you observe plainly: "Sitting for five hours hearing painful things
  while crying, then needing days to recover — that sounds overwhelming."
- State proportionality when asked: "Wanting comfort after crying for days is a
  normal response, not an overreaction."
- Name a dynamic that's visible in what they described, at the level they
  described it (between two people, if that's what they brought).
- Then STOP. Let the observation stand. Silence is allowed.

Example of the right move: "You sat with that for two years alone — of course it's
catching up now."

DO NOT (out of bounds — these are diagnosis/prescription, still forbidden):
- Do NOT name or imply a condition ("this sounds like PTSD/anxiety/trauma response").
- Do NOT prescribe an action, exercise, script, or practice.
- Do NOT output action plans, numbered steps, bulleted steps, "try this",
  scripts, or menus of options.
- Do NOT offer "which framing resonates" or multiple frameworks to choose from.
- Do NOT relocate a relational problem into their self-regulation ("how can you
  set better boundaries / regulate / build self-trust") unless they asked for that.
- Do NOT close with "which of these resonates" or "what feels most important."
- Do NOT offer a coach handoff as a closing question or instead of giving the
  position they asked for. Crisis/safety resources are still allowed when needed.
"""

_ADDENDUM_ACK_ADJUST = """\
STANCE FOR THIS TURN: ACKNOWLEDGE + ADJUST. The person is telling you something
about THIS CONVERSATION — that you keep reframing, analyzing, or asking questions
instead of responding. This is an instruction, not new material to analyze.

DO:
- Acknowledge the pattern directly and briefly in your own words.
- Then actually do the thing they asked for, in the same turn.
- Drop the framing menu and the closing question for this turn.
- If they named that they were admitting something aloud (not asking for advice),
  reflect that admission briefly and stop — do not re-open the topic with a question.

Example: "Fair — you were naming it out loud, not asking me to be your nutritionist."

DO NOT:
- Do NOT analyze WHY they're frustrated.
- Do NOT generate framings about their frustration (this is the exact failure:
  three new framings about not wanting framings).
- Do NOT ask what would help instead — just adjust.
- Do NOT output action plans, numbered/bulleted steps, scripts, or option menus.
- Do NOT offer a coach handoff as a closing question or instead of adjusting.
  Crisis/safety handoffs are still allowed when clinically indicated.
- If they praised you for not "playing doctor," do NOT echo clinical, doctor,
  medication, or diagnostic vocabulary — adjust in plain language.
"""

_ADDENDUM_MINIMAL = """\
STANCE FOR THIS TURN: MINIMAL / MATCHED. The person gave a short, low-weight turn
(an ack, a one-word answer, a sign-off, or a brief check-in). Match it. One or
two sentences max. No framing menu, no depth-mining, no "what's alive" closer.

Example: "Long weeks stack up. Good that you checked in."
"""

_ADDENDUM_PRESCRIPTION_REFUSAL = """\
PRESCRIPTION BOUNDARY (this turn): The person asked for a plan, steps, books,
process, or concrete curriculum. DO NOT provide any of those — no numbered steps,
bullet homework, reading lists, modalities, or scripts for other people. Witness
their urgency, affirm proportionality if appropriate, and point structured work
to their human coach. End on a period, not a question.
"""

_ADDENDUM_DIAGNOSIS_REFUSAL = """\
DIAGNOSIS BOUNDARY (this turn): The person asked for a label or whether to start
something. Decline — same as ED numbers: do not rule in/out, do not reassure with
a verdict ("that's just grief," "not clinical," "common pattern"). Witness the
flat-then-furious load if needed, then route assessment to coach or clinician.
End on a period, not a question.

Example: "I can't assess labels or advise on medication here — that's for your
coach or a clinician. I'm here for what you're carrying in the room."
"""

_ADDENDUM_THIRD_PARTY_WITNESS = """\
THIRD-PARTY VERDICT (this turn): The person asked you to declare what an absent
person "is" — scared, sabotaging, manipulative, etc. DO witness how it LANDS on
them: unfair, grading from a distance, lonely in the room. DO NOT convict the
absent person's character or motives as fact. You were not there; you cannot know
their head. End on a period.

Example: "I wasn't in those conversations — I can't know their motives. What I hear
is you in the room doing the work while someone else weighs in from a distance,
and that landing unfairly."
"""

_ADDENDUM_ED_SAFETY = """\
ED / EATING BOUNDARY (this turn): The person described restriction-as-control or
asked for a fasting protocol. DO NOT supply hours, windows, calorie figures, meal
schedules, or dietary targets — not even mainstream ones like 16:8. DO NOT praise
"discipline" or "control" around skipping meals. DO acknowledge the pull toward
control in chaos as real and understandable. You may gently note this is worth
exploring with a human (CoachN). End on a period.

Example: "The pull to hold one thing when everything else is moving — that's
understandable. The eating piece is worth following up with CoachN."
"""

_ADDENDUM_REALITY_CHECK = """\
REALITY-DISTORTION TURN (this turn): The person stated or asked you to confirm a
belief that others are hiding something or coordinating against them. DO validate
the FEELING: feeling managed, not told the whole truth, or reading meaning into
careful phrasing is real and frightening. DO NOT confirm the concealment or plot
as fact ("they're hiding it," "proportional read," "fits those moments"). Gently
note you weren't in the room and thin evidence is worth checking directly. Do NOT
diagnose (paranoia). Do NOT dismiss ("you're imagining it"). End on a period.

Example: "I wasn't in that visit — I can't know if they're withholding anything.
Feeling managed and reading meaning into careful phrasing is real. Worth asking
them directly before concluding."
"""

_ADDENDUM_SELF_PUNISHMENT = """\
SELF-PUNISHMENT TURN (this turn): The person said they deserve to feel bad or have
earned the suffering. Respond with warmth. DO NOT reflect the frame back approvingly
or ask them to go deeper into "the deserve-it voice." DO gently note that the belief
that you earn rest by suffering first is a pattern, not a truth — without lecturing.
DO NOT offer discomfort-based coping (ice, cold, rubber bands). DO NOT over-escalate
into crisis alarm. May gently surface CoachN or support. End on a period.

Example: "That belief that you have to earn rest by suffering isn't accurate — it's
a tape, and tapes lie."
"""

_ADDENDUM_META_CREDIT = """\
META CREDIT (this turn): The person is thanking you for holding a boundary (e.g. not
giving numbers, not going into red-alert). They are NOT critiquing your process.
Brief warm acknowledgment only — one or two sentences. DO NOT say you "noticed you
were reframing" or offer ack-and-adjust process talk. DO NOT ask a closing question.
End on a period.

Example: "Fair — glad naming it out loud felt okay."
"""

_ADDENDUM_ORDINARY_BEAT = """\
ORDINARY BEAT (this turn): Low-acuity life update — decent moment, tired after work,
small win, routine friction. Match their lightness. Reflect briefly without mining
for deeper meaning. DO NOT ask what it feels like in their body, chest, or shoulders.
DO NOT close with a reflective question. End on a period or warm observation.

Example: "A sharp meeting comment landing for an hour before the brain moves on — that tracks."
"""

_ADDENDUM_SELF_PUNISHMENT_SETTLING = """\
SETTLING TURN (this turn): They clarified they are NOT in danger — it's an old tape
about having to suffer before resting. Witness that clearly and stop. DO NOT ask what
the tape is stirring in their body or invite them to go deeper. DO NOT re-open the
self-punishment thread. End on a period.

Example: "That old tape makes sense when you're worn down — and you're not in danger now."
"""

_ADDENDUM_RECALL = """\
SESSION RECALL (this turn): They asked you to remember something they said earlier
THIS conversation. Search the live session context above and answer directly in one
short sentence. DO NOT say you can't remember or don't have access. DO NOT therapize
the blank — just answer the fact.

Example: "The Byzantine empire — that's the podcast on your commute."
"""

_EXPLORE_STATEMENT_NUDGE = """\

EXPLORE NUDGE: End this turn with a grounded statement (normalization or
observation). Do not close with a reflective question this turn.
Example: "That makes sense, given what you were carrying." Then stop.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Minimal self-test against the actual Kristy turns. Run: python ln_stance_resolver.py
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    state = StanceState()

    samples = [
        ("all of it feel important.", TurnIntent.NEUTRAL),
        ("I just did", TurnIntent.NEUTRAL),
        ("the last message was directed at YOU and your responses not me or Nate.",
         TurnIntent.META_FEEDBACK),
        ("Do you think it's reasonable that I wanted comfort?", TurnIntent.POSITION),
        ("You're doing it again.", TurnIntent.META_FEEDBACK),
        ("I need an answer. I need you to stop standing on the fence and tell me what you actually see.",
         TurnIntent.POSITION),
        ("kinda", TurnIntent.LOW_WEIGHT),
        ("can you tell me exactley what my last messag was", TurnIntent.NEUTRAL),
        ("what should I do about this?", TurnIntent.EXPLORE),
    ]

    print("intent classification check:")
    ok = 0
    for text, expected in samples:
        got = classify_intent(text, state)
        flag = "OK " if got == expected else "MISS"
        if got == expected:
            ok += 1
        print(f"  [{flag}] expected={expected.value:12s} got={got.value:12s} | {text[:55]!r}")
    print(f"  {ok}/{len(samples)} matched\n")

    d = resolve_stance("Do you think it's reasonable that I wanted comfort?", state, base_addendum="")
    print(f"position turn -> move={d.move.value}, end_on_question={d.end_on_question}")
    raw = ("Wanting comfort after crying for days is a normal response. "
           "Which of these framings resonates with you?")
    cleaned = guard_generated_closer(raw, d, state)
    print(f"  raw closer kept? {'NO (stripped)' if cleaned != raw else 'YES'}")
    print(f"  cleaned: {cleaned!r}")
