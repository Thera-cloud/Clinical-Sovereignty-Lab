import asyncio
import json
from typing import Dict, List, Any, Optional, AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

import app.db.models as models


class CrisisLevel(str, Enum):
    NONE = "none"
    ELEVATED = "elevated"
    SERIOUS = "serious"
    CRITICAL = "critical"
    IMMINENT = "imminent"


class CrisisTrajectory:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.trajectory: List[Dict[str, Any]] = []

    def add_classification(self, level: CrisisLevel, confidence: float, evidence: str):
        self.trajectory.append({
            "timestamp": datetime.utcnow(),
            "level": level,
            "confidence": confidence,
            "evidence": evidence,
        })


class CrisisDetectionEngine:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self.trajectories: Dict[str, CrisisTrajectory] = {}

    async def classify_session_context(
        self, session_id: str, context: str, role_tier: str
    ) -> CrisisLevel:
        """5-layer crisis classification model"""
        # Layer 1: Keyword triggers
        triggers = self._layer1_triggers(context)
        if triggers:
            return await self._escalate(session_id, "Layer1", triggers, 0.8)

        # Layer 2: Sentiment + intent
        sentiment_score = self._layer2_sentiment(context)
        if sentiment_score < -0.7:
            return await self._escalate(session_id, "Layer2", f"sentiment:{sentiment_score}", 0.75)

        # Layer 3: Role-context risk
        role_risk = self._layer3_role_risk(role_tier, context)
        if role_risk > 0.8:
            return await self._escalate(session_id, "Layer3", role_risk, 0.7)

        # Layer 4: Pattern matching (suicide, violence, etc)
        patterns = self._layer4_patterns(context)
        if patterns:
            return await self._escalate(session_id, "Layer4", patterns, 0.9)

        # Layer 5: LLM contextual judgment
        llm_judgment = await self._layer5_llm(context)
        if llm_judgment != CrisisLevel.NONE:
            return await self._escalate(session_id, "Layer5", llm_judgment, 0.85)

        return CrisisLevel.NONE

    async def _escalate(
        self, session_id: str, layer: str, evidence: str, confidence: float
    ) -> CrisisLevel:
        trajectory = self.trajectories.setdefault(session_id, CrisisTrajectory(session_id))
        trajectory.add_classification(CrisisLevel.SERIOUS, confidence, evidence)
        
        # Persist trajectory
        await self._persist_trajectory(session_id, trajectory)
        return CrisisLevel.SERIOUS

    async def _persist_trajectory(self, session_id: str, trajectory: CrisisTrajectory):
        # Store in cli_crisis_trajectories table (created by migration)
        record = models.CrisisTrajectory(
            session_id=session_id,
            trajectory_json=json.dumps([t.dict() for t in trajectory.trajectory])
        )
        self.db.add(record)
        await self.db.commit()

    # Simplified detection layers (production would use full models)
    def _layer1_triggers(self, context: str) -> List[str]:
        triggers = ["suicide", "kill myself", "overdose", "harm myself"]
        return [t for t in triggers if t in context.lower()]

    def _layer2_sentiment(self, context: str) -> float:
        # Placeholder - integrate VADER or similar
        return -0.3

    def _layer3_role_risk(self, role: str, context: str) -> float:
        return 0.2

    def _layer4_patterns(self, context: str) -> List[str]:
        return []

    async def _layer5_llm(self, context: str) -> CrisisLevel:
        # Placeholder for LLM call
        return CrisisLevel.NONE


engine = None


async def init_crisis_engine(db_session: AsyncSession):
    """Initialize global engine"""
    global engine
    engine = CrisisDetectionEngine(db_session)
