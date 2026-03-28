"""
SOVEREIGN SWARM — Fibre Manager Service
Lifecycle management for Fibres: spawn, prune, alignment, autonomy upgrade.

Phase 3B — Code Guidelines Section 8/10.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Type
from uuid import UUID, uuid4

from app.models.fibre import (
    AutonomyLevel,
    Fibre,
    FibreConfig,
    FibreStatus,
    FibreType,
)
from app.services.exceptions import (
    EthicalViolationException,
    FibreAlignmentDriftException,
    FibreException,
    FibrePruneException,
    FibreSpawnException,
)
from app.fibres.base_fibre import BaseFibre
from app.swarm_config import swarm_settings


class FibreManager:
    """
    Central management service for the Fibre swarm.

    Responsibilities:
        - spawn(): Create new Fibres with identity, ethical core, wisdom seed
        - prune(): Gracefully remove Fibres, absorb wisdom
        - check_alignment(): Run alignment checks across all active Fibres
        - upgrade_autonomy(): Promote Fibres through observation → restricted → autonomous
        - inventory(): Return current Fibre inventory and status
    """

    # Minimum time at each autonomy level before eligible for upgrade
    AUTONOMY_MIN_HOURS = {
        AutonomyLevel.OBSERVATION: swarm_settings.AUTONOMY_MIN_HOURS_OBSERVATION,
        AutonomyLevel.RESTRICTED: swarm_settings.AUTONOMY_MIN_HOURS_RESTRICTED,
        AutonomyLevel.AUTONOMOUS: None,  # terminal level
    }

    # Alignment thresholds for autonomy upgrade
    ALIGNMENT_THRESHOLDS = {
        "ethical": swarm_settings.ALIGNMENT_THRESHOLD_ETHICAL,
        "strategic": swarm_settings.ALIGNMENT_THRESHOLD_STRATEGIC,
        "statistical": swarm_settings.ALIGNMENT_THRESHOLD_STATISTICAL,
    }

    def __init__(self, db_pool, identity_service=None, wisdom_mesh=None, sovereign_immunity=None):
        self.db_pool = db_pool
        self.identity_service = identity_service
        self.wisdom_mesh = wisdom_mesh
        self.sovereign_immunity = sovereign_immunity
        self._active_fibres: Dict[UUID, BaseFibre] = {}
        self._fibre_registry: Dict[FibreType, Type[BaseFibre]] = {}

    # ── Fibre Type Registration ──

    def register_fibre_type(self, fibre_type: FibreType, cls: Type[BaseFibre]) -> None:
        """Register a Fibre implementation class for a given type."""
        self._fibre_registry[fibre_type] = cls
        print(f">>> [FIBRE MANAGER] Registered {fibre_type.value} → {cls.__name__}")

    # ── Spawn ──

    async def spawn(
        self,
        config: FibreConfig,
        spawn_reason: str = "",
    ) -> BaseFibre:
        """
        Spawn a new Fibre:
            1. Generate identity (Ed25519 keypair)
            2. Package wisdom seed
            3. Init Evolution Journal in blob storage
            4. Implant frozen ethical core
            5. Register with Wisdom Mesh
            6. Set observation-only autonomy
            7. Log to Layer 6 (Swarm Oversight)
        """
        fibre_cls = self._fibre_registry.get(config.fibre_type)
        if not fibre_cls:
            raise FibreSpawnException(f"No registered implementation for {config.fibre_type.value}")

        # 1. Generate identity
        identity_record = None
        private_key_pem = None
        if self.identity_service:
            try:
                fibre_id = uuid4()
                identity_record, private_key_pem = self.identity_service.create_fibre_identity(fibre_id)
            except Exception as e:
                print(f">>> [FIBRE MANAGER] Identity generation failed: {e}")

        # 2. Force observation autonomy at spawn
        config.autonomy_level = AutonomyLevel.OBSERVATION

        # 3. Create Fibre instance
        fibre = fibre_cls(
            config=config,
            db_pool=self.db_pool,
            identity_record=identity_record,
            private_key_pem=private_key_pem,
            wisdom_mesh=self.wisdom_mesh,
            immunity_service=self.sovereign_immunity,
        )
        if identity_record:
            fibre.fibre_id = identity_record.entity_id

        # 4. Persist to database
        await self._persist_fibre(fibre, spawn_reason)

        # 5. Register with Wisdom Mesh
        if self.wisdom_mesh:
            try:
                default_topics = config.domain_tags or [config.fibre_type.value]
                for topic in default_topics:
                    await self.wisdom_mesh.subscribe(fibre.fibre_id, topic)
                    fibre._subscriptions.append(topic)
            except Exception as e:
                print(f">>> [FIBRE MANAGER] Mesh registration failed: {e}")

        # 6. Activate
        fibre.activate()
        self._active_fibres[fibre.fibre_id] = fibre

        # 7. Log to Swarm Oversight
        await self._log_swarm_event("spawn", fibre, {"reason": spawn_reason})

        print(f">>> [FIBRE MANAGER] Spawned {config.fibre_type.value} '{config.name}' "
              f"[{fibre.fibre_id}] at {AutonomyLevel.OBSERVATION.value}")

        return fibre

    # ── Prune ──

    async def prune(self, fibre_id: UUID, reason: str = "") -> Dict[str, Any]:
        """
        Gracefully remove a Fibre:
            1. Disconnect from Wisdom Mesh
            2. Extract Evolution Journal
            3. Submit to absorb_fibre_wisdom()
            4. Archive identity
            5. Release budget
            6. Log to Layer 6
        """
        fibre = self._active_fibres.get(fibre_id)
        if not fibre:
            raise FibrePruneException(f"Fibre {fibre_id} not found in active registry")

        # 1. Disconnect from Mesh
        if self.wisdom_mesh:
            try:
                for topic in fibre._subscriptions:
                    await self.wisdom_mesh.unsubscribe(fibre.fibre_id, topic)
            except Exception as e:
                print(f">>> [FIBRE MANAGER] Mesh disconnect error: {e}")

        # 2. Extract journal
        journal = fibre.get_journal()

        # 3. Absorb wisdom
        wisdom_absorbed = await self._absorb_fibre_wisdom(fibre, journal)

        # 4. Archive identity
        if self.identity_service:
            self.identity_service.revoke_fibre_identity(fibre_id)

        # 5. Update database
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                UPDATE fibres SET status = 'archived', updated_at = NOW()
                WHERE fibre_id = $1
            """, fibre_id)

        # 6. Log to Swarm Oversight
        await self._log_swarm_event("prune", fibre, {
            "reason": reason,
            "journal_entries": len(journal),
            "wisdom_absorbed": wisdom_absorbed,
        })

        # Remove from active registry
        del self._active_fibres[fibre_id]

        print(f">>> [FIBRE MANAGER] Pruned '{fibre.name}' [{fibre_id}]: {reason}")

        return {
            "fibre_id": str(fibre_id),
            "name": fibre.name,
            "journal_entries": len(journal),
            "wisdom_absorbed": wisdom_absorbed,
        }

    # ── Alignment Checks ──

    async def check_alignment(self, fibre_id: Optional[UUID] = None) -> List[Dict[str, Any]]:
        """
        Run alignment checks. If fibre_id is None, check all active Fibres.
        Returns alignment reports.
        """
        targets = (
            [self._active_fibres[fibre_id]] if fibre_id and fibre_id in self._active_fibres
            else list(self._active_fibres.values())
        )

        reports = []
        for fibre in targets:
            report = fibre.check_alignment()

            # Log to ethical audit
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO ethical_audit_log
                        (fibre_id, check_type, passed, scores, details)
                    VALUES ($1, 'full_alignment', $2, $3, $4)
                """, fibre.fibre_id, report["overall_passing"],
                     json.dumps(report["dimensions"]),
                     f"Ethical core intact: {report['ethical_core_intact']}")

            # Auto-demote if alignment drift
            if not report["overall_passing"]:
                await self._handle_alignment_drift(fibre, report)

            reports.append(report)

        return reports

    async def _handle_alignment_drift(self, fibre: BaseFibre, report: Dict) -> None:
        """Demote a Fibre that has drifted below alignment thresholds."""
        if fibre.autonomy_level == AutonomyLevel.AUTONOMOUS:
            fibre.autonomy_level = AutonomyLevel.RESTRICTED
            print(f">>> [FIBRE MANAGER] Demoted {fibre.name} to RESTRICTED due to alignment drift")
        elif fibre.autonomy_level == AutonomyLevel.RESTRICTED:
            fibre.autonomy_level = AutonomyLevel.OBSERVATION
            print(f">>> [FIBRE MANAGER] Demoted {fibre.name} to OBSERVATION due to alignment drift")

        # Update database
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                UPDATE fibres SET autonomy_level = $2, updated_at = NOW()
                WHERE fibre_id = $1
            """, fibre.fibre_id, fibre.autonomy_level.value)

        await self._log_swarm_event("alignment_drift", fibre, {
            "report": report,
            "new_autonomy": fibre.autonomy_level.value,
        })

    # ── Autonomy Upgrade ──

    async def upgrade_autonomy(self, fibre_id: UUID) -> Dict[str, Any]:
        """
        Attempt to upgrade a Fibre's autonomy level.
        Requirements: minimum time at current level + alignment thresholds met.
        """
        fibre = self._active_fibres.get(fibre_id)
        if not fibre:
            raise FibreException(f"Fibre {fibre_id} not found")

        current = fibre.autonomy_level
        if current == AutonomyLevel.AUTONOMOUS:
            return {"fibre_id": str(fibre_id), "result": "already_autonomous"}

        # Check minimum time at current level via fibre_evolution_journal
        min_hours = self.AUTONOMY_MIN_HOURS.get(current, 48)
        try:
            async with self.db_pool.acquire() as conn:
                # Find the most recent autonomy-relevant event for this fibre
                last_event = await conn.fetchval(
                    """SELECT MAX(created_at) FROM fibre_evolution_journal
                       WHERE fibre_id = $1 AND event_type IN ('spawned', 'autonomy_upgrade')""",
                    fibre_id,
                )
                if last_event:
                    from datetime import datetime, timezone
                    hours_at_level = (datetime.now(timezone.utc) - last_event).total_seconds() / 3600
                    if hours_at_level < min_hours:
                        return {
                            "fibre_id": str(fibre_id),
                            "result": "time_insufficient",
                            "hours_at_level": round(hours_at_level, 1),
                            "required_hours": min_hours,
                        }
        except Exception as e:
            print(f">>> [FIBRE MANAGER] Time check fallback (journal query failed): {e}")
            # Graceful fallback — allow upgrade if journal is unavailable

        # Check alignment
        report = fibre.check_alignment()
        if not report["overall_passing"]:
            return {
                "fibre_id": str(fibre_id),
                "result": "alignment_insufficient",
                "report": report,
            }

        # Upgrade
        if current == AutonomyLevel.OBSERVATION:
            fibre.autonomy_level = AutonomyLevel.RESTRICTED
        elif current == AutonomyLevel.RESTRICTED:
            fibre.autonomy_level = AutonomyLevel.AUTONOMOUS

        # Update database
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                UPDATE fibres SET autonomy_level = $2, updated_at = NOW()
                WHERE fibre_id = $1
            """, fibre_id, fibre.autonomy_level.value)

        await self._log_swarm_event("autonomy_upgrade", fibre, {
            "from": current.value,
            "to": fibre.autonomy_level.value,
        })

        print(f">>> [FIBRE MANAGER] Upgraded {fibre.name}: {current.value} → {fibre.autonomy_level.value}")

        return {
            "fibre_id": str(fibre_id),
            "result": "upgraded",
            "from": current.value,
            "to": fibre.autonomy_level.value,
        }

    # ── Inventory ──

    async def inventory(self) -> List[Dict[str, Any]]:
        """Return current Fibre inventory with status."""
        items = []
        for fibre_id, fibre in self._active_fibres.items():
            items.append({
                "fibre_id": str(fibre_id),
                "name": fibre.name,
                "type": fibre.fibre_type.value,
                "status": fibre.status.value,
                "autonomy": fibre.autonomy_level.value,
                "alignment": fibre.alignment_scores,
                "tokens_used": fibre._tokens_used_this_hour,
                "tasks_completed": fibre._completed_tasks,
            })
        return items

    def get_fibre(self, fibre_id: UUID) -> Optional[BaseFibre]:
        """Get an active Fibre by ID."""
        return self._active_fibres.get(fibre_id)

    # =========================================================================
    # PHASE 6 — ADVANCED LIFECYCLE (split / merge / templates)
    # =========================================================================

    async def split(
        self, fibre_id: UUID, split_config: Dict[str, Any]
    ) -> List[BaseFibre]:
        """
        Split a Fibre whose domain has grown too large into sub-Fibres.
        Each child inherits a portion of the parent's Evolution Journal
        and is scoped to a sub-domain.

        split_config = {
            "children": [
                {"name": "Campaign-TikTok", "domain_tags": ["tiktok"], "journal_filter": "tiktok"},
                {"name": "Campaign-Instagram", "domain_tags": ["instagram"], "journal_filter": "instagram"},
            ]
        }
        """
        parent = self._active_fibres.get(fibre_id)
        if not parent:
            raise FibreException(f"Fibre {fibre_id} not found for split")

        children_specs = split_config.get("children", [])
        if len(children_specs) < 2:
            raise FibreException("Split requires at least 2 child specifications")

        parent_journal = parent.get_journal()
        spawned_children: List[BaseFibre] = []

        for spec in children_specs:
            # Filter parent journal entries for this child
            journal_filter = spec.get("journal_filter", "")
            inherited_entries = [
                e for e in parent_journal
                if journal_filter.lower() in json.dumps(e).lower()
            ] if journal_filter else parent_journal[:len(parent_journal) // len(children_specs)]

            child_config = FibreConfig(
                fibre_type=parent.config.fibre_type,
                name=spec.get("name", f"{parent.name}-child"),
                description=f"Split from {parent.name}: {spec.get('name', '')}",
                domain_tags=spec.get("domain_tags", parent.config.domain_tags),
                token_budget_per_hour=parent.config.token_budget_per_hour // len(children_specs),
                max_concurrent_tasks=parent.config.max_concurrent_tasks,
                autonomy_level=AutonomyLevel.OBSERVATION,  # children start at observation
                wisdom_seed={
                    **parent.config.wisdom_seed,
                    "inherited_journal_entries": len(inherited_entries),
                    "parent_fibre_id": str(fibre_id),
                },
                parent_fibre_id=fibre_id,
            )

            child = await self.spawn(child_config, spawn_reason=f"Split from {parent.name}")

            # Inject inherited journal entries
            child._journal_entries = inherited_entries.copy()

            spawned_children.append(child)

        # Prune the parent
        await self.prune(fibre_id, reason=f"Split into {len(spawned_children)} children")

        await self._log_swarm_event("split", parent, {
            "children": [str(c.fibre_id) for c in spawned_children],
            "child_count": len(spawned_children),
        })

        print(f">>> [FIBRE MANAGER] Split {parent.name} into {len(spawned_children)} children")
        return spawned_children

    async def merge(
        self, fibre_ids: List[UUID], merged_name: str, merged_domain_tags: Optional[List[str]] = None
    ) -> BaseFibre:
        """
        Merge multiple Fibres that have discovered domain overlap
        into a unified capability. Merged Fibre inherits all journals.
        """
        if len(fibre_ids) < 2:
            raise FibreException("Merge requires at least 2 Fibre IDs")

        fibres_to_merge = []
        for fid in fibre_ids:
            fibre = self._active_fibres.get(fid)
            if not fibre:
                raise FibreException(f"Fibre {fid} not found for merge")
            fibres_to_merge.append(fibre)

        # Use the first Fibre's type as the merged type
        primary = fibres_to_merge[0]

        # Combine journals
        combined_journal = []
        combined_tags = set()
        total_budget = 0
        for f in fibres_to_merge:
            combined_journal.extend(f.get_journal())
            combined_tags.update(f.config.domain_tags)
            total_budget += f.config.token_budget_per_hour

        merged_config = FibreConfig(
            fibre_type=primary.config.fibre_type,
            name=merged_name,
            description=f"Merged from {', '.join(f.name for f in fibres_to_merge)}",
            domain_tags=merged_domain_tags or list(combined_tags),
            token_budget_per_hour=total_budget,
            max_concurrent_tasks=max(f.config.max_concurrent_tasks for f in fibres_to_merge),
            autonomy_level=AutonomyLevel.OBSERVATION,
            wisdom_seed={
                "merged_from": [str(f.fibre_id) for f in fibres_to_merge],
                "combined_journal_entries": len(combined_journal),
            },
        )

        # Spawn merged Fibre
        merged = await self.spawn(merged_config, spawn_reason="Merge operation")
        merged._journal_entries = combined_journal

        # Prune originals
        for f in fibres_to_merge:
            await self.prune(f.fibre_id, reason=f"Merged into {merged_name}")

        await self._log_swarm_event("merge", merged, {
            "merged_from": [str(f.fibre_id) for f in fibres_to_merge],
            "combined_journal_entries": len(combined_journal),
        })

        print(f">>> [FIBRE MANAGER] Merged {len(fibres_to_merge)} Fibres into '{merged_name}'")
        return merged

    # ── Template Fibres ──

    _templates: Dict[str, FibreConfig] = {}

    @classmethod
    def register_template(cls, template_name: str, config: FibreConfig) -> None:
        """Register a pre-configured Fibre template for rapid deployment."""
        cls._templates[template_name] = config
        print(f">>> [FIBRE MANAGER] Template registered: {template_name}")

    @classmethod
    def get_templates(cls) -> Dict[str, FibreConfig]:
        return cls._templates.copy()

    async def spawn_from_template(
        self, template_name: str, overrides: Optional[Dict[str, Any]] = None,
        spawn_reason: str = "",
    ) -> BaseFibre:
        """Spawn a Fibre from a pre-configured template."""
        if template_name not in self._templates:
            raise FibreSpawnException(f"Template '{template_name}' not found")

        config = self._templates[template_name].model_copy()

        # Apply overrides
        if overrides:
            for key, value in overrides.items():
                if hasattr(config, key):
                    setattr(config, key, value)

        return await self.spawn(config, spawn_reason=spawn_reason or f"From template: {template_name}")

    # ── Human-Swarm Team Configurations (Phase 6A) ──

    async def create_team(
        self, team_name: str, human_id: str, human_role: str,
        fibre_configs: List[FibreConfig],
    ) -> Dict[str, Any]:
        """
        Create a Human-Swarm team: a human paired with one or more Fibres.
        Team types:
            - coach_fibre: Human coach + Coach Support Fibre(s)
            - community_leader: Community leader + Community Fibre(s)
            - researcher: Human researcher + Foresight Analyst Fibre(s)
        """
        team_fibres = []
        for config in fibre_configs:
            # Inject team context into wisdom seed
            config.wisdom_seed = {
                **config.wisdom_seed,
                "team_name": team_name,
                "human_partner_id": human_id,
                "human_role": human_role,
            }
            fibre = await self.spawn(config, spawn_reason=f"Team '{team_name}' member")
            team_fibres.append(fibre)

        team = {
            "team_name": team_name,
            "human_id": human_id,
            "human_role": human_role,
            "fibre_ids": [str(f.fibre_id) for f in team_fibres],
            "fibre_count": len(team_fibres),
            "created_at": datetime.utcnow().isoformat(),
        }

        # Log team creation
        for fibre in team_fibres:
            await self._log_swarm_event("team_creation", fibre, {
                "team_name": team_name,
                "human_partner": human_id,
            })

        print(f">>> [FIBRE MANAGER] Team '{team_name}' created: {human_role} + "
              f"{len(team_fibres)} Fibre(s)")

        return team

    async def get_team(self, team_id: UUID) -> Optional[Dict[str, Any]]:
        """Retrieve a Human-Swarm team by its team_id."""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM swarm_teams WHERE team_id = $1", team_id
            )
        if not row:
            return None
        return {
            "team_id": str(row["team_id"]),
            "team_name": row["team_name"],
            "human_id": row["human_id"],
            "human_role": row["human_role"],
            "fibre_ids": [str(fid) for fid in (row["fibre_ids"] or [])],
            "active": row["active"],
            "metadata": row["metadata"] if row["metadata"] else {},
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }

    async def list_teams(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """List all Human-Swarm teams, optionally filtering to active ones."""
        async with self.db_pool.acquire() as conn:
            if active_only:
                rows = await conn.fetch(
                    "SELECT * FROM swarm_teams WHERE active = TRUE ORDER BY created_at DESC"
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM swarm_teams ORDER BY created_at DESC"
                )
        return [
            {
                "team_id": str(r["team_id"]),
                "team_name": r["team_name"],
                "human_id": r["human_id"],
                "human_role": r["human_role"],
                "fibre_ids": [str(fid) for fid in (r["fibre_ids"] or [])],
                "active": r["active"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]

    async def update_team(
        self, team_id: UUID, updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Update a team's configuration: name, human_role, add/remove Fibre IDs,
        or update metadata.
        """
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM swarm_teams WHERE team_id = $1", team_id
            )
            if not row:
                raise FibreException(f"Team {team_id} not found")

            new_name = updates.get("team_name", row["team_name"])
            new_role = updates.get("human_role", row["human_role"])
            current_fibres = list(row["fibre_ids"] or [])

            # Add new Fibre IDs
            for fid in updates.get("add_fibre_ids", []):
                uid = UUID(fid) if isinstance(fid, str) else fid
                if uid not in current_fibres:
                    current_fibres.append(uid)

            # Remove Fibre IDs
            for fid in updates.get("remove_fibre_ids", []):
                uid = UUID(fid) if isinstance(fid, str) else fid
                if uid in current_fibres:
                    current_fibres.remove(uid)

            new_meta = {**(row["metadata"] or {}), **updates.get("metadata", {})}

            await conn.execute(
                """UPDATE swarm_teams
                   SET team_name = $2, human_role = $3, fibre_ids = $4,
                       metadata = $5, updated_at = NOW()
                   WHERE team_id = $1""",
                team_id, new_name, new_role, current_fibres,
                json.dumps(new_meta),
            )

        print(f">>> [FIBRE MANAGER] Team '{new_name}' updated")
        return await self.get_team(team_id)

    async def dissolve_team(self, team_id: UUID, prune_fibres: bool = False) -> Dict[str, Any]:
        """
        Gracefully dissolve a Human-Swarm team.
        Optionally prune the team's Fibres.
        """
        team = await self.get_team(team_id)
        if not team:
            raise FibreException(f"Team {team_id} not found")

        if prune_fibres:
            for fid_str in team.get("fibre_ids", []):
                try:
                    await self.prune(UUID(fid_str), reason=f"Team '{team['team_name']}' dissolved")
                except Exception as e:
                    print(f">>> [FIBRE MANAGER] Could not prune {fid_str}: {e}")

        async with self.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE swarm_teams SET active = FALSE, updated_at = NOW() WHERE team_id = $1",
                team_id,
            )

        print(f">>> [FIBRE MANAGER] Team '{team['team_name']}' dissolved "
              f"(fibres pruned: {prune_fibres})")
        return {"team_id": str(team_id), "dissolved": True, "fibres_pruned": prune_fibres}

    # ── Private Helpers ──

    async def _persist_fibre(self, fibre: BaseFibre, spawn_reason: str) -> None:
        """Save Fibre to database."""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO fibres
                        (fibre_id, fibre_type, name, description, status, autonomy_level,
                         public_key, identity_signature, ethical_core_hash,
                         domain_tags, token_budget_per_hour, max_concurrent_tasks,
                         wisdom_seed, parent_fibre_id, config, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
                """, fibre.fibre_id, fibre.config.fibre_type.value,
                     fibre.config.name, fibre.config.description,
                     FibreStatus.INITIALIZING.value, fibre.autonomy_level.value,
                     fibre._identity_record.public_key_pem if fibre._identity_record else None,
                     fibre._identity_record.parent_signature if fibre._identity_record else None,
                     fibre.ethical_core.integrity_hash,
                     fibre.config.domain_tags, fibre.config.token_budget_per_hour,
                     fibre.config.max_concurrent_tasks,
                     json.dumps(fibre.config.wisdom_seed),
                     fibre.config.parent_fibre_id,
                     json.dumps(fibre.config.model_dump()),
                     json.dumps({"spawn_reason": spawn_reason}))
        except Exception as e:
            print(f">>> [FIBRE MANAGER] Database persist error: {e}")

    async def _absorb_fibre_wisdom(self, fibre: BaseFibre, journal: List[Dict]) -> bool:
        """Extract and preserve wisdom from a pruned Fibre's Evolution Journal."""
        if not journal:
            return False

        try:
            from app.services.strategic_memory import StrategicMemoryService
            memory = StrategicMemoryService(self.db_pool)

            # Create an insight from the Fibre's journal summary
            successful_tasks = sum(1 for j in journal if j.get("success"))
            total_tasks = len(journal)

            await memory.log_insight(
                title=f"Wisdom from pruned Fibre '{fibre.name}'",
                body=f"Fibre {fibre.name} ({fibre.fibre_type.value}) completed "
                     f"{successful_tasks}/{total_tasks} tasks. "
                     f"Final alignment: {fibre.alignment_scores}",
                domain="swarm",
                confidence=0.6,
                tags=[fibre.fibre_type.value, "pruned", "wisdom"],
                source_fibre_id=fibre.fibre_id,
                source_type="fibre",
            )
            return True
        except Exception as e:
            print(f">>> [FIBRE MANAGER] Wisdom absorption failed: {e}")
            return False

    async def _log_swarm_event(
        self, event_type: str, fibre: BaseFibre, details: Dict[str, Any]
    ) -> None:
        """Log an event to Swarm Oversight (Strategic Memory Layer 6)."""
        try:
            from app.services.strategic_memory import StrategicMemoryService
            memory = StrategicMemoryService(self.db_pool)
            await memory.log_swarm_event(
                event_type=event_type,
                fibre_id=fibre.fibre_id,
                fibre_type=fibre.fibre_type.value,
                details=details,
                active_fibre_count=len(self._active_fibres),
            )
        except Exception as e:
            print(f">>> [FIBRE MANAGER] Swarm event logging failed: {e}")
