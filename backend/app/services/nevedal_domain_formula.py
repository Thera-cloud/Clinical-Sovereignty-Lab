"""
Nevedal Domain Formula Engine — Parameterized domain-specific coherence formulas.

The three patent-protected formulas (C_emo, C_knowledge, C_noetic) remain hardcoded
in nevedal_engine.py, quantum_knowledge_field.py, and quantum_cognition.py.

This engine creates NEW domain formulas that apply the same mathematical structure
to non-clinical domains (marketing, engagement, defense, etc.).

C_domain(t) = [beta * entanglement * tunneling] / [noise + load/hbar]
              * exp[-(noise + load/hbar) * t]
"""

import logging
import math
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nevedal_domain_formula")


class NevedalDomainFormula:
    """Parameterized Nevedal formula for a specific domain."""

    def __init__(self, name: str, domain: str, params: Dict[str, Any]):
        self.name = name
        self.domain = domain
        self.beta = float(params.get("beta", 0.85))
        self.hbar = float(params.get("hbar", 1.0))
        self.variable_map = params.get("variable_map", {})
        self.data_source = params.get("data_source", "")
        self.compute_schedule = params.get("compute_schedule", "per_observation")

    def compute(self, entanglement: float, tunneling: float,
                noise: float, load: float, t: float) -> float:
        denominator = max(noise + (load / max(self.hbar, 0.001)), 0.01)
        c_0 = (self.beta * entanglement * tunneling) / denominator
        decay = math.exp(-min(denominator * t, 50.0))
        return max(0.0, min(1.0, c_0 * decay))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "domain": self.domain,
            "beta": self.beta,
            "hbar": self.hbar,
            "variable_map": self.variable_map,
            "data_source": self.data_source,
            "compute_schedule": self.compute_schedule,
        }


class NevedalFormulaRegistry:
    """Registry of active domain formulas loaded from nate_extensions."""

    def __init__(self, db_pool=None, sandbox_executor=None):
        self._db_pool = db_pool
        self._sandbox = sandbox_executor
        self._formulas: Dict[str, NevedalDomainFormula] = {}

    async def load_from_db(self):
        if not self._db_pool:
            return
        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT name, domain, definition
                    FROM nate_extensions
                    WHERE extension_type = 'formula' AND active = true
                """)
            self._formulas.clear()
            for row in rows:
                try:
                    defn = row["definition"]
                    if isinstance(defn, str):
                        import json
                        defn = json.loads(defn)
                    formula = NevedalDomainFormula(
                        name=row["name"],
                        domain=row["domain"],
                        params=defn,
                    )
                    self._formulas[formula.name] = formula
                    logger.info("Loaded domain formula: %s (%s)", formula.name, formula.domain)
                except Exception as e:
                    logger.warning("Failed to load formula %s: %s", row.get("name"), e)
        except Exception as e:
            logger.warning("NevedalFormulaRegistry load error: %s", e)

    def get(self, name: str) -> Optional[NevedalDomainFormula]:
        return self._formulas.get(name)

    def list_formulas(self) -> List[Dict[str, Any]]:
        return [f.to_dict() for f in self._formulas.values()]

    async def compute_and_store(self, name: str, entanglement: float, tunneling: float,
                                noise: float, load: float, t: float) -> Optional[float]:
        formula = self._formulas.get(name)
        if not formula:
            return None

        result = formula.compute(entanglement, tunneling, noise, load, t)

        if self._sandbox:
            await self._sandbox.insert_formula_result(
                formula_name=name,
                domain=formula.domain,
                entanglement=entanglement,
                tunneling=tunneling,
                noise=noise,
                load_val=load,
                time_val=t,
                coherence=result,
            )

        return result

    def health(self) -> Dict[str, Any]:
        return {
            "loaded_formulas": len(self._formulas),
            "formula_names": list(self._formulas.keys()),
        }
