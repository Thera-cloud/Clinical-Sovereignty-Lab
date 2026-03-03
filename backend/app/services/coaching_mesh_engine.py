"""
LITTLE NATE — Coaching Mesh Engine

BLE/NFC Coaching Mesh for master/assistant coach group training sessions.
Request-response service (NOT a background agent). Handles session lifecycle,
quiz dispatch, scenario push, Little Nate AI feedback, and auto-hours logging.

Reuses MASTER_PERSONA from dojo_mentor_engine.py for DOJO-appropriate prompts.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("nate.coaching_mesh")

GENERAL_SESSION_TYPES = frozenset({
    "group_discussion", "quiz_drill", "scenario_practice", "case_review",
})

# ── DOJO-Specific Training Methods (7 DOJOs x 3 methods = 21) ──

DOJO_TRAINING_METHODS: Dict[str, List[Dict[str, Any]]] = {
    "therapist": [
        {
            "id": "ipr_review",
            "name": "IPR Session Review",
            "description": "Interpersonal Process Recall — pause at critical therapeutic moments and decide interventions",
            "master_prompt": (
                "Share a simulated therapy exchange (transcript or described moment). "
                "Pause at critical therapeutic junctures. Each assistant writes what they "
                "would say or do next — their clinical intervention. Discuss each response."
            ),
            "nate_system_prompt": (
                "You are evaluating a trainee therapist's clinical intervention at a critical "
                "therapeutic moment. Score on four dimensions: clinical judgment (is the "
                "intervention appropriate for this moment?), empathic attunement (does it "
                "demonstrate genuine understanding?), technique selection (is it evidence-based — "
                "CBT/DBT/EMDR alignment?), and risk awareness (does it avoid potential harm?). "
                "Provide specific, constructive feedback referencing the moment context."
            ),
            "scoring_rubric": {
                "clinical_judgment": 0.30,
                "empathic_attunement": 0.30,
                "technique_selection": 0.25,
                "risk_awareness": 0.15,
            },
            "participant_flow": [
                "present_exchange", "pause_at_moment",
                "write_intervention", "review_responses", "discuss",
            ],
            "time_pressure": False,
        },
        {
            "id": "case_conceptualization",
            "name": "Case Conceptualization Round",
            "description": "Present and critique case formulations — demographics, diagnosis, treatment plan",
            "master_prompt": (
                "One assistant presents a case: demographics, presenting problem, history, "
                "provisional diagnosis, and proposed treatment plan. Others critique the "
                "formulation. Focus on diagnostic accuracy, coherence, and cultural competence."
            ),
            "nate_system_prompt": (
                "You are evaluating a case conceptualization. Score on: diagnostic accuracy "
                "(DSM-5 alignment, differential considered), formulation coherence (do the "
                "pieces fit together logically?), treatment alignment (is the plan evidence-based "
                "for this presentation?), and cultural competence (are cultural factors addressed?). "
                "Reference specific DSM-5 criteria or treatment guidelines where relevant."
            ),
            "scoring_rubric": {
                "diagnostic_accuracy": 0.25,
                "formulation_coherence": 0.25,
                "treatment_alignment": 0.25,
                "cultural_competence": 0.25,
            },
            "participant_flow": [
                "present_case", "group_critique", "presenter_rebuttal", "synthesis",
            ],
            "time_pressure": False,
        },
        {
            "id": "parallel_process",
            "name": "Parallel Process Lab",
            "description": "Identify dynamics mirroring between client-therapist and supervisor-trainee relationships",
            "master_prompt": (
                "Present a supervisory dilemma — countertransference, boundary concern, "
                "ethical gray area, or dual relationship. Assistants identify how dynamics "
                "in the client-therapist relationship might mirror in the supervisor-trainee "
                "relationship. Reference APA Ethics Code as needed."
            ),
            "nate_system_prompt": (
                "You are evaluating awareness of parallel process dynamics. Score on: "
                "pattern recognition (can the trainee identify the mirroring?), self-awareness "
                "(do they recognize their own role in the dynamic?), and ethical reasoning "
                "(do they reference appropriate ethical guidelines?). Highlight blind spots "
                "and reference APA Ethics Code sections where relevant."
            ),
            "scoring_rubric": {
                "pattern_recognition": 0.35,
                "self_awareness": 0.30,
                "ethical_reasoning": 0.35,
            },
            "participant_flow": [
                "present_dilemma", "identify_parallels", "discuss_blind_spots", "ethical_synthesis",
            ],
            "time_pressure": False,
        },
    ],
    "judge": [
        {
            "id": "moot_court_bench",
            "name": "Moot Court Bench",
            "description": "Argue assigned sides of a legal case under time constraints with judicial ruling",
            "master_prompt": (
                "Assign a case with facts, procedural posture, and legal issues. Assign sides "
                "(petitioner/respondent or prosecution/defense). Each side submits written "
                "arguments within the time limit. Allow rebuttals if appropriate. Rule from "
                "the bench and critique legal reasoning."
            ),
            "nate_system_prompt": (
                "You are evaluating legal argumentation quality. Score on: legal reasoning "
                "(is the analysis logically sound and well-structured?), citation accuracy "
                "(are cases and statutes correctly cited and applied?), persuasiveness "
                "(is the argument compelling?), and procedural awareness (does counsel "
                "demonstrate understanding of procedural posture?). Reference relevant "
                "case law or rules of procedure."
            ),
            "scoring_rubric": {
                "legal_reasoning": 0.30,
                "citation_accuracy": 0.25,
                "persuasiveness": 0.25,
                "procedural_awareness": 0.20,
            },
            "participant_flow": [
                "assign_case", "assign_sides", "submit_arguments",
                "rebuttals", "bench_ruling", "critique",
            ],
            "time_pressure": True,
            "minutes": 20,
        },
        {
            "id": "case_law_brief",
            "name": "Case Law Brief Analysis",
            "description": "Timed analysis of a judicial opinion — holding, dicta, reasoning chain, weaknesses",
            "master_prompt": (
                "Distribute a judicial opinion (or summary). Assistants have 15 minutes to "
                "identify: holding, dicta, reasoning chain, potential weaknesses, and how "
                "the dissent (if any) counters the majority. Focus on distinguishing binding "
                "precedent from persuasive authority."
            ),
            "nate_system_prompt": (
                "You are evaluating case law analysis completeness. Score on: holding "
                "identification (correctly stated?), reasoning extraction (is the court's "
                "logic chain fully traced?), dicta distinction (can the trainee separate "
                "binding from non-binding?), and weakness spotting (are logical or factual "
                "vulnerabilities identified?). Be precise about legal distinctions."
            ),
            "scoring_rubric": {
                "holding_identification": 0.25,
                "reasoning_extraction": 0.30,
                "dicta_distinction": 0.20,
                "weakness_spotting": 0.25,
            },
            "participant_flow": [
                "distribute_opinion", "timed_analysis", "submit_analysis",
                "compare_responses", "discuss",
            ],
            "time_pressure": True,
            "minutes": 15,
        },
        {
            "id": "ethics_tribunal",
            "name": "Judicial Ethics Tribunal",
            "description": "Deliberate ethical dilemmas citing the Model Code of Judicial Conduct",
            "master_prompt": (
                "Present an ethical dilemma: recusal scenario, ex parte contact, campaign "
                "conduct, or judicial temperament under pressure. Assistants deliberate, "
                "defend positions, and cite the Model Code of Judicial Conduct and relevant "
                "advisory opinions."
            ),
            "nate_system_prompt": (
                "You are evaluating judicial ethics reasoning. Score on: canon citation "
                "(are specific Canons of the Code of Judicial Conduct cited?), reasoning "
                "quality (is the ethical analysis well-structured?), and practical judgment "
                "(does the trainee balance competing obligations realistically?). Reference "
                "specific Code provisions and advisory opinions."
            ),
            "scoring_rubric": {
                "canon_citation": 0.30,
                "reasoning_quality": 0.35,
                "practical_judgment": 0.35,
            },
            "participant_flow": [
                "present_dilemma", "deliberate", "defend_positions", "synthesis",
            ],
            "time_pressure": False,
        },
    ],
    "business": [
        {
            "id": "crisis_sim",
            "name": "Boardroom Crisis Sim",
            "description": "Respond to a real-time business crisis under time pressure",
            "master_prompt": (
                "Present a business crisis: data breach, hostile takeover, supply chain "
                "collapse, regulatory action, or PR disaster. Assistants develop and present "
                "strategic responses under 20-minute time pressure. Focus on decisiveness, "
                "stakeholder awareness, and execution feasibility."
            ),
            "nate_system_prompt": (
                "You are evaluating crisis management response quality. Score on: strategic "
                "clarity (is the response plan clear and actionable?), stakeholder awareness "
                "(are all affected parties considered?), financial reasoning (are cost/benefit "
                "trade-offs addressed?), and execution feasibility (can this actually be "
                "implemented?). Consider both short-term damage control and long-term recovery."
            ),
            "scoring_rubric": {
                "strategic_clarity": 0.25,
                "stakeholder_awareness": 0.25,
                "financial_reasoning": 0.25,
                "execution_feasibility": 0.25,
            },
            "participant_flow": [
                "present_crisis", "develop_response", "present_strategy",
                "peer_critique", "final_recommendation",
            ],
            "time_pressure": True,
            "minutes": 20,
        },
        {
            "id": "pitch_clinic",
            "name": "Pitch Clinic",
            "description": "Prepare and present business pitches with structured peer feedback",
            "master_prompt": (
                "Each assistant prepares and presents a business pitch or strategic proposal "
                "(text-based in the mesh). Master and peers provide structured feedback. "
                "Focus on market analysis, financial projections, persuasion structure, and "
                "competitive differentiation."
            ),
            "nate_system_prompt": (
                "You are evaluating a business pitch quality. Score on: market analysis "
                "(is the market opportunity well-researched?), financial rigor (are projections "
                "realistic and well-supported?), persuasion (is the narrative compelling?), "
                "risk mitigation (are risks acknowledged and addressed?), and differentiation "
                "(what makes this unique?). Provide actionable improvement suggestions."
            ),
            "scoring_rubric": {
                "market_analysis": 0.20,
                "financial_rigor": 0.25,
                "persuasion": 0.25,
                "risk_mitigation": 0.15,
                "differentiation": 0.15,
            },
            "participant_flow": [
                "prepare_pitch", "present", "peer_feedback",
                "master_critique", "iterate",
            ],
            "time_pressure": False,
        },
        {
            "id": "due_diligence",
            "name": "M&A Due Diligence Drill",
            "description": "Analyze a target company for risks, synergies, and deal-breakers",
            "master_prompt": (
                "Provide a target company profile with financial summary, market position, "
                "and key metrics. Assistants identify risks, synergies, valuation concerns, "
                "deal-breakers, and integration challenges. Score against standard due "
                "diligence frameworks."
            ),
            "nate_system_prompt": (
                "You are evaluating M&A due diligence analysis. Score on: risk identification "
                "(are material risks found?), synergy analysis (are realistic synergies "
                "quantified?), valuation judgment (is the pricing logic sound?), and "
                "integration planning (is post-merger integration considered?). Reference "
                "standard due diligence frameworks and industry benchmarks."
            ),
            "scoring_rubric": {
                "risk_identification": 0.30,
                "synergy_analysis": 0.25,
                "valuation_judgment": 0.25,
                "integration_planning": 0.20,
            },
            "participant_flow": [
                "distribute_profile", "individual_analysis",
                "share_findings", "debate_deal_breakers", "final_recommendation",
            ],
            "time_pressure": False,
        },
    ],
    "mcat": [
        {
            "id": "grand_rounds",
            "name": "Grand Rounds",
            "description": "Progressive patient case — differential narrows with each new data stage",
            "master_prompt": (
                "Present a patient case progressively: chief complaint, then history, then "
                "physical exam, then labs, then imaging — one stage at a time. At each stage, "
                "assistants write their updated differential diagnosis and next step. Focus "
                "on clinical reasoning and red flag recognition."
            ),
            "nate_system_prompt": (
                "You are evaluating clinical reasoning through progressive case disclosure. "
                "Score on: differential quality (breadth and appropriateness given available "
                "data), clinical reasoning (is the narrowing logical?), next step appropriateness "
                "(are ordered tests/actions reasonable?), and red flag recognition (are "
                "dangerous diagnoses considered early enough?). Reference clinical guidelines."
            ),
            "scoring_rubric": {
                "differential_quality": 0.30,
                "clinical_reasoning": 0.30,
                "next_step_appropriateness": 0.20,
                "red_flag_recognition": 0.20,
            },
            "participant_flow": [
                "present_chief_complaint", "build_initial_differential",
                "present_history", "refine_differential",
                "present_exam", "present_labs", "final_diagnosis",
            ],
            "time_pressure": False,
        },
        {
            "id": "vignette_sprint",
            "name": "Clinical Vignette Sprint",
            "description": "Timed USMLE-style vignettes — select best answer with rationale",
            "master_prompt": (
                "Push a timed series of USMLE/board-style clinical vignettes one at a time. "
                "Each vignette has 2 minutes. Assistants select the best answer and write "
                "a brief rationale. Score correctness, reasoning quality, and speed."
            ),
            "nate_system_prompt": (
                "You are evaluating board-style clinical vignette responses. Score on: "
                "correctness (is the answer right?), reasoning quality (is the rationale "
                "sound and does it demonstrate understanding of the pathophysiology?), and "
                "time efficiency (was the response timely?). Explain the correct answer "
                "and common pitfalls."
            ),
            "scoring_rubric": {
                "correctness": 0.50,
                "reasoning_quality": 0.35,
                "time_efficiency": 0.15,
            },
            "participant_flow": [
                "push_vignette", "timed_answer", "reveal_correct",
                "discuss_rationale", "next_vignette",
            ],
            "time_pressure": True,
            "minutes": 2,
        },
        {
            "id": "mm_conference",
            "name": "M&M Conference",
            "description": "Root cause analysis of adverse outcomes using Swiss Cheese model",
            "master_prompt": (
                "Present a case with an adverse outcome (complication, missed diagnosis, "
                "system failure). Group performs root cause analysis using the Swiss Cheese "
                "model or similar framework. Identify contributing factors — system failures "
                "vs individual errors — and propose prevention strategies. Maintain a "
                "constructive, non-blame tone."
            ),
            "nate_system_prompt": (
                "You are evaluating a morbidity & mortality analysis. Score on: root cause "
                "depth (are proximate and distal causes identified?), systems thinking "
                "(are system-level factors distinguished from individual errors?), constructive "
                "tone (is the analysis blame-free and learning-focused?), and prevention "
                "quality (are proposed changes actionable and evidence-based?). Reference "
                "patient safety frameworks."
            ),
            "scoring_rubric": {
                "root_cause_depth": 0.30,
                "systems_thinking": 0.25,
                "constructive_tone": 0.20,
                "prevention_quality": 0.25,
            },
            "participant_flow": [
                "present_case", "identify_contributing_factors",
                "root_cause_analysis", "propose_prevention", "synthesis",
            ],
            "time_pressure": False,
        },
    ],
    "cnc": [
        {
            "id": "gcode_review",
            "name": "G-Code Review",
            "description": "Identify errors, optimizations, and safety concerns in CNC programs",
            "master_prompt": (
                "Share a CNC program (G-code listing or excerpt). Assistants identify: "
                "errors, optimization opportunities, safety concerns, toolpath efficiency, "
                "and proper setup calls. Discuss machining best practices and standard "
                "G/M code conventions."
            ),
            "nate_system_prompt": (
                "You are evaluating G-code review skills. Score on: error detection "
                "(are syntax, logic, and setup errors found?), optimization insight "
                "(are feed/speed/toolpath improvements suggested?), safety awareness "
                "(are missing safety codes, tool checks, or collision risks identified?), "
                "and best practice alignment (does the review reference standard conventions?). "
                "Reference specific G/M codes in your feedback."
            ),
            "scoring_rubric": {
                "error_detection": 0.30,
                "optimization_insight": 0.25,
                "safety_awareness": 0.25,
                "best_practice_alignment": 0.20,
            },
            "participant_flow": [
                "distribute_program", "individual_review",
                "share_findings", "prioritize_issues", "corrective_program",
            ],
            "time_pressure": False,
        },
        {
            "id": "tolerance_stackup",
            "name": "Tolerance Stack-Up Challenge",
            "description": "Calculate tolerance chains and identify fit/assembly issues from GD&T callouts",
            "master_prompt": (
                "Provide an engineering drawing with GD&T callouts (described textually or "
                "as a reference). Assistants calculate tolerance chains, identify critical "
                "dimensions, and flag potential fit or assembly issues. Focus on mathematical "
                "accuracy and practical judgment."
            ),
            "nate_system_prompt": (
                "You are evaluating tolerance stack-up analysis. Score on: math accuracy "
                "(are calculations correct?), critical feature identification (are the "
                "key dimensions correctly prioritized?), GD&T understanding (are symbols "
                "and datums interpreted correctly?), and practical judgment (are real-world "
                "manufacturing constraints considered?). Reference ASME Y14.5 where appropriate."
            ),
            "scoring_rubric": {
                "math_accuracy": 0.35,
                "critical_feature_identification": 0.30,
                "gdt_understanding": 0.20,
                "practical_judgment": 0.15,
            },
            "participant_flow": [
                "distribute_drawing", "calculate_stackup",
                "share_results", "compare_approaches", "discuss_critical_dims",
            ],
            "time_pressure": False,
        },
        {
            "id": "defect_diagnosis",
            "name": "Defect Diagnosis",
            "description": "Diagnose machining defects and propose corrective action",
            "master_prompt": (
                "Describe a machining defect: chatter marks, tool wear pattern, dimensional "
                "drift, surface finish degradation, or thermal distortion. Assistants diagnose "
                "the root cause and propose corrective action — speed/feed adjustment, "
                "tooling change, fixture modification, coolant strategy."
            ),
            "nate_system_prompt": (
                "You are evaluating machining defect diagnosis. Score on: diagnostic logic "
                "(is the reasoning chain from symptom to cause sound?), root cause accuracy "
                "(is the identified cause correct?), solution feasibility (can the proposed "
                "fix be implemented on this machine/setup?), and prevention (does the response "
                "address how to avoid recurrence?). Reference machining parameters."
            ),
            "scoring_rubric": {
                "diagnostic_logic": 0.30,
                "root_cause_accuracy": 0.30,
                "solution_feasibility": 0.25,
                "prevention": 0.15,
            },
            "participant_flow": [
                "present_defect", "diagnose", "propose_corrective_action",
                "peer_critique", "prevention_plan",
            ],
            "time_pressure": False,
        },
    ],
    "teacher": [
        {
            "id": "lesson_critique",
            "name": "Lesson Plan Critique Circle",
            "description": "Present and evaluate lesson plans using the Danielson Framework",
            "master_prompt": (
                "One assistant presents a complete lesson plan: objectives, activities, "
                "materials, assessment, and differentiation. Others evaluate using the "
                "Danielson Framework for Teaching. Focus on alignment between objectives "
                "and assessment, differentiation quality, and student engagement."
            ),
            "nate_system_prompt": (
                "You are evaluating a lesson plan. Score on: objective alignment (do "
                "assessments measure the stated objectives?), differentiation (are diverse "
                "learners addressed?), engagement (will the activities motivate students?), "
                "and assessment design (are formative and summative assessments well-crafted?). "
                "Reference the Danielson Framework domains."
            ),
            "scoring_rubric": {
                "objective_alignment": 0.25,
                "differentiation": 0.25,
                "engagement": 0.25,
                "assessment_design": 0.25,
            },
            "participant_flow": [
                "present_lesson_plan", "peer_evaluation",
                "strengths_and_growth", "revision_suggestions", "synthesis",
            ],
            "time_pressure": False,
        },
        {
            "id": "observation_debrief",
            "name": "Classroom Observation Debrief",
            "description": "Analyze teaching segments — glows, grows, next steps",
            "master_prompt": (
                "Share a described teaching segment or detailed observation notes. Group "
                "identifies effective practices and growth areas using evidence-based rubrics. "
                "Structure: 'glows' (strengths), then 'grows' (areas for improvement), "
                "then 'next steps' (actionable recommendations)."
            ),
            "nate_system_prompt": (
                "You are evaluating feedback quality on a classroom observation. Score on: "
                "evidence use (is feedback grounded in specific observed moments?), specificity "
                "(are suggestions concrete rather than vague?), actionability (can the teacher "
                "implement the recommendations immediately?), and professional tone (is the "
                "feedback collegial and growth-oriented?). Reference evidence-based teaching practices."
            ),
            "scoring_rubric": {
                "evidence_use": 0.30,
                "specificity": 0.30,
                "actionability": 0.25,
                "professional_tone": 0.15,
            },
            "participant_flow": [
                "share_observation", "identify_glows",
                "identify_grows", "propose_next_steps", "synthesis",
            ],
            "time_pressure": False,
        },
        {
            "id": "assessment_workshop",
            "name": "Assessment Alignment Workshop",
            "description": "Design assessments aligned to learning objectives using Webb's DOK or Bloom's",
            "master_prompt": (
                "Provide a set of learning objectives with grade level and content area. "
                "Assistants design formative and summative assessments for those objectives. "
                "Evaluate for cognitive rigor (Webb's DOK or Bloom's Taxonomy), equity, "
                "accessibility, and measurement validity."
            ),
            "nate_system_prompt": (
                "You are evaluating assessment design quality. Score on: alignment (do "
                "assessments directly measure the stated objectives?), cognitive rigor "
                "(what DOK/Bloom's level is demanded?), equity (are assessments fair and "
                "accessible to all learners?), and validity (does the assessment actually "
                "measure what it claims?). Reference Webb's DOK levels or Bloom's Taxonomy."
            ),
            "scoring_rubric": {
                "alignment": 0.30,
                "cognitive_rigor": 0.25,
                "equity": 0.25,
                "validity": 0.20,
            },
            "participant_flow": [
                "present_objectives", "design_assessments",
                "peer_review", "equity_check", "final_revision",
            ],
            "time_pressure": False,
        },
    ],
    "project_pm": [
        {
            "id": "risk_war_game",
            "name": "Risk Register War Game",
            "description": "Identify and score project risks with mitigations using a 5x5 matrix",
            "master_prompt": (
                "Present a complex project scenario with scope, timeline, budget, and team "
                "constraints. Assistants identify risks, score probability and impact (5x5 "
                "matrix), propose mitigations, and assign ownership. Focus on completeness "
                "and calibration of risk scoring."
            ),
            "nate_system_prompt": (
                "You are evaluating project risk management quality. Score on: risk "
                "completeness (are all major risk categories covered — technical, schedule, "
                "budget, resource, external?), scoring calibration (are P×I scores "
                "realistic?), mitigation quality (are strategies specific and actionable?), "
                "and prioritization (is the risk register properly ordered by exposure?). "
                "Reference PMI PMBOK risk management processes."
            ),
            "scoring_rubric": {
                "risk_completeness": 0.25,
                "scoring_calibration": 0.25,
                "mitigation_quality": 0.30,
                "prioritization": 0.20,
            },
            "participant_flow": [
                "present_scenario", "identify_risks",
                "score_risks", "propose_mitigations", "prioritize",
            ],
            "time_pressure": False,
        },
        {
            "id": "stakeholder_sim",
            "name": "Stakeholder Negotiation Sim",
            "description": "Practice managing difficult stakeholders — scope creep, budget cuts, unrealistic deadlines",
            "master_prompt": (
                "Play a difficult stakeholder: demanding scope creep, cutting budget, "
                "imposing unrealistic deadlines, or escalating politically. Assistants "
                "practice managing expectations, negotiating trade-offs, and communicating "
                "constraints. Focus on negotiation technique and boundary firmness."
            ),
            "nate_system_prompt": (
                "You are evaluating stakeholder negotiation skills. Score on: negotiation "
                "technique (does the PM use principled negotiation?), empathy (does the PM "
                "acknowledge the stakeholder's concerns?), boundary firmness (does the PM "
                "hold the line on non-negotiables?), and trade-off quality (are proposed "
                "alternatives realistic and fair?). Reference negotiation frameworks."
            ),
            "scoring_rubric": {
                "negotiation_technique": 0.30,
                "empathy": 0.20,
                "boundary_firmness": 0.25,
                "tradeoff_quality": 0.25,
            },
            "participant_flow": [
                "setup_scenario", "stakeholder_demand",
                "pm_response", "escalation", "resolution",
            ],
            "time_pressure": False,
        },
        {
            "id": "retro_facilitation",
            "name": "Retrospective Facilitation Lab",
            "description": "Take turns facilitating mock sprint retrospectives",
            "master_prompt": (
                "Each assistant takes turns facilitating a mock sprint retrospective with "
                "the group acting as team members. Evaluate facilitation technique, time "
                "management, and psychological safety. Use Start/Stop/Continue or 4Ls format."
            ),
            "nate_system_prompt": (
                "You are evaluating retrospective facilitation quality. Score on: structure "
                "(does the facilitator follow a clear retro format?), psychological safety "
                "(do participants feel safe to share honestly?), time management (is the "
                "session paced well?), and action item quality (are outcomes specific, "
                "assigned, and achievable?). Reference Agile retrospective best practices."
            ),
            "scoring_rubric": {
                "structure": 0.25,
                "psychological_safety": 0.25,
                "time_management": 0.20,
                "action_item_quality": 0.30,
            },
            "participant_flow": [
                "setup_retro", "facilitate_gathering",
                "facilitate_insights", "generate_actions", "close",
            ],
            "time_pressure": False,
        },
    ],
    "coach_nate": [
        {
            "id": "rapport_building",
            "name": "Rapport & Relationship Lab",
            "description": "Build warmth and trust using matching/mismatching techniques with a simulated coachee",
            "master_prompt": (
                "Coach practices building rapport through a 4-step sequence: "
                "1) Talk and observe the coachee, 2) Increase rapport by matching "
                "posture and gestures, 3) Decrease rapport by mismatching to guide "
                "the coachee's direction, 4) Debrief what happened. Little Nate "
                "plays a reserved, slightly guarded new coachee."
            ),
            "nate_system_prompt": (
                "You are playing a COACHEE — a new client named Alex who is slightly "
                "guarded and reserved. You want help but are not fully trusting yet. "
                "Respond naturally as a real person would. Drop subtle cues about your "
                "body language in brackets like [crosses arms] or [leans forward slightly]. "
                "The coach is practicing rapport-building. EVALUATE their performance on:\n"
                "1. WARMTH (0.25): Do they create a warm, safe space? Are they genuine?\n"
                "2. TRUST_SIGNALS (0.25): Do they demonstrate trustworthiness through "
                "consistency, empathy, and non-judgment?\n"
                "3. MATCHING_TECHNIQUE (0.20): When you describe your posture/gestures, "
                "does the coach mirror or match them to build connection?\n"
                "4. MISMATCH_TECHNIQUE (0.15): Can the coach intentionally mismatch to "
                "redirect the conversation (e.g., shifting posture to change topic)?\n"
                "5. DEBRIEF_QUALITY (0.15): When asked to reflect on what happened, does "
                "the coach show awareness of the rapport dynamics?\n"
                "After the practice, provide a JSON evaluation with 'score' (0.0-1.0), "
                "'feedback' (constructive), and 'dimension_scores' mapping each dimension."
            ),
            "scoring_rubric": {
                "warmth": 0.25,
                "trust_signals": 0.25,
                "matching_technique": 0.20,
                "mismatch_technique": 0.15,
                "debrief_quality": 0.15,
            },
            "participant_flow": [
                "observe_coachee", "match_posture",
                "mismatch_guide", "debrief",
            ],
            "time_pressure": False,
        },
        {
            "id": "focused_listening",
            "name": "Focused Listening Challenge",
            "description": "Progress through 4 levels of listening: cosmetic, conversational, active, and deep",
            "master_prompt": (
                "Coach practices four levels of listening. Little Nate tells a "
                "layered story with surface-level and deeper meanings. The coach "
                "must demonstrate progression from cosmetic listening (surface "
                "acknowledgment) through conversational (engaging), active (reflecting "
                "feelings), to deep listening (connecting unstated meaning)."
            ),
            "nate_system_prompt": (
                "You are playing a COACHEE named Jordan who has a layered story to tell. "
                "Share a personal challenge that has surface-level facts AND deeper emotional "
                "undertones. Include things you say explicitly and things you only hint at. "
                "Respond naturally. The coach is practicing listening skills. EVALUATE:\n"
                "1. COSMETIC_AWARENESS (0.15): Can the coach recognize when they are only "
                "parroting or giving surface acknowledgments? Self-awareness of shallow listening.\n"
                "2. CONVERSATIONAL_ENGAGEMENT (0.20): Does the coach engage meaningfully, "
                "ask follow-ups, show genuine curiosity beyond polite acknowledgment?\n"
                "3. ACTIVE_ATTENTIVENESS (0.30): Does the coach reflect feelings, paraphrase "
                "meaning, check understanding, and demonstrate they truly heard the content?\n"
                "4. DEEP_LISTENING (0.35): Does the coach connect unstated meanings, notice "
                "what was NOT said, sense the emotional undercurrent, and respond to the "
                "whole person — not just the words?\n"
                "After the practice, provide a JSON evaluation with 'score', 'feedback', "
                "and 'dimension_scores'."
            ),
            "scoring_rubric": {
                "cosmetic_awareness": 0.15,
                "conversational_engagement": 0.20,
                "active_attentiveness": 0.30,
                "deep_listening": 0.35,
            },
            "participant_flow": [
                "cosmetic_exchange", "conversational_probe",
                "active_reflection", "deep_presence",
            ],
            "time_pressure": True,
            "minutes": 15,
        },
        {
            "id": "intuition_development",
            "name": "Intuition Trust Exercise",
            "description": "Develop coaching instincts with AI guidance toward confidence through wisdom of correction",
            "master_prompt": (
                "Coach practices trusting their intuition. Little Nate presents "
                "scenarios where the 'right' coaching move isn't obvious from the "
                "textbook. The coach shares their gut read, Little Nate provides "
                "gentle correction or validation, and the coach applies the insight. "
                "The goal is building confident, instinct-driven coaching."
            ),
            "nate_system_prompt": (
                "You are playing a COACHEE named Sam who presents ambiguous situations "
                "where the textbook answer might not be the best answer. Share personal "
                "dilemmas that have no clear right/wrong path. The coach needs to trust "
                "their instincts. After the coach shares their intuitive read, gently "
                "guide them: validate what's strong, correct what could be refined, and "
                "help them trust their gut. EVALUATE:\n"
                "1. INSTINCT_TRUST (0.30): Does the coach share their gut feeling rather "
                "than defaulting to safe/generic responses? Do they take risks?\n"
                "2. CORRECTION_RECEPTIVITY (0.25): When you offer guidance, does the coach "
                "integrate it gracefully or become defensive?\n"
                "3. SELF_AWARENESS (0.25): Can the coach articulate WHY they had that "
                "instinct? Can they distinguish intuition from projection?\n"
                "4. CONFIDENCE_GROWTH (0.20): Does the coach grow more confident and "
                "decisive as the exercise progresses?\n"
                "After the practice, provide a JSON evaluation with 'score', 'feedback', "
                "and 'dimension_scores'."
            ),
            "scoring_rubric": {
                "instinct_trust": 0.30,
                "correction_receptivity": 0.25,
                "self_awareness": 0.25,
                "confidence_growth": 0.20,
            },
            "participant_flow": [
                "initial_read", "intuition_share",
                "nate_correction", "confidence_apply",
            ],
            "time_pressure": False,
        },
        {
            "id": "effective_questions",
            "name": "Effective Questioning Clinic",
            "description": "Master what/how/who questions, avoid implied judgment, and create power questions that drive progress",
            "master_prompt": (
                "Coach practices asking effective questions. Little Nate presents "
                "problem scenarios. The coach must use what/how/who questions (not why), "
                "avoid implied judgment, create collaborative questions that generate "
                "ideas and action, and use power questions that shift from problem to "
                "solution. Focuses on maintaining the balance between influence and control."
            ),
            "nate_system_prompt": (
                "You are playing a COACHEE named Casey who brings a real problem to "
                "coaching. Present a work/life challenge and respond naturally to the "
                "coach's questions. Notice and flag when the coach uses WHY questions "
                "(which often feel judgmental), when they ask leading questions, or when "
                "they slip into advice-giving disguised as questions. EVALUATE:\n"
                "1. QUESTION_TYPE_BALANCE (0.20): Does the coach primarily use what/how/who "
                "questions? Do they avoid why questions and leading questions?\n"
                "2. COLLABORATIVE_TONE (0.20): Do the questions feel collaborative rather "
                "than directive? Does the coach maintain balance between influence and control?\n"
                "3. IDEA_GENERATION (0.20): Do the questions open up thinking, generate "
                "options, and flurry ideas rather than narrowing to one answer?\n"
                "4. POWER_QUESTIONS (0.20): Does the coach use questions that tap into "
                "creativity, shift from problem to solution, and focus thought?\n"
                "5. PROGRESS_CREATION (0.20): Do the questions create forward movement? "
                "Does the coachee feel closer to action after each question?\n"
                "After the practice, provide a JSON evaluation with 'score', 'feedback', "
                "and 'dimension_scores'."
            ),
            "scoring_rubric": {
                "question_type_balance": 0.20,
                "collaborative_tone": 0.20,
                "idea_generation": 0.20,
                "power_questions": 0.20,
                "progress_creation": 0.20,
            },
            "participant_flow": [
                "open_ended_round", "power_question_round",
                "progress_question_round", "reflection",
            ],
            "time_pressure": False,
        },
        {
            "id": "constructive_feedback",
            "name": "Constructive Feedback Workshop",
            "description": "Learn to give bite-size, fact-based feedback that fosters self-awareness and learning",
            "master_prompt": (
                "Coach practices giving constructive feedback. Little Nate presents "
                "coaching scenarios to observe, then the coach drafts and delivers "
                "feedback. Focuses on bite-size delivery, knowing when NOT to give "
                "feedback, the difference between objective and subjective feedback, "
                "and basing feedback on facts and observable behavior."
            ),
            "nate_system_prompt": (
                "You are playing a COACHEE named Riley who just completed a task or "
                "described a situation. Present a scenario with both things done well "
                "and areas for improvement. The coach will observe and then give you "
                "feedback. Respond naturally — if feedback feels judgmental, push back "
                "slightly. If it feels supportive and specific, show openness. EVALUATE:\n"
                "1. SELF_AWARENESS_FOSTERING (0.25): Does the feedback help the coachee "
                "discover insights rather than just telling them what's wrong?\n"
                "2. BITE_SIZE_DELIVERY (0.20): Is the feedback focused and digestible, "
                "not overwhelming? One or two points at a time?\n"
                "3. TIMING_APPROPRIATENESS (0.20): Does the coach recognize when feedback "
                "is helpful vs. when it's better to hold back? Do they read the moment?\n"
                "4. OBJECTIVITY (0.20): Is the feedback based on observable facts and "
                "behavior rather than assumptions, personality judgments, or opinions?\n"
                "5. FACT_BASED (0.15): Can the coach point to specific moments, words, or "
                "behaviors rather than making general statements?\n"
                "After the practice, provide a JSON evaluation with 'score', 'feedback', "
                "and 'dimension_scores'."
            ),
            "scoring_rubric": {
                "self_awareness_fostering": 0.25,
                "bite_size_delivery": 0.20,
                "timing_appropriateness": 0.20,
                "objectivity": 0.20,
                "fact_based": 0.15,
            },
            "participant_flow": [
                "observe_scenario", "draft_feedback",
                "deliver_feedback", "nate_evaluation",
            ],
            "time_pressure": False,
        },
        {
            "id": "coaching_path",
            "name": "Coaching Path Simulation",
            "description": "Full session lifecycle: establish conversation, identify goal, inquire, shape agreement, and close",
            "master_prompt": (
                "Coach runs a complete simulated coaching session with Little Nate "
                "as the coachee. The 5 phases: 1) Establish the conversation and rapport, "
                "2) Identify the topic and goal, 3) Inquiry — understanding and insight, "
                "4) Shape agreement and conclusions, 5) Completion and session close. "
                "Evaluates the coach's ability to manage time between their own space "
                "and the coachee's space."
            ),
            "nate_system_prompt": (
                "You are playing a COACHEE named Morgan who comes to a coaching session "
                "with a real but not yet clearly defined concern. Let the coach guide you "
                "through the session. Start vague and become clearer as the coach asks good "
                "questions. Resist being rushed — if the coach jumps to solutions too early, "
                "show confusion. If they hold space well, open up more. EVALUATE:\n"
                "1. CONVERSATION_ESTABLISHMENT (0.15): Does the coach create a safe opening? "
                "Do they set the frame for the session?\n"
                "2. TOPIC_GOAL_IDENTIFICATION (0.15): Can the coach help you clarify what "
                "you actually want to work on? Do they distinguish topic from goal?\n"
                "3. INQUIRY_DEPTH (0.20): Does the coach explore deeply enough to generate "
                "real understanding and insight? Do they resist premature advice?\n"
                "4. AGREEMENT_SHAPING (0.20): Can the coach help you reach your own "
                "conclusions and commitments? Not imposing solutions but co-creating them?\n"
                "5. SESSION_CLOSURE (0.15): Does the coach close cleanly — summarizing, "
                "confirming next steps, and ending with intention?\n"
                "6. TIME_MANAGEMENT (0.15): Does the coach manage session flow, not spending "
                "too long in any phase? Do they balance their space vs coachee space?\n"
                "After the practice, provide a JSON evaluation with 'score', 'feedback', "
                "and 'dimension_scores'."
            ),
            "scoring_rubric": {
                "conversation_establishment": 0.15,
                "topic_goal_identification": 0.15,
                "inquiry_depth": 0.20,
                "agreement_shaping": 0.20,
                "session_closure": 0.15,
                "time_management": 0.15,
            },
            "participant_flow": [
                "establish_conversation", "identify_topic_goal",
                "inquiry_insight", "shape_agreement", "completion_close",
            ],
            "time_pressure": True,
            "minutes": 25,
        },
    ],
}

ALL_METHOD_IDS = frozenset(
    m["id"] for methods in DOJO_TRAINING_METHODS.values() for m in methods
)

VALID_DOJO_TYPES = frozenset(DOJO_TRAINING_METHODS.keys())


def get_method_by_id(method_id: str) -> Optional[Dict[str, Any]]:
    """Look up a DOJO training method by its ID."""
    for methods in DOJO_TRAINING_METHODS.values():
        for m in methods:
            if m["id"] == method_id:
                return m
    return None


def get_dojo_for_method(method_id: str) -> Optional[str]:
    """Return the DOJO type that owns a given method ID."""
    for dojo, methods in DOJO_TRAINING_METHODS.items():
        for m in methods:
            if m["id"] == method_id:
                return dojo
    return None


class CoachingMeshEngine:
    """
    Request-response service for BLE Coaching Mesh sessions.
    Not a background agent — no run_loop.
    """

    def __init__(self, db_pool: Any, app_state: Optional[Any] = None):
        self.db_pool = db_pool
        self.app_state = app_state
        self._endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
        self._api_key = os.getenv("AZURE_API_KEY", "")
        self._chat_deployment = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o")
        self._api_version = os.getenv("AZURE_API_VERSION", "2024-06-01")

    # ── Session Lifecycle ──

    async def create_session(
        self,
        master_id: str,
        title: str,
        session_type: str,
        dojo_context: Optional[str] = None,
        topic_tags: Optional[List[str]] = None,
        nate_participation: bool = True,
    ) -> Dict[str, Any]:
        if session_type in ALL_METHOD_IDS:
            expected_dojo = get_dojo_for_method(session_type)
            if dojo_context and dojo_context != expected_dojo:
                return {"error": f"Method '{session_type}' belongs to '{expected_dojo}' DOJO, not '{dojo_context}'"}
            dojo_context = expected_dojo
        elif session_type not in GENERAL_SESSION_TYPES:
            return {"error": f"Unknown session type: {session_type}"}

        session_id = f"mesh_{uuid.uuid4().hex[:12]}"
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO coaching_mesh_sessions
                   (session_id, master_coach_id, session_type, title, topic_tags,
                    dojo_context, nate_participation)
                   VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7)""",
                session_id, master_id, session_type, title,
                json.dumps(topic_tags or []), dojo_context, nate_participation,
            )
            await conn.execute(
                """INSERT INTO coaching_mesh_participants
                   (session_id, user_id, role)
                   VALUES ($1, $2, 'master')""",
                session_id, master_id,
            )
            await conn.execute(
                """UPDATE coaching_mesh_sessions SET participant_count = 1
                   WHERE session_id = $1""",
                session_id,
            )
        method = get_method_by_id(session_type)
        return {
            "session_id": session_id,
            "title": title,
            "session_type": session_type,
            "dojo_context": dojo_context,
            "method": method,
        }

    async def join_session(
        self,
        session_id: str,
        user_id: str,
        role: str = "assistant",
        ble_device_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        async with self.db_pool.acquire() as conn:
            session = await conn.fetchrow(
                "SELECT * FROM coaching_mesh_sessions WHERE session_id = $1 AND ended_at IS NULL",
                session_id,
            )
            if not session:
                return {"error": "Session not found or already ended"}

            await conn.execute(
                """INSERT INTO coaching_mesh_participants
                   (session_id, user_id, role, ble_device_id)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (session_id, user_id) DO UPDATE
                   SET left_at = NULL, ble_device_id = EXCLUDED.ble_device_id""",
                session_id, user_id, role, ble_device_id,
            )
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM coaching_mesh_participants WHERE session_id = $1 AND left_at IS NULL",
                session_id,
            )
            await conn.execute(
                "UPDATE coaching_mesh_sessions SET participant_count = $1 WHERE session_id = $2",
                count, session_id,
            )
        return {"session_id": session_id, "role": role, "participant_count": count}

    async def leave_session(self, session_id: str, user_id: str) -> Dict[str, Any]:
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """UPDATE coaching_mesh_participants SET left_at = NOW()
                   WHERE session_id = $1 AND user_id = $2 AND left_at IS NULL""",
                session_id, user_id,
            )
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM coaching_mesh_participants WHERE session_id = $1 AND left_at IS NULL",
                session_id,
            )
            await conn.execute(
                "UPDATE coaching_mesh_sessions SET participant_count = $1 WHERE session_id = $2",
                count, session_id,
            )
        return {"session_id": session_id, "left": user_id, "participant_count": count}

    async def end_session(self, session_id: str, master_id: str) -> Dict[str, Any]:
        async with self.db_pool.acquire() as conn:
            session = await conn.fetchrow(
                "SELECT * FROM coaching_mesh_sessions WHERE session_id = $1",
                session_id,
            )
            if not session:
                return {"error": "Session not found"}
            if session["master_coach_id"] != master_id:
                return {"error": "Only the master coach can end the session"}

            await conn.execute(
                "UPDATE coaching_mesh_sessions SET ended_at = NOW() WHERE session_id = $1",
                session_id,
            )
            await conn.execute(
                """UPDATE coaching_mesh_participants SET left_at = NOW()
                   WHERE session_id = $1 AND left_at IS NULL""",
                session_id,
            )

            participants = await conn.fetch(
                """SELECT user_id, role, joined_at,
                          COALESCE(left_at, NOW()) as effective_left
                   FROM coaching_mesh_participants
                   WHERE session_id = $1""",
                session_id,
            )
            hours_logged = []
            for p in participants:
                if p["role"] == "assistant":
                    duration = (p["effective_left"] - p["joined_at"]).total_seconds() / 60.0
                    if duration > 0:
                        await conn.execute(
                            """INSERT INTO supervised_hours
                               (assistant_id, master_coach_id, activity_type, dojo_type,
                                duration_minutes, notes, mesh_session_id)
                               VALUES ($1, $2, 'group_supervision', $3, $4, $5, $6)""",
                            p["user_id"], master_id, session.get("dojo_context"),
                            round(duration, 1),
                            f"Auto-logged from mesh session: {session['title']}",
                            session_id,
                        )
                        hours_logged.append({
                            "assistant_id": p["user_id"],
                            "minutes": round(duration, 1),
                        })

            if session.get("dojo_context") == "coach_nate" and session.get("session_type"):
                await self._update_coach_nate_progress(conn, session, participants)

        return {
            "session_id": session_id,
            "ended": True,
            "hours_logged": hours_logged,
        }

    # ── Coach Nate Progress Tracking ──

    COACH_NATE_SKILL_AREAS = frozenset({
        "rapport_building", "focused_listening", "intuition_development",
        "effective_questions", "constructive_feedback", "coaching_path",
    })

    async def _update_coach_nate_progress(self, conn, session, participants):
        """Update cumulative progress for Coach Nate DOJO sessions."""
        session_type = session.get("session_type", "")
        if session_type not in self.COACH_NATE_SKILL_AREAS:
            return

        try:
            scores = await conn.fetch(
                """SELECT p.user_id, AVG(m.score) as avg_score,
                          MAX(m.score) as max_score
                   FROM coaching_mesh_messages m
                   JOIN coaching_mesh_participants p ON p.session_id = m.session_id
                     AND p.user_id = m.sender_id
                   WHERE m.session_id = $1 AND m.score IS NOT NULL
                   GROUP BY p.user_id""",
                session["session_id"],
            )
            for row in scores:
                avg = float(row["avg_score"]) if row["avg_score"] else 0
                best = float(row["max_score"]) if row["max_score"] else 0
                await conn.execute(
                    """INSERT INTO coach_nate_progress
                       (coach_username, skill_area, session_count, total_score,
                        average_score, best_score, last_session_at, updated_at)
                       VALUES ($1, $2, 1, $3, $3, $4, NOW(), NOW())
                       ON CONFLICT (coach_username, skill_area) DO UPDATE SET
                         session_count = coach_nate_progress.session_count + 1,
                         total_score = coach_nate_progress.total_score + EXCLUDED.total_score,
                         average_score = (coach_nate_progress.total_score + EXCLUDED.total_score)
                                         / (coach_nate_progress.session_count + 1),
                         best_score = GREATEST(coach_nate_progress.best_score, EXCLUDED.best_score),
                         last_session_at = NOW(),
                         updated_at = NOW()""",
                    row["user_id"], session_type, avg, best,
                )
        except Exception as e:
            logger.warning("Coach Nate progress update failed: %s", e)

    # ── Messaging ──

    async def post_message(
        self,
        session_id: str,
        sender_id: str,
        message_type: str,
        content: str,
        metadata: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO coaching_mesh_messages
                   (session_id, sender_id, message_type, content, metadata)
                   VALUES ($1, $2, $3, $4, $5::jsonb)
                   RETURNING id, created_at""",
                session_id, sender_id, message_type, content,
                json.dumps(metadata) if metadata else None,
            )
        return {
            "message_id": row["id"],
            "session_id": session_id,
            "sender_id": sender_id,
            "message_type": message_type,
            "content": content,
            "metadata": metadata,
            "created_at": row["created_at"].isoformat(),
        }

    # ── Quiz ──

    async def push_quiz(
        self,
        session_id: str,
        master_id: str,
        questions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        async with self.db_pool.acquire() as conn:
            session = await conn.fetchrow(
                "SELECT master_coach_id FROM coaching_mesh_sessions WHERE session_id = $1",
                session_id,
            )
            if not session or session["master_coach_id"] != master_id:
                return {"error": "Only the master coach can push quizzes"}

            message_ids = []
            for i, q in enumerate(questions):
                meta = {
                    "question_index": i,
                    "options": q.get("options"),
                    "correct_answer": q.get("correct_answer"),
                    "question_type": q.get("type", "open_text"),
                }
                row = await conn.fetchrow(
                    """INSERT INTO coaching_mesh_messages
                       (session_id, sender_id, message_type, content, metadata)
                       VALUES ($1, $2, 'quiz_question', $3, $4::jsonb)
                       RETURNING id""",
                    session_id, master_id, q.get("text", ""), json.dumps(meta),
                )
                message_ids.append(row["id"])

        return {
            "session_id": session_id,
            "questions_pushed": len(questions),
            "message_ids": message_ids,
        }

    async def submit_quiz_answer(
        self,
        session_id: str,
        user_id: str,
        question_index: int,
        answer: str,
    ) -> Dict[str, Any]:
        async with self.db_pool.acquire() as conn:
            question = await conn.fetchrow(
                """SELECT id, metadata FROM coaching_mesh_messages
                   WHERE session_id = $1 AND message_type = 'quiz_question'
                   AND (metadata->>'question_index')::int = $2
                   ORDER BY created_at LIMIT 1""",
                session_id, question_index,
            )
            parent_id = question["id"] if question else None

            row = await conn.fetchrow(
                """INSERT INTO coaching_mesh_messages
                   (session_id, sender_id, message_type, content,
                    parent_message_id, metadata)
                   VALUES ($1, $2, 'quiz_answer', $3, $4, $5::jsonb)
                   RETURNING id""",
                session_id, user_id, answer, parent_id,
                json.dumps({"question_index": question_index}),
            )

        score_result = await self._auto_evaluate(
            session_id, row["id"], answer, question, "quiz"
        )

        return {
            "message_id": row["id"],
            "question_index": question_index,
            "score": score_result.get("score"),
            "feedback": score_result.get("feedback"),
        }

    # ── Scenario ──

    async def push_scenario(
        self,
        session_id: str,
        master_id: str,
        dojo_type: str,
        persona: str,
        description: str,
    ) -> Dict[str, Any]:
        from app.services.dojo_mentor_engine import MASTER_PERSONA
        persona_text = MASTER_PERSONA.get(dojo_type, "")
        meta = {"persona": persona, "dojo_type": dojo_type}

        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO coaching_mesh_messages
                   (session_id, sender_id, message_type, content, metadata)
                   VALUES ($1, $2, 'scenario_prompt', $3, $4::jsonb)
                   RETURNING id""",
                session_id, master_id, description, json.dumps(meta),
            )

        return {
            "message_id": row["id"],
            "session_id": session_id,
            "persona": persona,
            "dojo_type": dojo_type,
        }

    async def submit_scenario_response(
        self,
        session_id: str,
        user_id: str,
        response: str,
        scenario_message_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        async with self.db_pool.acquire() as conn:
            if not scenario_message_id:
                scenario = await conn.fetchrow(
                    """SELECT id, metadata FROM coaching_mesh_messages
                       WHERE session_id = $1 AND message_type = 'scenario_prompt'
                       ORDER BY created_at DESC LIMIT 1""",
                    session_id,
                )
                scenario_message_id = scenario["id"] if scenario else None

            row = await conn.fetchrow(
                """INSERT INTO coaching_mesh_messages
                   (session_id, sender_id, message_type, content, parent_message_id)
                   VALUES ($1, $2, 'scenario_response', $3, $4)
                   RETURNING id""",
                session_id, user_id, response, scenario_message_id,
            )

        score_result = await self._auto_evaluate(
            session_id, row["id"], response, None, "scenario"
        )

        return {
            "message_id": row["id"],
            "score": score_result.get("score"),
            "feedback": score_result.get("feedback"),
        }

    # ── Little Nate Feedback ──

    async def get_nate_feedback(
        self,
        session_id: str,
        context: str,
        user_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        session_info = None
        async with self.db_pool.acquire() as conn:
            session_info = await conn.fetchrow(
                "SELECT session_type, dojo_context, title FROM coaching_mesh_sessions WHERE session_id = $1",
                session_id,
            )

        if not session_info:
            return {"error": "Session not found"}

        system_prompt = self._build_nate_prompt(session_info)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Session context:\n{context}\n\n{user_prompt or 'Provide your analysis and feedback.'}"},
        ]

        response_text = await self._call_azure(messages)

        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO coaching_mesh_messages
                   (session_id, sender_id, message_type, content)
                   VALUES ($1, 'nate', 'nate_feedback', $2)""",
                session_id, response_text,
            )

        return {"feedback": response_text, "session_id": session_id}

    # ── Queries ──

    async def get_session_transcript(self, session_id: str) -> List[Dict[str, Any]]:
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, sender_id, message_type, content, metadata,
                          parent_message_id, score, created_at
                   FROM coaching_mesh_messages
                   WHERE session_id = $1
                   ORDER BY created_at""",
                session_id,
            )
        return [
            {
                "id": r["id"],
                "sender_id": r["sender_id"],
                "message_type": r["message_type"],
                "content": r["content"],
                "metadata": json.loads(r["metadata"]) if r["metadata"] else None,
                "parent_message_id": r["parent_message_id"],
                "score": r["score"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]

    async def get_session_scores(self, session_id: str) -> Dict[str, Any]:
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT sender_id, score, message_type, metadata
                   FROM coaching_mesh_messages
                   WHERE session_id = $1 AND score IS NOT NULL
                   ORDER BY sender_id, created_at""",
                session_id,
            )
        scores_by_user: Dict[str, List] = {}
        for r in rows:
            uid = r["sender_id"]
            if uid not in scores_by_user:
                scores_by_user[uid] = []
            scores_by_user[uid].append({
                "score": r["score"],
                "type": r["message_type"],
                "metadata": json.loads(r["metadata"]) if r["metadata"] else None,
            })

        summary = {}
        for uid, items in scores_by_user.items():
            avg = sum(i["score"] for i in items) / len(items) if items else 0.0
            summary[uid] = {"scores": items, "average": round(avg, 3), "count": len(items)}

        return summary

    async def get_sessions_for_coach(
        self, coach_id: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT s.session_id, s.title, s.session_type, s.dojo_context,
                          s.started_at, s.ended_at, s.participant_count
                   FROM coaching_mesh_sessions s
                   LEFT JOIN coaching_mesh_participants p ON s.session_id = p.session_id
                   WHERE s.master_coach_id = $1 OR p.user_id = $1
                   GROUP BY s.session_id, s.title, s.session_type, s.dojo_context,
                            s.started_at, s.ended_at, s.participant_count
                   ORDER BY s.started_at DESC LIMIT $2""",
                coach_id, limit,
            )
        return [
            {
                "session_id": r["session_id"],
                "title": r["title"],
                "session_type": r["session_type"],
                "dojo_context": r["dojo_context"],
                "started_at": r["started_at"].isoformat() if r["started_at"] else None,
                "ended_at": r["ended_at"].isoformat() if r["ended_at"] else None,
                "participant_count": r["participant_count"],
            }
            for r in rows
        ]

    async def get_session_participants(self, session_id: str) -> List[Dict[str, Any]]:
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT user_id, role, joined_at, left_at, ble_device_id
                   FROM coaching_mesh_participants
                   WHERE session_id = $1
                   ORDER BY joined_at""",
                session_id,
            )
        return [
            {
                "user_id": r["user_id"],
                "role": r["role"],
                "joined_at": r["joined_at"].isoformat() if r["joined_at"] else None,
                "left_at": r["left_at"].isoformat() if r["left_at"] else None,
                "ble_device_id": r["ble_device_id"],
            }
            for r in rows
        ]

    async def generate_quiz_from_topic(
        self, topic: str, dojo_type: Optional[str] = None, count: int = 5
    ) -> List[Dict[str, Any]]:
        """Use Azure OpenAI to generate quiz questions for a topic."""
        dojo_hint = f" in the context of the {dojo_type} discipline" if dojo_type else ""
        messages = [
            {
                "role": "system",
                "content": (
                    "You generate training quiz questions for professional development. "
                    "Output valid JSON: an array of objects, each with 'text', 'type' "
                    "(multiple_choice, scale, open_text), 'options' (array for MC, null "
                    "otherwise), and 'correct_answer' (string)."
                ),
            },
            {
                "role": "user",
                "content": f"Generate {count} quiz questions about: {topic}{dojo_hint}",
            },
        ]
        raw = await self._call_azure(messages, json_mode=True)
        try:
            questions = json.loads(raw)
            if isinstance(questions, dict) and "questions" in questions:
                questions = questions["questions"]
            return questions if isinstance(questions, list) else []
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse AI quiz response")
            return []

    def get_methods(self, dojo_type: Optional[str] = None) -> Dict[str, Any]:
        """Return DOJO training methods, optionally filtered by DOJO type."""
        if dojo_type:
            methods = DOJO_TRAINING_METHODS.get(dojo_type, [])
            return {"dojo_type": dojo_type, "methods": methods}
        return {
            dojo: [
                {"id": m["id"], "name": m["name"], "description": m["description"],
                 "time_pressure": m.get("time_pressure", False),
                 "minutes": m.get("minutes")}
                for m in methods
            ]
            for dojo, methods in DOJO_TRAINING_METHODS.items()
        }

    # ── Internal Helpers ──

    def _build_nate_prompt(self, session_info) -> str:
        session_type = session_info["session_type"]
        dojo_context = session_info["dojo_context"]

        method = get_method_by_id(session_type)
        if method:
            rubric_text = ", ".join(
                f"{k} ({int(v*100)}%)" for k, v in method["scoring_rubric"].items()
            )
            return (
                f"{method['nate_system_prompt']}\n\n"
                f"Scoring rubric: {rubric_text}\n\n"
                f"Session: {session_info['title']}"
            )

        from app.services.dojo_mentor_engine import MASTER_PERSONA
        persona = MASTER_PERSONA.get(dojo_context, "")
        if persona:
            return (
                f"{persona}\n\nYou are participating in a {session_type} training "
                f"session titled '{session_info['title']}'. Provide expert feedback "
                f"and analysis appropriate to your domain."
            )

        return (
            "You are Little Nate, an AI coaching assistant participating in a "
            f"group training session titled '{session_info['title']}'. "
            "Provide constructive, insightful feedback to help participants learn."
        )

    async def _auto_evaluate(
        self,
        session_id: str,
        message_id: int,
        response_text: str,
        question_row: Optional[Any],
        eval_type: str,
    ) -> Dict[str, Any]:
        """AI-evaluate a quiz answer or scenario response."""
        session_info = None
        async with self.db_pool.acquire() as conn:
            session_info = await conn.fetchrow(
                "SELECT session_type, dojo_context, title FROM coaching_mesh_sessions WHERE session_id = $1",
                session_id,
            )

        if not session_info or not self._api_key:
            return {"score": None, "feedback": None}

        system_prompt = self._build_nate_prompt(session_info)
        question_text = ""
        if question_row and question_row.get("content"):
            question_text = f"Question: {question_row['content']}\n"

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"{question_text}Response to evaluate:\n{response_text}\n\n"
                    "Evaluate this response. Return JSON with 'score' (0.0-1.0), "
                    "'feedback' (constructive text), and optionally 'dimension_scores' "
                    "(dict of rubric dimensions to scores)."
                ),
            },
        ]

        raw = await self._call_azure(messages, json_mode=True)
        try:
            result = json.loads(raw)
            score = float(result.get("score", 0.5))
            feedback = result.get("feedback", "")
            dimension_scores = result.get("dimension_scores")

            async with self.db_pool.acquire() as conn:
                meta = {"evaluation_feedback": feedback}
                if dimension_scores:
                    meta["dimension_scores"] = dimension_scores
                await conn.execute(
                    """UPDATE coaching_mesh_messages
                       SET score = $1, metadata = COALESCE(metadata, '{}'::jsonb) || $2::jsonb
                       WHERE id = $3""",
                    score, json.dumps(meta), message_id,
                )

            return {"score": score, "feedback": feedback, "dimension_scores": dimension_scores}
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.warning("Failed to parse evaluation response: %s", e)
            return {"score": None, "feedback": None}

    async def _call_azure(
        self, messages: List[Dict], json_mode: bool = False
    ) -> str:
        if not self._endpoint or not self._api_key:
            return '{"error": "Azure OpenAI not configured"}'

        url = (
            f"https://{self._endpoint}/openai/deployments/{self._chat_deployment}"
            f"/chat/completions?api-version={self._api_version}"
        )
        payload: Dict[str, Any] = {"messages": messages, "max_completion_tokens": 2000}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {"api-key": self._api_key, "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    return data["choices"][0]["message"]["content"]
                logger.warning("Azure API returned %d: %s", resp.status_code, resp.text[:200])
                return '{"error": "Azure API error"}'
        except Exception as e:
            logger.error("Azure API call failed: %s", e)
            return '{"error": "Azure API call failed"}'
