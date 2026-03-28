"""
Distributed Inference Configuration
Manages the multi-node inference topology:
  - Hetzner CAX41 (37.27.244.80 / 10.13.13.5): Primary sovereign - llama3.1:8b, Qwen2.5-14B, Qwen2.5-32B
  - DigitalOcean production (68.183.168.75): Backend host, can run small model alongside containers
  - DigitalOcean droplets (to be provisioned): Secondary inference nodes
  - Home GPU (configurable): Clinical-depth 70B model
"""
import os
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import IntEnum

logger = logging.getLogger(__name__)


class ScalingLevel(IntEnum):
    MINIMAL = 1        # Hetzner only (llama3.1:8b)
    DUAL_MODEL = 2     # Hetzner (8B + 14B)
    TRIPLE_MODEL = 3   # Hetzner (8B + 14B + 32B)
    WORKERS_AI = 4     # + Cloudflare Workers AI overflow
    MULTI_NODE = 5     # + DigitalOcean secondary nodes
    HOME_GPU = 6       # + Home GPU for clinical depth


@dataclass
class InferenceNode:
    name: str
    url: str
    model: str
    max_concurrent: int
    wireguard_ip: Optional[str] = None
    public_ip: Optional[str] = None
    enabled: bool = True
    health_status: str = "unknown"
    provider: str = "sovereign"  # sovereign, workers_ai, azure, home_gpu


@dataclass
class DistributedInferenceConfig:
    scaling_level: ScalingLevel = ScalingLevel.MINIMAL
    nodes: List[InferenceNode] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> "DistributedInferenceConfig":
        level = int(os.getenv("SCALING_LEVEL", "3"))
        config = cls(scaling_level=ScalingLevel(min(level, 6)))

        # Always include Hetzner primary
        hetzner_url = os.getenv("SOVEREIGN_INFERENCE_URL", "http://10.13.13.5:11434")
        config.nodes.append(InferenceNode(
            name="hetzner-primary",
            url=hetzner_url,
            model="llama3.1:8b-instruct-q4_K_M",
            max_concurrent=4,
            wireguard_ip="10.13.13.5",
            public_ip="37.27.244.80",
            provider="sovereign",
        ))

        if config.scaling_level >= ScalingLevel.DUAL_MODEL:
            config.nodes.append(InferenceNode(
                name="hetzner-14b",
                url=hetzner_url,
                model="qwen2.5:14b-instruct-q4_K_M",
                max_concurrent=2,
                wireguard_ip="10.13.13.5",
                public_ip="37.27.244.80",
                provider="sovereign",
            ))

        if config.scaling_level >= ScalingLevel.TRIPLE_MODEL:
            config.nodes.append(InferenceNode(
                name="hetzner-32b",
                url=hetzner_url,
                model="qwen2.5:32b-instruct-q4_K_M",
                max_concurrent=1,
                wireguard_ip="10.13.13.5",
                public_ip="37.27.244.80",
                provider="sovereign",
            ))

        if config.scaling_level >= ScalingLevel.WORKERS_AI:
            workers_url = os.getenv("WORKERS_AI_URL", "")
            if workers_url:
                config.nodes.append(InferenceNode(
                    name="workers-ai",
                    url=workers_url,
                    model="@cf/meta/llama-3.1-8b-instruct",
                    max_concurrent=50,
                    provider="workers_ai",
                ))

        if config.scaling_level >= ScalingLevel.MULTI_NODE:
            # DigitalOcean secondary nodes (provisioned separately)
            do_nodes = os.getenv("DO_INFERENCE_NODES", "")
            if do_nodes:
                for i, node_url in enumerate(do_nodes.split(",")):
                    node_url = node_url.strip()
                    if node_url:
                        config.nodes.append(InferenceNode(
                            name=f"digitalocean-{i+1}",
                            url=node_url,
                            model="llama3.1:8b-instruct-q4_K_M",
                            max_concurrent=4,
                            provider="sovereign",
                        ))

        if config.scaling_level >= ScalingLevel.HOME_GPU:
            home_url = os.getenv("HOME_GPU_URL", "")
            if home_url:
                home_model = os.getenv("HOME_GPU_MODEL", "llama3.1:70b-instruct-q4_K_M")
                config.nodes.append(InferenceNode(
                    name="home-gpu",
                    url=home_url,
                    model=home_model,
                    max_concurrent=2,
                    provider="home_gpu",
                ))

        logger.info(
            "DistributedInferenceConfig: level=%s, %d nodes active",
            config.scaling_level.name,
            len(config.nodes),
        )
        return config

    def get_node_for_tier(
        self, tier: str, odpe_signal: str = "PROVISIONAL"
    ) -> Optional[InferenceNode]:
        """Select best node based on inference tier and ODPE signal."""
        enabled = [n for n in self.nodes if n.enabled]
        if not enabled:
            return None

        if tier == "clinical":
            # Clinical: prefer home GPU > 32B > 14B > 8B, never Workers AI
            for name_pref in ["home-gpu", "hetzner-32b", "hetzner-14b", "hetzner-primary"]:
                node = next((n for n in enabled if n.name == name_pref), None)
                if node:
                    return node

        if odpe_signal == "LOCKED":
            # High consensus: fast model is fine
            return next(
                (
                    n
                    for n in enabled
                    if "8b" in n.model.lower() or n.name == "hetzner-primary"
                ),
                enabled[0],
            )

        if odpe_signal == "TENSION":
            # Deep analysis needed: prefer larger models
            for name_pref in ["hetzner-32b", "hetzner-14b", "home-gpu"]:
                node = next((n for n in enabled if n.name == name_pref), None)
                if node:
                    return node

        if odpe_signal == "NOISE":
            return None  # NOISE signal should not trigger LLM calls

        # Default: round-robin among sovereign nodes
        sovereign = [n for n in enabled if n.provider == "sovereign"]
        if sovereign:
            return sovereign[0]
        return enabled[0]

    def get_status(self) -> Dict:
        return {
            "scaling_level": self.scaling_level.name,
            "scaling_level_value": int(self.scaling_level),
            "total_nodes": len(self.nodes),
            "enabled_nodes": len([n for n in self.nodes if n.enabled]),
            "nodes": [
                {
                    "name": n.name,
                    "model": n.model,
                    "max_concurrent": n.max_concurrent,
                    "enabled": n.enabled,
                    "health": n.health_status,
                    "provider": n.provider,
                }
                for n in self.nodes
            ],
            "total_concurrent_capacity": sum(
                n.max_concurrent for n in self.nodes if n.enabled
            ),
        }


# WireGuard provisioning script template for new DigitalOcean droplets
WIREGUARD_SETUP_SCRIPT = """#!/bin/bash
# WireGuard setup for new inference node
# Run on: fresh Ubuntu 24.04 droplet

apt-get update && apt-get install -y wireguard ollama

# Generate WireGuard keys
wg genkey | tee /etc/wireguard/privatekey | wg pubkey > /etc/wireguard/publickey

# WireGuard config (fill in peer details)
cat > /etc/wireguard/wg0.conf << 'WGEOF'
[Interface]
PrivateKey = $(cat /etc/wireguard/privatekey)
Address = 10.13.13.{NODE_NUM}/24
ListenPort = 51820

[Peer]
# Production VPS (68.183.168.75)
PublicKey = {PROD_PUBKEY}
AllowedIPs = 10.13.13.0/24
Endpoint = 68.183.168.75:51820
PersistentKeepalive = 25
WGEOF

systemctl enable --now wg-quick@wg0

# Configure Ollama
systemctl enable --now ollama
OLLAMA_HOST=0.0.0.0 ollama pull llama3.1:8b-instruct-q4_K_M

echo "Node ready. WireGuard IP: 10.13.13.{NODE_NUM}"
echo "Ollama API: http://10.13.13.{NODE_NUM}:11434"
"""
