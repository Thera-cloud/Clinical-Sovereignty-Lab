"""
JUDGE DOJO — Debate and Mentoring Session Management

Handles:
- Coach-vs-Coach debates with Judge Nate presiding ($500/simulation per coach)
- Coach-as-Judge mentoring sessions with verified students ($250/simulation to coach-judge)
- Scoring, rulings, interjections, and evaluations
- Financial ledger tracking for simulation fees
"""

from __future__ import annotations

import datetime
import secrets
import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional


class DebateStatus(str, Enum):
    PENDING_MATCH = "pending_match"
    SCHEDULED = "scheduled"
    PAYMENT_CONFIRMED = "payment_confirmed"
    IN_PROGRESS = "in_progress"
    RULING_ISSUED = "ruling_issued"
    CANCELLED = "cancelled"


class MentoringStatus(str, Enum):
    PENDING = "pending"
    PAYMENT_CONFIRMED = "payment_confirmed"
    IN_PROGRESS = "in_progress"
    EVALUATED = "evaluated"
    CANCELLED = "cancelled"


class InterjectionType(str, Enum):
    OBJECTION = "objection"
    SUSTAINED = "sustained"
    OVERRULED = "overruled"
    CONTEMPT = "contempt"
    ORDER = "order"
    SIDEBAR = "sidebar"
    ADMONISH = "admonish"
    INSTRUCT_JURY = "instruct_jury"


@dataclass
class NateInterjection:
    """A single Judge Nate interjection during a debate or mentoring session."""
    timestamp: str
    interjection_type: str  # InterjectionType value
    target_coach: str  # coach_id the interjection is directed at
    statement: str  # What Judge Nate says
    reasoning: str = ""  # Why Nate interjected

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "type": self.interjection_type,
            "target": self.target_coach,
            "statement": self.statement,
            "reasoning": self.reasoning,
        }


@dataclass
class CoachScore:
    """Scoring for one coach in a debate."""
    coach_id: str
    legal_reasoning: int = 0  # 0-100
    evidence_presentation: int = 0  # 0-100
    courtroom_demeanor: int = 0  # 0-100
    persuasiveness: int = 0  # 0-100
    total: int = 0

    def compute_total(self):
        self.total = (self.legal_reasoning + self.evidence_presentation +
                      self.courtroom_demeanor + self.persuasiveness) // 4
        return self.total

    def to_dict(self) -> Dict:
        return {
            "coach_id": self.coach_id,
            "legal_reasoning": self.legal_reasoning,
            "evidence_presentation": self.evidence_presentation,
            "courtroom_demeanor": self.courtroom_demeanor,
            "persuasiveness": self.persuasiveness,
            "total": self.total,
        }


@dataclass
class JudgeDebateSession:
    """A coach-vs-coach debate with Judge Nate presiding."""
    session_id: str = ""
    coach_a_id: str = ""
    coach_b_id: str = ""
    case_description: str = ""
    zoom_meeting_id: str = ""
    zoom_join_url: str = ""
    simulation_fee: float = 500.0
    debate_status: str = DebateStatus.PENDING_MATCH
    created_at: str = ""
    started_at: str = ""
    ended_at: str = ""
    nate_observations: List[Dict] = field(default_factory=list)
    scores: Dict[str, Dict] = field(default_factory=dict)  # {coach_id: CoachScore.to_dict()}
    ruling: Dict = field(default_factory=dict)  # {prevailing_coach, reasoning}
    transcript_excerpts: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.session_id:
            self.session_id = f"DEBATE-{secrets.token_hex(6).upper()}"
        if not self.created_at:
            self.created_at = datetime.datetime.now().isoformat()

    def to_dict(self) -> Dict:
        return {
            "session_id": self.session_id,
            "coach_a_id": self.coach_a_id,
            "coach_b_id": self.coach_b_id,
            "case_description": self.case_description,
            "zoom_meeting_id": self.zoom_meeting_id,
            "zoom_join_url": self.zoom_join_url,
            "simulation_fee": self.simulation_fee,
            "debate_status": self.debate_status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "nate_observations": self.nate_observations,
            "scores": self.scores,
            "ruling": self.ruling,
        }


@dataclass
class StudentAssessment:
    """Evaluation of a single student's performance."""
    student_id: str = ""
    student_name: str = ""
    argument_structure: int = 0  # 0-100
    evidence_usage: int = 0  # 0-100
    persuasiveness: int = 0  # 0-100
    legal_knowledge: int = 0  # 0-100
    overall: int = 0
    feedback: str = ""

    def compute_overall(self):
        self.overall = (self.argument_structure + self.evidence_usage +
                        self.persuasiveness + self.legal_knowledge) // 4
        return self.overall

    def to_dict(self) -> Dict:
        return {
            "student_id": self.student_id,
            "student_name": self.student_name,
            "argument_structure": self.argument_structure,
            "evidence_usage": self.evidence_usage,
            "persuasiveness": self.persuasiveness,
            "legal_knowledge": self.legal_knowledge,
            "overall": self.overall,
            "feedback": self.feedback,
        }


@dataclass
class JudgeMentoringSession:
    """A coaching session where the coach acts as judge and students argue."""
    session_id: str = ""
    coach_id: str = ""  # Acting as judge
    student_ids: List[str] = field(default_factory=list)
    zoom_meeting_id: str = ""
    zoom_join_url: str = ""
    simulation_fee: float = 250.0  # Charged to coach-judge
    status: str = MentoringStatus.PENDING
    created_at: str = ""
    started_at: str = ""
    ended_at: str = ""
    coach_judge_assessment: Dict = field(default_factory=dict)
    # {demeanor, fairness, legal_accuracy, feedback_quality, overall, feedback}
    student_assessments: List[Dict] = field(default_factory=list)
    nate_learning_notes: str = ""
    nate_observations: List[Dict] = field(default_factory=list)

    def __post_init__(self):
        if not self.session_id:
            self.session_id = f"MENTOR-{secrets.token_hex(6).upper()}"
        if not self.created_at:
            self.created_at = datetime.datetime.now().isoformat()

    def to_dict(self) -> Dict:
        return {
            "session_id": self.session_id,
            "coach_id": self.coach_id,
            "student_ids": self.student_ids,
            "zoom_meeting_id": self.zoom_meeting_id,
            "zoom_join_url": self.zoom_join_url,
            "simulation_fee": self.simulation_fee,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "coach_judge_assessment": self.coach_judge_assessment,
            "student_assessments": self.student_assessments,
            "nate_learning_notes": self.nate_learning_notes,
        }


class JudgeDebateManager:
    """Manages JUDGE DOJO debate and mentoring sessions."""

    def __init__(self):
        self.debate_queue: List[Dict] = []  # Coaches waiting for a match
        self.active_debates: Dict[str, JudgeDebateSession] = {}
        self.active_mentoring: Dict[str, JudgeMentoringSession] = {}
        self.completed_debates: List[Dict] = []
        self.completed_mentoring: List[Dict] = []

    def request_debate(self, coach_id: str, coach_name: str,
                       bar_id: str, case_description: str) -> Dict:
        """Coach requests a debate — enters matchmaking queue."""
        entry = {
            "coach_id": coach_id,
            "coach_name": coach_name,
            "bar_id": bar_id,
            "case_description": case_description,
            "queued_at": datetime.datetime.now().isoformat(),
        }

        # Check if there's already someone in the queue to match with
        if self.debate_queue:
            opponent = self.debate_queue.pop(0)
            if opponent["coach_id"] == coach_id:
                # Can't match with yourself
                self.debate_queue.append(entry)
                return {"status": "queued", "message": "Waiting for an opponent..."}

            session = JudgeDebateSession(
                coach_a_id=opponent["coach_id"],
                coach_b_id=coach_id,
                case_description=f"[Coach A]: {opponent['case_description']}\n[Coach B]: {case_description}",
            )
            session.debate_status = DebateStatus.SCHEDULED
            self.active_debates[session.session_id] = session
            return {
                "status": "matched",
                "session_id": session.session_id,
                "opponent_name": opponent["coach_name"],
                "opponent_bar_id": opponent["bar_id"],
                "message": f"Matched with {opponent['coach_name']}! Confirm $500 fee to proceed.",
            }
        else:
            self.debate_queue.append(entry)
            return {"status": "queued", "message": "Entered debate queue. Waiting for an opponent..."}

    def confirm_debate_payment(self, session_id: str, coach_id: str) -> Dict:
        """Coach confirms the $500 simulation fee."""
        session = self.active_debates.get(session_id)
        if not session:
            return {"error": "Debate session not found"}

        # Track confirmation
        if not hasattr(session, '_payment_confirmed'):
            session._payment_confirmed = set()
        session._payment_confirmed = getattr(session, '_payment_confirmed', set())
        session._payment_confirmed.add(coach_id)

        if session.coach_a_id in session._payment_confirmed and session.coach_b_id in session._payment_confirmed:
            session.debate_status = DebateStatus.PAYMENT_CONFIRMED
            return {"status": "both_confirmed", "session_id": session_id,
                    "message": "Both coaches confirmed. Ready to start debate."}
        return {"status": "waiting_opponent", "session_id": session_id,
                "message": "Payment confirmed. Waiting for opponent to confirm."}

    def start_debate(self, session_id: str, zoom_meeting_id: str, zoom_join_url: str) -> Dict:
        """Start the debate after Zoom meeting is created."""
        session = self.active_debates.get(session_id)
        if not session:
            return {"error": "Debate session not found"}
        session.zoom_meeting_id = zoom_meeting_id
        session.zoom_join_url = zoom_join_url
        session.debate_status = DebateStatus.IN_PROGRESS
        session.started_at = datetime.datetime.now().isoformat()
        return session.to_dict()

    def add_interjection(self, session_id: str, interjection: NateInterjection) -> Dict:
        """Add a Judge Nate interjection to an active debate."""
        session = self.active_debates.get(session_id)
        if not session:
            return {"error": "Debate session not found"}
        session.nate_observations.append(interjection.to_dict())
        return interjection.to_dict()

    def issue_ruling(self, session_id: str, prevailing_coach_id: str,
                     reasoning: str, scores: Dict[str, CoachScore]) -> Dict:
        """Judge Nate issues a ruling and scores both coaches."""
        session = self.active_debates.get(session_id)
        if not session:
            return {"error": "Debate session not found"}

        for coach_id, score in scores.items():
            score.compute_total()
            session.scores[coach_id] = score.to_dict()

        session.ruling = {
            "prevailing_coach": prevailing_coach_id,
            "reasoning": reasoning,
            "issued_at": datetime.datetime.now().isoformat(),
        }
        session.debate_status = DebateStatus.RULING_ISSUED
        session.ended_at = datetime.datetime.now().isoformat()

        # Move to completed
        self.completed_debates.append(session.to_dict())

        return session.to_dict()

    def create_mentoring_session(self, coach_id: str, student_ids: List[str]) -> Dict:
        """Coach initiates a mentoring session as judge with verified students."""
        session = JudgeMentoringSession(
            coach_id=coach_id,
            student_ids=student_ids,
        )
        self.active_mentoring[session.session_id] = session
        return {
            "status": "created",
            "session_id": session.session_id,
            "message": f"Mentoring session created. Confirm $250 fee to proceed. Students: {len(student_ids)}",
        }

    def confirm_mentoring_payment(self, session_id: str) -> Dict:
        """Coach confirms the $250 mentoring fee."""
        session = self.active_mentoring.get(session_id)
        if not session:
            return {"error": "Mentoring session not found"}
        session.status = MentoringStatus.PAYMENT_CONFIRMED
        return {"status": "confirmed", "session_id": session_id,
                "message": "Payment confirmed. Ready to start mentoring session."}

    def start_mentoring(self, session_id: str, zoom_meeting_id: str, zoom_join_url: str) -> Dict:
        """Start the mentoring session after Zoom meeting is created."""
        session = self.active_mentoring.get(session_id)
        if not session:
            return {"error": "Mentoring session not found"}
        session.zoom_meeting_id = zoom_meeting_id
        session.zoom_join_url = zoom_join_url
        session.status = MentoringStatus.IN_PROGRESS
        session.started_at = datetime.datetime.now().isoformat()
        return session.to_dict()

    def evaluate_mentoring(self, session_id: str, coach_assessment: Dict,
                           student_assessments: List[Dict],
                           nate_learning_notes: str) -> Dict:
        """Judge Nate evaluates both the coach-judge and the students."""
        session = self.active_mentoring.get(session_id)
        if not session:
            return {"error": "Mentoring session not found"}

        session.coach_judge_assessment = coach_assessment
        session.student_assessments = student_assessments
        session.nate_learning_notes = nate_learning_notes
        session.status = MentoringStatus.EVALUATED
        session.ended_at = datetime.datetime.now().isoformat()

        # Move to completed
        self.completed_mentoring.append(session.to_dict())

        return session.to_dict()

    def generate_interjection(self, transcript_segment: str,
                              coach_a_id: str, coach_b_id: str) -> Optional[NateInterjection]:
        """Analyze a transcript segment and generate an appropriate Judge Nate interjection.
        This is called periodically with new transcript data during a live debate."""
        # Keywords that trigger judicial interjections
        triggers = {
            "objection": ("objection", "The Court notes an objection has been raised."),
            "hearsay": ("sustained", "Sustained. Counsel will refrain from presenting hearsay testimony."),
            "irrelevant": ("sustained", "Sustained. Counsel will confine arguments to relevant matters."),
            "badgering": ("admonish", "Counsel is admonished. You will treat opposing counsel with respect."),
            "speculation": ("sustained", "Sustained. Counsel is speculating. Stick to the facts in evidence."),
            "move to strike": ("order", "The Court will consider the motion. Counsel, your basis?"),
            "hostile": ("order", "The Court reminds both parties to maintain courtroom decorum."),
            "contempt": ("contempt", "Counsel is warned. One more outburst and the Court will hold you in contempt."),
            "sidebar": ("sidebar", "The Court will see both counsel at sidebar."),
        }

        lower = transcript_segment.lower()
        for keyword, (itype, statement) in triggers.items():
            if keyword in lower:
                return NateInterjection(
                    timestamp=datetime.datetime.now().isoformat(),
                    interjection_type=itype,
                    target_coach=coach_a_id,  # Will be refined by AI analysis
                    statement=statement,
                )

        return None

    def record_financial_charge(self, profile: Dict, amount: float, description: str) -> Dict:
        """Record a simulation fee in the coach's financial ledger."""
        ledger = profile.setdefault("financial_ledger", [])
        entry = {
            "amount": amount,
            "description": description,
            "timestamp": datetime.datetime.now().isoformat(),
            "type": "judge_simulation_fee",
        }
        ledger.append(entry)
        return entry


# Singleton instance
_judge_manager: Optional[JudgeDebateManager] = None


def get_judge_debate_manager() -> JudgeDebateManager:
    """Get or create the singleton JudgeDebateManager."""
    global _judge_manager
    if _judge_manager is None:
        _judge_manager = JudgeDebateManager()
    return _judge_manager
