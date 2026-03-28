import inspect

from app.services.quantum_crystal_orchestrator import (
    NevedalWaveEngine,
    ODPESignalRouter,
    QuantumCrystalOrchestrator,
)
from app.services.time_crystal_forge import TimeCrystalForge


def test_required_contract_methods_exist():
    assert hasattr(QuantumCrystalOrchestrator, "recall")
    assert hasattr(TimeCrystalForge, "forge_for_user")
    assert hasattr(NevedalWaveEngine, "compute_ec")
    assert hasattr(ODPESignalRouter, "filter_recall_results")


def test_required_contract_signatures_are_stable():
    recall_sig = inspect.signature(QuantumCrystalOrchestrator.recall)
    forge_sig = inspect.signature(TimeCrystalForge.forge_for_user)
    ec_sig = inspect.signature(NevedalWaveEngine.compute_ec)
    filter_sig = inspect.signature(ODPESignalRouter.filter_recall_results)

    assert "query" in recall_sig.parameters
    assert "user_id" in recall_sig.parameters
    assert "crystals" in recall_sig.parameters

    assert "user_id" in forge_sig.parameters
    assert "user_id" in ec_sig.parameters
    assert "crystals" in filter_sig.parameters
