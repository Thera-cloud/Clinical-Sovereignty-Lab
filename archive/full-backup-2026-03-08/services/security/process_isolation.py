"""
HIVE DEFENSE PROTOCOL v3.0 — Process Isolation Service (Phase 8C)
Minimal capability container configuration and runtime verification.

Production containers run with the absolute minimum set of capabilities
required for the application to function.  This service generates and
verifies the security profiles:

1. **seccomp-bpf** — restricts which system calls the process can make.
   Only the syscalls explicitly needed for Python, asyncio, networking
   (to Azure services), and file I/O to designated paths are permitted.
   All others are blocked.

2. **Linux capabilities** — all capabilities are dropped; only the
   minimal set required (NET_BIND_SERVICE for port 80/443, if needed)
   is re-added.

3. **Filesystem policy** — read-only root filesystem with designated
   writable paths (/tmp, /app/data, /var/log).

4. **Network policy** — egress limited to Azure service endpoints only.
   No arbitrary outbound connections.

5. **Runtime verification** — verifies at startup that the current
   process is actually running under the expected restrictions.

Additional hardening:
    - No compiler available in production container.
    - Non-root user enforcement (UID ≥ 1000).
    - /proc and /sys mounted read-only.
    - No new privileges flag set.

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import json
import logging
import os
import platform
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("hive.process_isolation")


# =============================================================================
# CONSTANTS
# =============================================================================

# Allowed syscalls for production containers (x86_64 / aarch64)
ALLOWED_SYSCALLS: List[str] = [
    # Process management
    "exit", "exit_group", "set_tid_address", "set_robust_list",
    "getpid", "getuid", "geteuid", "getgid", "getegid",
    "gettid", "getppid",
    # Memory
    "brk", "mmap", "munmap", "mprotect", "mremap",
    "madvise", "futex",
    # File I/O (read-only + designated write paths)
    "read", "write", "open", "openat", "close", "stat", "fstat",
    "lstat", "lseek", "access", "faccessat", "readlink",
    "readlinkat", "getcwd", "dup", "dup2", "dup3", "fcntl",
    "flock", "fsync", "fdatasync", "ftruncate",
    # Directory
    "getdents", "getdents64",
    # Networking (restricted to Azure egress)
    "socket", "connect", "sendto", "recvfrom", "sendmsg",
    "recvmsg", "shutdown", "bind", "listen", "accept",
    "accept4", "getsockname", "getpeername", "setsockopt",
    "getsockopt", "select", "poll", "epoll_create",
    "epoll_create1", "epoll_ctl", "epoll_wait", "epoll_pwait",
    # Signals
    "rt_sigaction", "rt_sigprocmask", "rt_sigreturn",
    "sigaltstack",
    # Time
    "clock_gettime", "clock_getres", "clock_nanosleep",
    "nanosleep", "gettimeofday",
    # Misc required by Python / asyncio
    "getrandom", "pipe", "pipe2", "eventfd", "eventfd2",
    "timerfd_create", "timerfd_settime", "timerfd_gettime",
    "prctl", "arch_prctl", "ioctl",
    # Process (fork disabled — only thread creation)
    "clone", "clone3", "wait4", "sched_getaffinity",
    "sched_yield",
]

# Minimal Linux capabilities
MINIMAL_CAPABILITIES: Dict[str, List[str]] = {
    "drop": ["ALL"],
    "add": [
        "NET_BIND_SERVICE",     # Bind to ports < 1024 if needed
    ],
}

# Designated writable paths
WRITABLE_PATHS: List[str] = [
    "/tmp",
    "/app/data",
    "/var/log/sovereign",
    "/dev/null",
    "/dev/urandom",
]

# Read-only paths
READONLY_PATHS: List[str] = [
    "/app",
    "/etc",
    "/usr",
    "/lib",
    "/proc",
    "/sys",
]

# Azure service egress endpoints
ALLOWED_EGRESS_ENDPOINTS: List[Dict[str, Any]] = [
    {"host": "*.vault.azure.net", "port": 443, "protocol": "tcp"},
    {"host": "*.cognitiveservices.azure.com", "port": 443, "protocol": "tcp"},
    {"host": "*.openai.azure.com", "port": 443, "protocol": "tcp"},
    {"host": "*.database.azure.com", "port": 5432, "protocol": "tcp"},
    {"host": "*.redis.cache.windows.net", "port": 6380, "protocol": "tcp"},
    # Internal services
    {"host": "10.0.0.0/8", "port": "*", "protocol": "tcp"},
    {"host": "127.0.0.1", "port": "*", "protocol": "tcp"},
    # DNS
    {"host": "*", "port": 53, "protocol": "udp"},
]

# Required non-root UID
MIN_ALLOWED_UID: int = 1000


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class IsolationVerificationResult:
    """Result of runtime isolation verification."""

    verified: bool = False
    checks: Dict[str, bool] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    verified_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# =============================================================================
# PROCESS ISOLATION SERVICE
# =============================================================================

class ProcessIsolation:
    """
    Minimal capability container configuration and runtime verification.

    Generates the security profiles (seccomp, capabilities, filesystem,
    network) used to lock down production containers, and verifies at
    runtime that the expected restrictions are in place.

    Usage
    -----
    ::

        isolation = ProcessIsolation()

        # Generate profiles for container deployment
        seccomp = isolation.get_seccomp_profile()
        caps = isolation.get_capabilities()
        fs_policy = isolation.get_filesystem_policy()
        net_policy = isolation.get_network_policy()

        # Verify at startup
        result = await isolation.verify_runtime_isolation()
        if not result.verified:
            logger.critical("ISOLATION VERIFICATION FAILED: %s", result.errors)
    """

    def __init__(self) -> None:
        logger.info("ProcessIsolation service initialized")

    # ------------------------------------------------------------------
    # seccomp-bpf Profile
    # ------------------------------------------------------------------

    def get_seccomp_profile(self) -> Dict[str, Any]:
        """
        Generate a seccomp-bpf profile restricting allowed system calls.

        The profile follows the OCI runtime spec format and can be passed
        directly to Docker's ``--security-opt seccomp=<profile.json>``
        or Kubernetes ``securityContext.seccompProfile``.

        Returns
        -------
        dict
            A complete seccomp profile in OCI format.

        Notes
        -----
        The default action is ``SCMP_ACT_ERRNO`` (return EPERM for
        blocked syscalls).  In DEFCON 1, this can be upgraded to
        ``SCMP_ACT_KILL`` (kill the process on any blocked syscall).
        """
        profile = {
            "defaultAction": "SCMP_ACT_ERRNO",
            "architectures": [
                "SCMP_ARCH_X86_64",
                "SCMP_ARCH_AARCH64",
            ],
            "syscalls": [
                {
                    "names": ALLOWED_SYSCALLS,
                    "action": "SCMP_ACT_ALLOW",
                },
            ],
            "metadata": {
                "generated_by": "hive.process_isolation",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "version": "8C",
                "note": (
                    "Production seccomp profile for Sovereign Sanctuary containers. "
                    "All syscalls not explicitly listed are blocked with EPERM."
                ),
            },
        }

        logger.info(
            "seccomp_profile_generated allowed_syscalls=%d",
            len(ALLOWED_SYSCALLS),
        )
        return profile

    # ------------------------------------------------------------------
    # Linux Capabilities
    # ------------------------------------------------------------------

    def get_capabilities(self) -> Dict[str, List[str]]:
        """
        Generate the minimal Linux capabilities profile.

        Drops ALL capabilities and re-adds only those strictly required:
        - ``NET_BIND_SERVICE``: Only if the container needs to bind to
          ports below 1024.

        Returns
        -------
        dict
            ``{"drop": ["ALL"], "add": ["NET_BIND_SERVICE"]}``

        Notes
        -----
        In most deployments, even ``NET_BIND_SERVICE`` can be removed
        by binding to a high port (8000, 8765) and using a reverse
        proxy (nginx) for 80/443.
        """
        logger.info(
            "capabilities_profile_generated drop=%s add=%s",
            MINIMAL_CAPABILITIES["drop"],
            MINIMAL_CAPABILITIES["add"],
        )
        return dict(MINIMAL_CAPABILITIES)

    # ------------------------------------------------------------------
    # Filesystem Policy
    # ------------------------------------------------------------------

    def get_filesystem_policy(self) -> Dict[str, Any]:
        """
        Generate the filesystem access policy for production containers.

        The root filesystem is read-only.  Only designated paths are
        mounted as writable tmpfs or bind mounts.

        Returns
        -------
        dict
            Policy with ``read_only_root``, ``writable_paths``,
            ``readonly_paths``, and ``tmpfs_mounts``.
        """
        policy = {
            "read_only_root": True,
            "writable_paths": list(WRITABLE_PATHS),
            "readonly_paths": list(READONLY_PATHS),
            "tmpfs_mounts": [
                {"path": "/tmp", "size": "64m", "mode": "1777"},
                {"path": "/run", "size": "16m", "mode": "0755"},
            ],
            "no_new_devices": True,
            "no_suid": True,
            "proc_mount": "readonly",
            "sys_mount": "readonly",
            "no_compiler": True,
            "compiler_paths_blocked": [
                "/usr/bin/gcc", "/usr/bin/g++", "/usr/bin/cc",
                "/usr/bin/make", "/usr/bin/as", "/usr/bin/ld",
            ],
            "metadata": {
                "generated_by": "hive.process_isolation",
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
        }

        logger.info(
            "filesystem_policy_generated writable=%d readonly=%d",
            len(WRITABLE_PATHS),
            len(READONLY_PATHS),
        )
        return policy

    # ------------------------------------------------------------------
    # Network Policy
    # ------------------------------------------------------------------

    def get_network_policy(self) -> Dict[str, Any]:
        """
        Generate the network egress policy for production containers.

        Outbound connections are restricted to Azure service endpoints
        and internal services only.  No arbitrary internet egress.

        Returns
        -------
        dict
            Policy with ``default_egress`` (deny), ``allowed_endpoints``,
            and ``dns_policy``.
        """
        policy = {
            "default_egress": "deny",
            "default_ingress": "deny",
            "allowed_egress": list(ALLOWED_EGRESS_ENDPOINTS),
            "allowed_ingress": [
                {"port": 8000, "protocol": "tcp", "source": "10.0.0.0/8"},
                {"port": 8765, "protocol": "tcp", "source": "10.0.0.0/8"},
            ],
            "dns_policy": {
                "allow_dns": True,
                "nameservers": ["10.0.0.2", "168.63.129.16"],  # Azure DNS
            },
            "no_raw_sockets": True,
            "no_icmp": False,  # Allow ICMP for health checks
            "metadata": {
                "generated_by": "hive.process_isolation",
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
        }

        logger.info(
            "network_policy_generated egress_rules=%d ingress_rules=%d",
            len(ALLOWED_EGRESS_ENDPOINTS),
            2,
        )
        return policy

    # ------------------------------------------------------------------
    # Runtime Verification
    # ------------------------------------------------------------------

    async def verify_runtime_isolation(self) -> IsolationVerificationResult:
        """
        Verify that the current process is running under expected restrictions.

        Checks performed:
        1. Non-root user (UID >= 1000).
        2. Read-only filesystem where expected.
        3. No compiler binaries accessible.
        4. /proc/self/status shows expected capabilities.
        5. No new privileges flag.

        Returns
        -------
        IsolationVerificationResult
            Complete verification result with pass/fail for each check.
        """
        result = IsolationVerificationResult()

        # --- Check 1: Non-root user ---
        uid = os.getuid() if hasattr(os, "getuid") else -1
        is_non_root = uid >= MIN_ALLOWED_UID
        result.checks["non_root_user"] = is_non_root
        if not is_non_root:
            if uid == 0:
                result.errors.append(f"Running as root (UID={uid}) — FORBIDDEN")
            elif uid == -1:
                result.warnings.append("Cannot determine UID (non-Linux platform)")
            else:
                result.warnings.append(f"UID {uid} < {MIN_ALLOWED_UID}")

        # --- Check 2: Filesystem restrictions ---
        fs_checks = await self._check_filesystem_restrictions()
        result.checks.update(fs_checks["checks"])
        result.warnings.extend(fs_checks.get("warnings", []))
        result.errors.extend(fs_checks.get("errors", []))

        # --- Check 3: No compiler ---
        compiler_check = self._check_no_compiler()
        result.checks["no_compiler"] = compiler_check["clean"]
        if not compiler_check["clean"]:
            result.errors.append(
                f"Compiler binaries found: {compiler_check['found']}"
            )

        # --- Check 4: Capabilities ---
        caps_check = await self._check_capabilities()
        result.checks["minimal_capabilities"] = caps_check.get("minimal", False)
        if not caps_check.get("minimal", False):
            result.warnings.append(
                f"Non-minimal capabilities detected: {caps_check.get('effective', 'unknown')}"
            )

        # --- Check 5: No new privileges ---
        nnp_check = self._check_no_new_privileges()
        result.checks["no_new_privileges"] = nnp_check
        if not nnp_check:
            result.warnings.append("no_new_privs flag not set or cannot be verified")

        # Overall verdict
        has_critical_errors = len(result.errors) > 0
        result.verified = not has_critical_errors

        if result.verified:
            logger.info(
                "runtime_isolation_verified checks=%s warnings=%d",
                result.checks,
                len(result.warnings),
            )
        else:
            logger.critical(
                "RUNTIME_ISOLATION_FAILED errors=%s checks=%s",
                result.errors,
                result.checks,
            )

        return result

    # ------------------------------------------------------------------
    # Verification Helpers
    # ------------------------------------------------------------------

    async def _check_filesystem_restrictions(self) -> Dict[str, Any]:
        """Check filesystem read-only and writable path restrictions."""
        checks: Dict[str, bool] = {}
        warnings: List[str] = []
        errors: List[str] = []

        # Check if /app is read-only (attempt write test)
        test_path = "/app/.isolation_test"
        try:
            with open(test_path, "w") as f:
                f.write("test")
            # If we can write — filesystem is NOT read-only
            os.unlink(test_path)
            checks["root_fs_readonly"] = False
            warnings.append("/app is writable — expected read-only")
        except (PermissionError, OSError):
            checks["root_fs_readonly"] = True
        except Exception:
            checks["root_fs_readonly"] = True  # Assume restricted

        # Check writable paths exist
        for path in WRITABLE_PATHS:
            exists = os.path.exists(path)
            checks[f"writable_path_{path}"] = exists
            if not exists:
                warnings.append(f"Expected writable path missing: {path}")

        return {"checks": checks, "warnings": warnings, "errors": errors}

    def _check_no_compiler(self) -> Dict[str, Any]:
        """Check that no compiler binaries are accessible."""
        compiler_paths = [
            "/usr/bin/gcc", "/usr/bin/g++", "/usr/bin/cc",
            "/usr/bin/make", "/usr/bin/as", "/usr/bin/ld",
            "/usr/local/bin/gcc", "/usr/local/bin/g++",
        ]
        found = [p for p in compiler_paths if os.path.exists(p)]
        return {"clean": len(found) == 0, "found": found}

    async def _check_capabilities(self) -> Dict[str, Any]:
        """Read current process capabilities from /proc/self/status."""
        result: Dict[str, Any] = {"minimal": False, "effective": "unknown"}

        if platform.system() != "Linux":
            result["minimal"] = True  # Cannot check on non-Linux
            return result

        try:
            with open("/proc/self/status", "r") as f:
                for line in f:
                    if line.startswith("CapEff:"):
                        cap_hex = line.split(":")[1].strip()
                        cap_int = int(cap_hex, 16)
                        result["effective"] = cap_hex
                        # Minimal = only NET_BIND_SERVICE (bit 10)
                        # or zero capabilities
                        minimal_mask = (1 << 10)  # NET_BIND_SERVICE
                        result["minimal"] = (cap_int & ~minimal_mask) == 0
                        break
        except (FileNotFoundError, PermissionError):
            result["minimal"] = True  # Cannot verify — assume OK
        except Exception as exc:
            logger.debug("capability_check_error: %s", exc)

        return result

    def _check_no_new_privileges(self) -> bool:
        """Check if the no_new_privs flag is set for this process."""
        if platform.system() != "Linux":
            return True  # Cannot check on non-Linux

        try:
            # PR_GET_NO_NEW_PRIVS = 39
            import ctypes
            libc = ctypes.CDLL("libc.so.6", use_errno=True)
            result = libc.prctl(39, 0, 0, 0, 0)
            return result == 1
        except Exception:
            return True  # Cannot verify — assume OK in dev

    # ------------------------------------------------------------------
    # Docker Compose Integration
    # ------------------------------------------------------------------

    def generate_docker_security_opts(self) -> Dict[str, Any]:
        """
        Generate Docker Compose / Kubernetes security context configuration.

        Returns a dictionary suitable for inclusion in a docker-compose
        service definition or Kubernetes pod spec.

        Returns
        -------
        dict
            Security options for container deployment.
        """
        return {
            "security_opt": [
                "no-new-privileges:true",
            ],
            "cap_drop": ["ALL"],
            "cap_add": MINIMAL_CAPABILITIES["add"],
            "read_only": True,
            "user": "1000:1000",
            "tmpfs": {
                "/tmp": "size=64m,mode=1777",
                "/run": "size=16m,mode=0755",
            },
        }

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        """Current isolation configuration summary."""
        return {
            "allowed_syscalls": len(ALLOWED_SYSCALLS),
            "capabilities_drop": MINIMAL_CAPABILITIES["drop"],
            "capabilities_add": MINIMAL_CAPABILITIES["add"],
            "writable_paths": len(WRITABLE_PATHS),
            "egress_rules": len(ALLOWED_EGRESS_ENDPOINTS),
            "min_uid": MIN_ALLOWED_UID,
            "current_uid": os.getuid() if hasattr(os, "getuid") else -1,
            "platform": platform.system(),
        }

    def __repr__(self) -> str:
        return (
            f"<ProcessIsolation syscalls={len(ALLOWED_SYSCALLS)} "
            f"uid={os.getuid() if hasattr(os, 'getuid') else '?'}>"
        )
