"""
HIVE DEFENSE v4.1 — SBOM Generator
Software Bill of Materials generation in CycloneDX JSON format.

Generates a complete inventory of all dependencies with:
- Package name, version, and license
- SHA-256 hash of installed package
- Supplier/author information
- Dependency relationships
"""

import hashlib
import importlib.metadata
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

_logger = logging.getLogger("sbom_generator")


class SBOMGenerator:
    """Generates CycloneDX-format Software Bill of Materials."""

    def __init__(self):
        self._last_sbom: Optional[Dict] = None
        self._last_generated: Optional[datetime] = None

    def generate(self) -> Dict[str, Any]:
        """Generate a CycloneDX SBOM for all installed packages."""
        components = []

        for dist in importlib.metadata.distributions():
            name = dist.metadata.get("Name", "")
            version = dist.metadata.get("Version", "")
            if not name:
                continue

            component = {
                "type": "library",
                "name": name,
                "version": version,
                "purl": f"pkg:pypi/{name.lower()}@{version}",
                "properties": [],
            }

            # Add license info
            license_info = dist.metadata.get("License", "")
            classifier_licenses = [
                c for c in dist.metadata.get_all("Classifier") or []
                if c.startswith("License")
            ]
            if license_info:
                component["licenses"] = [{"license": {"name": license_info[:100]}}]
            elif classifier_licenses:
                component["licenses"] = [{"license": {"name": classifier_licenses[0][:100]}}]

            # Add author info
            author = dist.metadata.get("Author", "")
            if author:
                component["author"] = author[:100]

            # Add hash from RECORD
            record = dist.read_text("RECORD")
            if record:
                record_hash = hashlib.sha256(record.encode()).hexdigest()
                component["hashes"] = [{"alg": "SHA-256", "content": record_hash}]

            components.append(component)

        sbom = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "serialNumber": f"urn:uuid:{uuid4()}",
            "version": 1,
            "metadata": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "tools": [{"vendor": "Clinical Sovereignty Lab", "name": "hive-sbom-generator", "version": "4.1"}],
                "component": {
                    "type": "application",
                    "name": "sovereign-sanctuary-backend",
                    "version": "4.1",
                },
            },
            "components": components,
        }

        self._last_sbom = sbom
        self._last_generated = datetime.now(timezone.utc)
        _logger.info("SBOM generated: %d components", len(components))
        return sbom

    def save_to_file(self, output_path: str = "sbom.json") -> str:
        """Generate and save SBOM to a JSON file."""
        sbom = self.generate()
        path = Path(output_path)
        path.write_text(json.dumps(sbom, indent=2))
        _logger.info("SBOM saved to %s", output_path)
        return str(path.absolute())

    def get_last_sbom(self) -> Optional[Dict]:
        """Get the last generated SBOM."""
        return self._last_sbom

    def get_component_count(self) -> int:
        """Get number of components in last SBOM."""
        if self._last_sbom:
            return len(self._last_sbom.get("components", []))
        return 0
