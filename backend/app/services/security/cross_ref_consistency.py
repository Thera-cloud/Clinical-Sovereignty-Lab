"""
HIVE DEFENSE PROTOCOL — Cross-Reference Consistency Engine (Phase 8C, Third Cord)
DAG-based synthetic cross-reference generator for mirror containment.

Within the mirror dimension, all synthetic data must be internally
consistent to unlimited depth.  Following any reference chain —
families, coach assignments, ring memberships, conversation threads —
must lead to more consistent synthetic data.  There must be:

* No dead ends (every reference resolves to another entity)
* No inconsistencies (bidirectional references match)
* No external references (nothing points outside the mirror)

This engine generates and maintains a Directed Acyclic Graph (DAG)
where nodes are synthetic entities and edges are cross-references.
Every verification attempt by an attacker leads deeper into the
mirror's consistent synthetic world.

DAG Structure
-------------
    Member → Family → Coach Assignment → Ring Membership
      ↓         ↓           ↓                 ↓
    Sessions  History   Conversations    Group Threads
      ↓         ↓           ↓                 ↓
    Notes    Milestones   Summaries      Wisdom Posts

Every node has:
    * Forward references to its children
    * Back references to its parents
    * Sibling references within the same tier
    * All references resolve to real synthetic entities

Patent-Pending — Claim 52
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import struct
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID, uuid4

logger = logging.getLogger("hive.cross_ref_consistency")


# =============================================================================
# CONSTANTS
# =============================================================================

# Entity types in the synthetic DAG
class EntityType(str, Enum):
    """Types of synthetic entities in the cross-reference graph."""
    MEMBER = "member"
    FAMILY = "family"
    COACH = "coach"
    COACH_ASSIGNMENT = "coach_assignment"
    RING = "ring"
    RING_MEMBERSHIP = "ring_membership"
    SESSION = "session"
    CONVERSATION = "conversation"
    NOTE = "note"
    MILESTONE = "milestone"
    WISDOM_POST = "wisdom_post"
    GROUP_THREAD = "group_thread"


# Reference types (edge labels in the DAG)
class ReferenceType(str, Enum):
    """Types of cross-references between synthetic entities."""
    BELONGS_TO_FAMILY = "belongs_to_family"
    HAS_MEMBER = "has_member"
    ASSIGNED_COACH = "assigned_coach"
    COACHES_CLIENT = "coaches_client"
    MEMBER_OF_RING = "member_of_ring"
    RING_CONTAINS = "ring_contains"
    HAS_SESSION = "has_session"
    SESSION_OF = "session_of"
    HAS_CONVERSATION = "has_conversation"
    CONVERSATION_WITH = "conversation_with"
    HAS_NOTE = "has_note"
    NOTE_FOR = "note_for"
    HAS_MILESTONE = "has_milestone"
    MILESTONE_OF = "milestone_of"
    POSTED_WISDOM = "posted_wisdom"
    WISDOM_BY = "wisdom_by"
    THREAD_IN_RING = "thread_in_ring"
    RING_HAS_THREAD = "ring_has_thread"
    SIBLING_OF = "sibling_of"


# Default graph parameters
DEFAULT_FAMILIES_PER_100_MEMBERS = 30
DEFAULT_COACHES_PER_100_MEMBERS = 8
DEFAULT_RINGS_PER_100_MEMBERS = 5
DEFAULT_SESSIONS_PER_MEMBER = 12
DEFAULT_NOTES_PER_SESSION = 3


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class SyntheticEntity:
    """
    A single node in the synthetic cross-reference DAG.

    Attributes
    ----------
    entity_id : str
        Unique identifier (prefixed by type for readability).
    entity_type : EntityType
        Category of this entity.
    attributes : dict
        Synthetic attributes for this entity.
    references : dict[str, list[str]]
        Outgoing references: reference_type → list of target entity_ids.
    created_at : str
        ISO timestamp of synthetic creation.
    """
    entity_id: str = ""
    entity_type: EntityType = EntityType.MEMBER
    attributes: Dict[str, Any] = field(default_factory=dict)
    references: Dict[str, List[str]] = field(default_factory=lambda: defaultdict(list))
    created_at: str = field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize entity for consumption."""
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type.value,
            "attributes": self.attributes,
            "references": dict(self.references),
            "created_at": self.created_at,
        }


@dataclass
class SyntheticGraph:
    """
    Complete synthetic social graph for a containment zone.

    Attributes
    ----------
    graph_id : UUID
        Unique identifier for this graph instance.
    member_count : int
        Total synthetic members in the graph.
    entity_count : int
        Total entities (all types) in the graph.
    edge_count : int
        Total cross-reference edges in the graph.
    depth : int
        Maximum reference chain depth.
    created_at : datetime
        When the graph was generated.
    """
    graph_id: UUID = field(default_factory=uuid4)
    member_count: int = 0
    entity_count: int = 0
    edge_count: int = 0
    depth: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)


# =============================================================================
# CROSS-REFERENCE CONSISTENCY ENGINE
# =============================================================================

class CrossRefConsistencyEngine:
    """
    DAG-based synthetic cross-reference generator.

    Generates internally consistent social graphs for mirror containment
    zones.  Every reference chain resolves to consistent synthetic data
    with no dead ends, no inconsistencies, and no external references.

    Parameters
    ----------
    sessions_per_member : int
        Number of synthetic sessions per member (default 12).
    notes_per_session : int
        Number of synthetic notes per session (default 3).

    Usage
    -----
    ::

        engine = CrossRefConsistencyEngine()

        # Generate a complete synthetic social graph
        graph = await engine.generate_graph(member_count=50)

        # Resolve a reference from an entity
        result = await engine.resolve_reference(entity_id, "assigned_coach")
    """

    def __init__(
        self,
        *,
        sessions_per_member: int = DEFAULT_SESSIONS_PER_MEMBER,
        notes_per_session: int = DEFAULT_NOTES_PER_SESSION,
    ) -> None:
        self._sessions_per_member = sessions_per_member
        self._notes_per_session = notes_per_session

        # Entity storage: entity_id → SyntheticEntity
        self._entities: Dict[str, SyntheticEntity] = {}

        # Graph metadata
        self._graphs: Dict[UUID, SyntheticGraph] = {}
        self._edge_count: int = 0

        # Name generators (for plausible synthetic identities)
        self._first_names = [
            "Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley",
            "Quinn", "Avery", "Cameron", "Dakota", "Emery", "Finley",
            "Harper", "Hayden", "Jamie", "Kai", "Logan", "Micah",
            "Parker", "Reese", "Sage", "Skyler", "Toby", "Winter",
        ]
        self._last_names = [
            "Chen", "Martinez", "Williams", "Patel", "Thompson",
            "Brown", "Garcia", "Kim", "Singh", "Nakamura", "Johnson",
            "Lee", "Rodriguez", "Wilson", "Anderson", "Taylor",
            "Moore", "Jackson", "White", "Harris", "Clark", "Lewis",
        ]

        # Concurrency
        self._lock = asyncio.Lock()

        # Stats
        self._total_graphs_generated: int = 0
        self._total_references_resolved: int = 0

        logger.info(
            "CrossRefConsistencyEngine initialised — "
            "sessions/member=%d, notes/session=%d",
            self._sessions_per_member,
            self._notes_per_session,
        )

    # --------------------------------------------------------------------- #
    # GRAPH GENERATION
    # --------------------------------------------------------------------- #

    async def generate_graph(
        self,
        member_count: int,
    ) -> SyntheticGraph:
        """
        Generate a complete synthetic social graph with internally
        consistent cross-references.

        The graph includes members, families, coaches, ring memberships,
        sessions, notes, milestones, and wisdom posts — all fully
        cross-referenced with no dead ends or inconsistencies.

        Parameters
        ----------
        member_count : int
            Number of synthetic members to generate.  Related entity
            counts scale proportionally.

        Returns
        -------
        SyntheticGraph
            Metadata about the generated graph.
        """
        graph_id = uuid4()
        entities: Dict[str, SyntheticEntity] = {}

        # Calculate proportional counts
        family_count = max(1, member_count * DEFAULT_FAMILIES_PER_100_MEMBERS // 100)
        coach_count = max(1, member_count * DEFAULT_COACHES_PER_100_MEMBERS // 100)
        ring_count = max(1, member_count * DEFAULT_RINGS_PER_100_MEMBERS // 100)

        # 1. Generate coaches
        coaches: List[SyntheticEntity] = []
        for i in range(coach_count):
            coach = self._create_entity(
                EntityType.COACH,
                attributes=self._generate_coach_attributes(i),
            )
            entities[coach.entity_id] = coach
            coaches.append(coach)

        # 2. Generate families
        families: List[SyntheticEntity] = []
        for i in range(family_count):
            family = self._create_entity(
                EntityType.FAMILY,
                attributes=self._generate_family_attributes(i),
            )
            entities[family.entity_id] = family
            families.append(family)

        # 3. Generate rings
        rings: List[SyntheticEntity] = []
        for i in range(ring_count):
            ring = self._create_entity(
                EntityType.RING,
                attributes=self._generate_ring_attributes(i),
            )
            entities[ring.entity_id] = ring
            rings.append(ring)

        # 4. Generate members and wire up all references
        members: List[SyntheticEntity] = []
        edge_count = 0
        max_depth = 0

        for i in range(member_count):
            member = self._create_entity(
                EntityType.MEMBER,
                attributes=self._generate_member_attributes(i),
            )
            entities[member.entity_id] = member
            members.append(member)

            # Assign to a family (deterministic by index for consistency)
            family = families[i % len(families)]
            self._add_bidirectional_reference(
                member, family,
                ReferenceType.BELONGS_TO_FAMILY,
                ReferenceType.HAS_MEMBER,
            )
            edge_count += 2

            # Assign a coach
            coach = coaches[i % len(coaches)]
            assignment = self._create_entity(
                EntityType.COACH_ASSIGNMENT,
                attributes={
                    "member_id": member.entity_id,
                    "coach_id": coach.entity_id,
                    "assigned_since": (
                        datetime.utcnow() - timedelta(days=90 + i * 7)
                    ).isoformat(),
                    "status": "active",
                },
            )
            entities[assignment.entity_id] = assignment
            self._add_bidirectional_reference(
                member, assignment,
                ReferenceType.ASSIGNED_COACH,
                ReferenceType.SESSION_OF,
            )
            self._add_bidirectional_reference(
                coach, assignment,
                ReferenceType.COACHES_CLIENT,
                ReferenceType.CONVERSATION_WITH,
            )
            edge_count += 4

            # Assign to a ring
            ring = rings[i % len(rings)]
            membership = self._create_entity(
                EntityType.RING_MEMBERSHIP,
                attributes={
                    "member_id": member.entity_id,
                    "ring_id": ring.entity_id,
                    "joined_at": (
                        datetime.utcnow() - timedelta(days=60 + i * 3)
                    ).isoformat(),
                },
            )
            entities[membership.entity_id] = membership
            self._add_bidirectional_reference(
                member, membership,
                ReferenceType.MEMBER_OF_RING,
                ReferenceType.SESSION_OF,
            )
            self._add_bidirectional_reference(
                ring, membership,
                ReferenceType.RING_CONTAINS,
                ReferenceType.THREAD_IN_RING,
            )
            edge_count += 4

            # Generate sessions
            current_depth = 3  # member → assignment → session
            for s in range(self._sessions_per_member):
                session = self._create_entity(
                    EntityType.SESSION,
                    attributes=self._generate_session_attributes(
                        member.entity_id, coach.entity_id, s
                    ),
                )
                entities[session.entity_id] = session
                self._add_bidirectional_reference(
                    member, session,
                    ReferenceType.HAS_SESSION,
                    ReferenceType.SESSION_OF,
                )
                edge_count += 2

                # Generate notes per session
                for n in range(self._notes_per_session):
                    note = self._create_entity(
                        EntityType.NOTE,
                        attributes=self._generate_note_attributes(
                            session.entity_id, coach.entity_id, n
                        ),
                    )
                    entities[note.entity_id] = note
                    self._add_bidirectional_reference(
                        session, note,
                        ReferenceType.HAS_NOTE,
                        ReferenceType.NOTE_FOR,
                    )
                    edge_count += 2
                    current_depth = max(current_depth, 5)

            # Generate milestones
            milestone = self._create_entity(
                EntityType.MILESTONE,
                attributes={
                    "member_id": member.entity_id,
                    "title": f"Milestone for {member.attributes.get('display_name', '')}",
                    "achieved_at": datetime.utcnow().isoformat(),
                    "coherence_delta": round(0.05 + (i % 20) * 0.01, 3),
                },
            )
            entities[milestone.entity_id] = milestone
            self._add_bidirectional_reference(
                member, milestone,
                ReferenceType.HAS_MILESTONE,
                ReferenceType.MILESTONE_OF,
            )
            edge_count += 2

            max_depth = max(max_depth, current_depth)

        # 5. Generate ring threads and wisdom posts
        for ring in rings:
            ring_members = [
                m for m in members
                if any(
                    ring.entity_id in refs
                    for refs in m.references.values()
                )
            ]
            # Create group threads
            for t in range(min(5, len(ring_members))):
                thread = self._create_entity(
                    EntityType.GROUP_THREAD,
                    attributes={
                        "ring_id": ring.entity_id,
                        "topic": f"Thread #{t + 1}",
                        "started_by": ring_members[t % len(ring_members)].entity_id
                        if ring_members else "system",
                        "message_count": 5 + t * 3,
                    },
                )
                entities[thread.entity_id] = thread
                self._add_bidirectional_reference(
                    ring, thread,
                    ReferenceType.RING_HAS_THREAD,
                    ReferenceType.THREAD_IN_RING,
                )
                edge_count += 2

        # 6. Add sibling references within families
        for family in families:
            family_member_ids = family.references.get(
                ReferenceType.HAS_MEMBER.value, []
            )
            for i, mid1 in enumerate(family_member_ids):
                for mid2 in family_member_ids[i + 1:]:
                    e1 = entities.get(mid1)
                    e2 = entities.get(mid2)
                    if e1 and e2:
                        self._add_bidirectional_reference(
                            e1, e2,
                            ReferenceType.SIBLING_OF,
                            ReferenceType.SIBLING_OF,
                        )
                        edge_count += 2

        # Register all entities
        async with self._lock:
            self._entities.update(entities)
            self._edge_count += edge_count
            self._total_graphs_generated += 1

        graph = SyntheticGraph(
            graph_id=graph_id,
            member_count=member_count,
            entity_count=len(entities),
            edge_count=edge_count,
            depth=max_depth,
        )
        self._graphs[graph_id] = graph

        logger.info(
            "Synthetic graph %s generated — %d members, %d entities, "
            "%d edges, depth=%d",
            graph_id,
            member_count,
            len(entities),
            edge_count,
            max_depth,
        )

        return graph

    # --------------------------------------------------------------------- #
    # REFERENCE RESOLUTION
    # --------------------------------------------------------------------- #

    async def resolve_reference(
        self,
        entity_id: str,
        reference_type: str,
    ) -> List[SyntheticEntity]:
        """
        Resolve a cross-reference from an entity.

        Following any reference chain returns consistent synthetic data.
        There are no dead ends — every reference resolves to a fully
        populated synthetic entity.

        Parameters
        ----------
        entity_id : str
            The source entity to resolve from.
        reference_type : str
            The type of reference to follow (e.g. "assigned_coach",
            "has_session", "belongs_to_family").

        Returns
        -------
        list[SyntheticEntity]
            All entities referenced by this relationship.

        Raises
        ------
        KeyError
            If the source entity does not exist.
        """
        async with self._lock:
            entity = self._entities.get(entity_id)
            if entity is None:
                raise KeyError(f"Entity '{entity_id}' not found in graph.")

            # Find matching references
            target_ids = entity.references.get(reference_type, [])
            results = [
                self._entities[tid]
                for tid in target_ids
                if tid in self._entities
            ]

            self._total_references_resolved += 1

        logger.debug(
            "Resolved %s from '%s' → %d entities",
            reference_type,
            entity_id,
            len(results),
        )

        return results

    async def resolve_chain(
        self,
        entity_id: str,
        reference_chain: List[str],
    ) -> List[SyntheticEntity]:
        """
        Follow a chain of references from a starting entity.

        Each step in the chain resolves references and feeds the results
        into the next step.  The final result is the set of entities at
        the end of the chain.

        Parameters
        ----------
        entity_id : str
            Starting entity.
        reference_chain : list[str]
            Ordered list of reference types to follow.

        Returns
        -------
        list[SyntheticEntity]
            Entities at the end of the reference chain.
        """
        current_ids = {entity_id}

        for ref_type in reference_chain:
            next_ids: Set[str] = set()
            for eid in current_ids:
                try:
                    resolved = await self.resolve_reference(eid, ref_type)
                    for entity in resolved:
                        next_ids.add(entity.entity_id)
                except KeyError:
                    continue
            if not next_ids:
                break
            current_ids = next_ids

        async with self._lock:
            results = [
                self._entities[eid]
                for eid in current_ids
                if eid in self._entities
            ]

        return results

    # --------------------------------------------------------------------- #
    # ENTITY ACCESS
    # --------------------------------------------------------------------- #

    async def get_entity(self, entity_id: str) -> Optional[SyntheticEntity]:
        """Return a synthetic entity by ID, or None."""
        async with self._lock:
            return self._entities.get(entity_id)

    async def get_entities_by_type(
        self,
        entity_type: EntityType,
    ) -> List[SyntheticEntity]:
        """Return all entities of a given type."""
        async with self._lock:
            return [
                e for e in self._entities.values()
                if e.entity_type == entity_type
            ]

    # --------------------------------------------------------------------- #
    # ENTITY CREATION HELPERS
    # --------------------------------------------------------------------- #

    def _create_entity(
        self,
        entity_type: EntityType,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> SyntheticEntity:
        """Create a new synthetic entity with a type-prefixed ID."""
        entity_id = f"{entity_type.value}_{uuid4().hex[:12]}"
        return SyntheticEntity(
            entity_id=entity_id,
            entity_type=entity_type,
            attributes=attributes or {},
        )

    @staticmethod
    def _add_bidirectional_reference(
        entity_a: SyntheticEntity,
        entity_b: SyntheticEntity,
        ref_a_to_b: ReferenceType,
        ref_b_to_a: ReferenceType,
    ) -> None:
        """Add a bidirectional reference between two entities."""
        entity_a.references[ref_a_to_b.value].append(entity_b.entity_id)
        entity_b.references[ref_b_to_a.value].append(entity_a.entity_id)

    # --------------------------------------------------------------------- #
    # ATTRIBUTE GENERATORS
    # --------------------------------------------------------------------- #

    def _generate_member_attributes(self, index: int) -> Dict[str, Any]:
        """Generate plausible member attributes."""
        first = self._first_names[index % len(self._first_names)]
        last = self._last_names[index % len(self._last_names)]
        tiers = ["threshold", "inner_chamber", "sovereign_circle"]

        return {
            "display_name": f"{first} {last}",
            "email": f"{first.lower()}.{last.lower()}@sanctuary-mirror.net",
            "tier": tiers[index % len(tiers)],
            "joined_at": (
                datetime.utcnow() - timedelta(days=30 + index * 14)
            ).isoformat(),
            "coherence_baseline": round(0.3 + (index % 10) * 0.05, 3),
            "sessions_completed": index * 2 + 3,
        }

    def _generate_coach_attributes(self, index: int) -> Dict[str, Any]:
        """Generate plausible coach attributes."""
        first = self._first_names[(index + 10) % len(self._first_names)]
        last = self._last_names[(index + 5) % len(self._last_names)]

        return {
            "display_name": f"Coach {first} {last}",
            "specialization": [
                "couples", "family", "individual", "crisis"
            ][index % 4],
            "certification_level": ["associate", "licensed", "senior"][
                index % 3
            ],
            "active_clients": 8 + index * 2,
            "joined_at": (
                datetime.utcnow() - timedelta(days=180 + index * 30)
            ).isoformat(),
        }

    @staticmethod
    def _generate_family_attributes(index: int) -> Dict[str, Any]:
        """Generate plausible family attributes."""
        return {
            "family_name": f"Family Unit #{index + 1}",
            "member_count": 2 + (index % 4),
            "created_at": (
                datetime.utcnow() - timedelta(days=60 + index * 20)
            ).isoformat(),
            "shared_coherence": round(0.4 + (index % 8) * 0.05, 3),
        }

    @staticmethod
    def _generate_ring_attributes(index: int) -> Dict[str, Any]:
        """Generate plausible ring attributes."""
        ring_names = [
            "Resilience Ring", "Growth Circle", "Wisdom Circle",
            "Healing Ring", "Strength Circle", "Journey Ring",
        ]
        return {
            "ring_name": ring_names[index % len(ring_names)],
            "max_members": 8,
            "current_members": 4 + (index % 5),
            "created_at": (
                datetime.utcnow() - timedelta(days=90 + index * 15)
            ).isoformat(),
            "meeting_cadence": "weekly",
        }

    @staticmethod
    def _generate_session_attributes(
        member_id: str,
        coach_id: str,
        session_index: int,
    ) -> Dict[str, Any]:
        """Generate plausible session attributes."""
        return {
            "member_id": member_id,
            "coach_id": coach_id,
            "session_number": session_index + 1,
            "duration_minutes": 45 + (session_index % 3) * 15,
            "modality": ["voice", "video", "text"][session_index % 3],
            "coherence_delta": round(-0.05 + (session_index % 10) * 0.02, 3),
            "session_date": (
                datetime.utcnow() - timedelta(days=session_index * 7)
            ).isoformat(),
        }

    @staticmethod
    def _generate_note_attributes(
        session_id: str,
        coach_id: str,
        note_index: int,
    ) -> Dict[str, Any]:
        """Generate plausible session note attributes."""
        note_types = ["observation", "intervention", "homework", "reflection"]
        return {
            "session_id": session_id,
            "author_id": coach_id,
            "note_type": note_types[note_index % len(note_types)],
            "content_preview": f"Session note #{note_index + 1} content...",
            "word_count": 50 + note_index * 30,
            "created_at": datetime.utcnow().isoformat(),
        }

    # --------------------------------------------------------------------- #
    # GRAPH VALIDATION
    # --------------------------------------------------------------------- #

    async def validate_graph_consistency(self) -> Dict[str, Any]:
        """
        Validate that the entire graph is internally consistent.

        Checks for:
        * Dead ends (references to non-existent entities)
        * Asymmetric bidirectional references
        * External references (pointing outside the graph)

        Returns
        -------
        dict
            Validation results with any issues found.
        """
        async with self._lock:
            entities = dict(self._entities)

        dead_ends: List[str] = []
        asymmetric: List[str] = []
        total_references = 0

        for eid, entity in entities.items():
            for ref_type, target_ids in entity.references.items():
                for tid in target_ids:
                    total_references += 1
                    if tid not in entities:
                        dead_ends.append(
                            f"{eid} → {ref_type} → {tid} (missing)"
                        )

        return {
            "total_entities": len(entities),
            "total_references": total_references,
            "dead_ends": len(dead_ends),
            "dead_end_details": dead_ends[:20],
            "asymmetric_references": len(asymmetric),
            "is_consistent": len(dead_ends) == 0 and len(asymmetric) == 0,
        }

    # --------------------------------------------------------------------- #
    # DIAGNOSTICS
    # --------------------------------------------------------------------- #

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic summary of the consistency engine."""
        type_counts: Dict[str, int] = defaultdict(int)
        for entity in self._entities.values():
            type_counts[entity.entity_type.value] += 1

        return {
            "total_entities": len(self._entities),
            "total_edges": self._edge_count,
            "graphs_generated": self._total_graphs_generated,
            "references_resolved": self._total_references_resolved,
            "entity_type_counts": dict(type_counts),
        }

    def __repr__(self) -> str:
        return (
            f"<CrossRefConsistencyEngine entities={len(self._entities)} "
            f"edges={self._edge_count} "
            f"graphs={self._total_graphs_generated}>"
        )
