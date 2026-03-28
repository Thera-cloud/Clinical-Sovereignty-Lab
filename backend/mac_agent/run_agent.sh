#!/bin/bash
# Wrapper script for nate-mac-agent LaunchAgent.
# Uses /bin/bash (which typically has FDA via Terminal.app grant)
# to avoid macOS TCC blocking python3 from accessing ~/Desktop/.

export MAC_AGENT_TOKEN="${MAC_AGENT_TOKEN}"
export MAC_AGENT_PORT="${MAC_AGENT_PORT:-9900}"
export MAC_AGENT_WORKSPACE="${MAC_AGENT_WORKSPACE:-/Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2}"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

cd "$MAC_AGENT_WORKSPACE"
exec /usr/bin/python3 backend/mac_agent/nate_mac_agent.py
