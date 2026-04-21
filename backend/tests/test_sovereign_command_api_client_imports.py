"""
Meta-regression: Sovereign Command React tabs must import shared apiClient
so Bearer auth is sent on admin API calls (prevents raw fetch 401s).
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
COMPONENTS = REPO / "admin" / "src" / "components"
ROOT = REPO / "admin" / "src"

REQUIRED_COMPONENTS = [
    "ThePulse.jsx",
    "StrategicMemory.jsx",
    "SwarmOperations.jsx",
    "ForesightDashboard.jsx",
    "FamilyPatterns.jsx",
    "QuaketeMap.jsx",
    "BigNateChat.jsx",
    "ZEFCPMonitor.jsx",
    "RevenueDashboard.jsx",
    "SovereignSwarmWireDiagram.jsx",
]


def test_tab_components_import_api_client():
    for name in REQUIRED_COMPONENTS:
        text = (COMPONENTS / name).read_text(encoding="utf-8")
        assert "apiClient" in text, f"{name} must import from ../apiClient"


def test_sovereign_command_root_imports_api_client():
    text = (ROOT / "SovereignCommand.jsx").read_text(encoding="utf-8")
    assert "from './apiClient'" in text or 'from "./apiClient"' in text
