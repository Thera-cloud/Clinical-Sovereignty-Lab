"""Clinical intake question catalog and shared constants."""

from __future__ import annotations

from typing import Dict, List

SECTION1_TEXT_FIELDS: List[str] = [
    "q1_preferred_name",
    "q2_pronouns",
    "q3_household_relationship",
    "q4_bringing_you_in",
    "q5_how_long",
    "q6_hope_to_get",
    "q7_successful_outcome",
    "q8_biggest_things_weighing",
    "q11_communication_preferences",
    "q12_anything_else_upfront",
]

SECTION1_ENUM_FIELDS: Dict[str, List[str]] = {
    "q9_support_network": ["yes", "somewhat", "no"],
    "q10_current_wellbeing": ["not_satisfactory", "satisfactory", "thriving"],
}

SECTION1_FIELDS: List[str] = SECTION1_TEXT_FIELDS + list(SECTION1_ENUM_FIELDS.keys())

SECTION2_FIELDS: List[str] = [
    "q13_emergency_contact_name",
    "q13_emergency_contact_phone",
    "q14_address",
    "q15_prior_treatment",
    "q16_current_medications",
    "q17_family_history",
    "q18_suicide_self_harm_history",
    "q19_trauma_history",
    "q20_substance_use",
    "q21_sleep_appetite_energy",
]

SECTION1_STATUS_VALUES = ("not_started", "in_progress", "complete")
SECTION2_STATUS_VALUES = ("not_started", "in_progress", "complete")
SECTION2_COMPLETED_BY_VALUES = ("client", "coach")

QUESTION_LABELS: Dict[str, str] = {
    "q1_preferred_name": "What name would you like me to use for you?",
    "q2_pronouns": "What pronouns do you use?",
    "q3_household_relationship": "Who lives in your household, and what's your current relationship status?",
    "q4_bringing_you_in": "What's bringing you in right now?",
    "q5_how_long": "How long has this been going on?",
    "q6_hope_to_get": "What do you hope to get from our conversations?",
    "q7_successful_outcome": "What would a successful outcome look like to you?",
    "q8_biggest_things_weighing": "What are the biggest things weighing on you right now?",
    "q9_support_network": "Do you have people in your life you can turn to for support?",
    "q10_current_wellbeing": "How would you rate where you're at right now?",
    "q11_communication_preferences": "Is there anything you'd like me to know about how you communicate or process things best?",
    "q12_anything_else_upfront": "Is there anything else you want me to know upfront?",
    "q13_emergency_contact_name": "Emergency contact name",
    "q13_emergency_contact_phone": "Emergency contact phone number",
    "q14_address": "Current address",
    "q15_prior_treatment": "Have you received therapy, counseling, or psychiatric treatment in the past?",
    "q16_current_medications": "Are you currently taking any prescription medications, vitamins, or supplements?",
    "q17_family_history": "Is there a history of mental health conditions or substance use in your immediate family?",
    "q18_suicide_self_harm_history": "Have you ever attempted suicide or engaged in self-harming behaviors in the past?",
    "q19_trauma_history": "Have you ever experienced a significant trauma, loss, or major life upheaval?",
    "q20_substance_use": "How many alcoholic drinks do you have in an average week, and do you use any recreational substances?",
    "q21_sleep_appetite_energy": "How would you describe your current sleep, appetite, and energy?",
}

ALL_QUESTION_FIELDS: List[str] = SECTION1_FIELDS + SECTION2_FIELDS
