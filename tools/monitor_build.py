#!/usr/bin/env python3
"""
LN-FAB Build Monitor — Real-time build activity dashboard.

Usage:
    python3 tools/monitor_build.py                  # Monitor live (tails log)
    python3 tools/monitor_build.py /tmp/custom.log  # Monitor custom log
    python3 tools/monitor_build.py --summary        # Show summary of last build
    python3 tools/monitor_build.py --replay         # Replay full log with formatting
"""

import sys
import os
import re
import time

LOG_FILE = "/tmp/bridge_local.log"

GOLD = "\033[38;2;201;169;98m"
CYAN = "\033[38;2;78;205;196m"
GREEN = "\033[38;2;34;197;94m"
RED = "\033[38;2;239;68;68m"
PURPLE = "\033[38;2;157;78;221m"
DIM = "\033[38;2;100;100;100m"
WHITE = "\033[97m"
BOLD = "\033[1m"
RESET = "\033[0m"
YELLOW = "\033[38;2;250;204;21m"

BAR = f"{DIM}{'─' * 70}{RESET}"


def fmt_dur(ms):
    return f"{ms}ms" if ms < 1000 else f"{ms / 1000:.1f}s"


class Monitor:
    def __init__(self, silent=False):
        self.turn = 0
        self.max_turns = 10
        self.tools_run = 0
        self.files_written = []
        self.files_read = []
        self.searches = 0
        self.errors = []
        self.grok_chunks = 0
        self.grok_time = 0.0
        self.grok_ttft = 0.0
        self.grok_model = ""
        self.tool_durations = []
        self.build_active = False
        self.t0 = None
        self.turn_t0 = None
        self.provider = ""
        self._pending_tool = None
        self.silent = silent
        self.builds_completed = 0

    def p(self, *args, **kwargs):
        if not self.silent:
            print(*args, **kwargs)

    def banner(self):
        self.p(f"\n{GOLD}{BOLD}╔═══════════════════════════════════════════════════════════════════╗{RESET}")
        self.p(f"{GOLD}{BOLD}║            LN-FAB Build Monitor — Live Dashboard                 ║{RESET}")
        self.p(f"{GOLD}{BOLD}╚═══════════════════════════════════════════════════════════════════╝{RESET}")
        self.p(f"  {DIM}Log: {LOG_FILE}  |  Ctrl+C to stop{RESET}")
        self.p(BAR)

    def progress_bar(self):
        pct = min(self.turn / self.max_turns, 1.0) if self.max_turns else 0
        filled = int(pct * 30)
        bar = f"{GREEN}{'█' * filled}{DIM}{'░' * (30 - filled)}{RESET}"
        elapsed = f"{time.time() - self.t0:.0f}s" if self.t0 and self.t0 > 1 else "—"
        return f"  [{bar}] Turn {self.turn}/{self.max_turns}  {DIM}elapsed {elapsed}{RESET}"

    def summary(self):
        elapsed = time.time() - self.t0 if self.t0 and self.t0 > 1 else 0
        self.p(f"\n{BAR}")
        self.p(f"{GOLD}{BOLD}  BUILD SUMMARY{RESET}")
        self.p(BAR)
        self.p(f"  {WHITE}Turns:{RESET}          {CYAN}{self.turn}{RESET}")
        self.p(f"  {WHITE}Tools run:{RESET}      {CYAN}{self.tools_run}{RESET}")
        self.p(f"  {WHITE}Files written:{RESET}  {GREEN}{len(self.files_written)}{RESET}")
        self.p(f"  {WHITE}Files read:{RESET}     {CYAN}{len(self.files_read)}{RESET}")
        self.p(f"  {WHITE}Searches:{RESET}       {CYAN}{self.searches}{RESET}")
        self.p(f"  {WHITE}Errors:{RESET}         {RED if self.errors else DIM}{len(self.errors)}{RESET}")
        self.p(f"  {WHITE}LLM provider:{RESET}   {PURPLE}{self.provider or '—'}{RESET}")
        if self.grok_model:
            self.p(f"  {WHITE}Model:{RESET}         {PURPLE}{self.grok_model}{RESET}")
        self.p(f"  {WHITE}LLM chunks:{RESET}    {PURPLE}{self.grok_chunks}{RESET}")
        self.p(f"  {WHITE}LLM time:{RESET}      {PURPLE}{self.grok_time:.1f}s{RESET}")
        if self.grok_ttft:
            self.p(f"  {WHITE}Time to 1st:{RESET}   {PURPLE}{self.grok_ttft:.1f}s{RESET}")
        if self.tool_durations:
            avg = sum(self.tool_durations) / len(self.tool_durations)
            self.p(f"  {WHITE}Avg tool:{RESET}      {CYAN}{avg:.0f}ms{RESET}")
        if elapsed > 0:
            self.p(f"  {WHITE}Total time:{RESET}    {GOLD}{elapsed:.1f}s{RESET}")

        if self.files_written:
            self.p(f"\n  {GREEN}{BOLD}Files Created/Modified:{RESET}")
            seen = set()
            for f in self.files_written:
                if f in seen:
                    continue
                seen.add(f)
                name = os.path.basename(f)
                dirp = os.path.dirname(f)
                self.p(f"    {GREEN}✓{RESET} {DIM}{dirp}/{RESET}{WHITE}{name}{RESET}")

        if self.errors:
            self.p(f"\n  {RED}{BOLD}Errors:{RESET}")
            for e in self.errors[:5]:
                self.p(f"    {RED}✗{RESET} {e[:75]}")
        self.p(BAR)

    def _tool_icon(self, tool):
        if "write" in tool or "create" in tool:
            return "📝", GREEN
        elif "read" in tool:
            return "📖", CYAN
        elif "list" in tool:
            return "📁", CYAN
        elif "search" in tool:
            return "🔍", CYAN
        return "🔧", CYAN

    def feed(self, line):
        line = line.rstrip()
        if not line:
            return

        # --- Grok first token ---
        m = re.search(r'\[GROK\] First token in ([\d.]+)s', line)
        if m:
            self.grok_ttft = float(m.group(1))
            if not self.build_active:
                self.build_active = True
                self.t0 = self.t0 or time.time()
            c = GREEN if self.grok_ttft < 2 else CYAN if self.grok_ttft < 5 else RED
            self.p(f"    {c}⚡ First token: {self.grok_ttft}s{RESET}")
            return

        # --- Grok stream complete ---
        m = re.search(r'\[GROK\] Stream complete: (\d+) chunks in ([\d.]+)s(?: \(model=([^)]+)\))?', line)
        if m:
            chunks, dur = int(m.group(1)), float(m.group(2))
            model = m.group(3) or ""
            self.grok_chunks += chunks
            self.grok_time += dur
            if model:
                self.grok_model = model
            suffix = f" {DIM}({model}){RESET}" if model else ""
            self.p(f"    {PURPLE}📡 Streamed {chunks} chunks in {dur}s{RESET}{suffix}")
            return

        # --- Turn header ---
        m = re.search(r'\[CLI\] Turn (\d+): extracted (\d+) tool calls? from (\d+) chars', line)
        if m:
            turn, n_tools, chars = int(m.group(1)), int(m.group(2)), int(m.group(3))
            self.turn = turn
            if not self.build_active:
                self.build_active = True
                self.t0 = self.t0 or time.time()
            self.turn_t0 = time.time()

            self.p(f"\n{self.progress_bar()}")
            if n_tools > 0:
                self.p(f"  {WHITE}Extracted {n_tools} tool call{'s' if n_tools != 1 else ''} ({chars:,} char response){RESET}")
            else:
                self.p(f"  {DIM}No tool calls in {chars:,} char response{RESET}")
            return

        # --- Tool call detail from extraction ---
        m = re.search(r'>>>   tool: (\w+) args=(.+)', line)
        if m:
            tool, args = m.group(1), m.group(2)[:100]
            pm = re.search(r'"path":\s*"([^"]+)"', args)
            path = pm.group(1) if pm else ""
            icon, color = self._tool_icon(tool)
            if "write" in tool and path:
                self.files_written.append(path)
            if "search" in tool:
                self.searches += 1
            display = path if path else args[:55]
            if len(display) > 55:
                display = "..." + display[-52:]
            self.p(f"      {color}{icon} {tool}({display}){RESET}")
            return

        # --- Tool start ---
        m = re.search(r'\[CLI\] TOOL_START: (\w+) args=(.+)', line)
        if m:
            tool, args = m.group(1), m.group(2)[:100]
            pm = re.search(r'"path":\s*"([^"]+)"', args)
            path = pm.group(1) if pm else ""
            icon, color = self._tool_icon(tool)
            if "read" in tool and path:
                self.files_read.append(path)
            display = path if path else args[:50]
            if len(display) > 50:
                display = "..." + display[-47:]
            self._pending_tool = tool
            self.p(f"    {color}{icon} {tool}({display}){RESET}", end="", flush=True)
            return

        # --- Tool done ---
        m = re.search(r'\[CLI\] TOOL_DONE: (\w+) status=(\w+) dur=(\d+)ms provider=(\w+)', line)
        if m:
            tool, status = m.group(1), m.group(2)
            dur, prov = int(m.group(3)), m.group(4)
            self.tools_run += 1
            self.tool_durations.append(dur)
            self.provider = self.provider or prov
            ok = status == "ok"
            si = f"{GREEN}✓{RESET}" if ok else f"{RED}✗{RESET}"
            dc = GREEN if dur < 50 else CYAN if dur < 500 else YELLOW if dur < 2000 else RED

            if self._pending_tool:
                self.p(f" {si} {dc}{fmt_dur(dur)}{RESET}")
                self._pending_tool = None
            else:
                self.p(f"    {si} {tool} {dc}{fmt_dur(dur)}{RESET} {DIM}({prov}){RESET}")
            if not ok:
                self.errors.append(f"{tool}: {status}")
            return

        # --- No more tool calls ---
        if "no new tool calls, breaking" in line:
            m2 = re.search(r'Turn (\d+)', line)
            if m2:
                self.turn = int(m2.group(1))
            self.builds_completed += 1
            self.p(f"\n  {GOLD}✅ Build output complete — Turn {self.turn}{RESET}")
            self.summary()
            return

        # --- Streaming error ---
        m = re.search(r'\[CLI\] Streaming error \(turn (\d+)\): (.+)', line)
        if m:
            self.errors.append(f"Turn {m.group(1)}: {m.group(2)[:60]}")
            self.p(f"    {RED}⚠ Streaming error (turn {m.group(1)}): {m.group(2)[:60]}{RESET}")
            return

        # --- Tool loop error ---
        m = re.search(r'\[CLI\] Tool loop error: (.+)', line)
        if m:
            self.errors.append(m.group(1)[:60])
            self.p(f"    {RED}⚠ Tool loop error: {m.group(1)[:60]}{RESET}")
            return

        # --- Workspace routing ---
        if "[ROUTE]" in line:
            m = re.search(r'\[ROUTE\] (\w+) → (.+)', line)
            if m:
                self.p(f"    {DIM}🔀 {m.group(1)} → {m.group(2)}{RESET}")
            return

        # --- Ollama fallback (not an error, just info) ---
        if "Ollama native FC failed" in line:
            self.p(f"    {YELLOW}⚠ Ollama fallback triggered{RESET}")
            return

        # --- Sovereign fallback (expected when Ollama model missing) ---
        if "sovereign streaming failed" in line:
            m = re.search(r"Ollama 404.*model '([^']+)' not found", line)
            if m:
                self.p(f"    {DIM}↪ Ollama model {m.group(1)} not found, falling back{RESET}")
            return

        # --- Non-fatal storage/redis (ignore) ---
        if "R2 storage error (non-fatal)" in line:
            return
        if "Redis" in line and ("non-fatal" in line or "persist" in line):
            return

        # --- New build message ---
        if re.search(r"type=nate_cli_chat\b", line):
            if not self.build_active:
                self.build_active = True
                self.t0 = time.time()
                self.p(f"\n  {GOLD}{BOLD}🔨 BUILD MESSAGE RECEIVED{RESET}")
                self.p(BAR)
            return


def monitor_live(log_file):
    mon = Monitor()
    mon.banner()

    try:
        with open(log_file, 'r') as f:
            f.seek(0, 2)
            mon.p(f"  {DIM}Tailing log... waiting for build activity...{RESET}\n")

            while True:
                line = f.readline()
                if line:
                    mon.feed(line)
                else:
                    time.sleep(0.05)
    except KeyboardInterrupt:
        if mon.build_active and mon.builds_completed == 0:
            mon.summary()
        mon.p(f"\n{DIM}Monitor stopped.{RESET}")
    except FileNotFoundError:
        print(f"{RED}Log file not found: {log_file}{RESET}")
        print(f"{DIM}Start the bridge: PYTHONUNBUFFERED=1 python3 bridge_server.py 2>&1 | tee /tmp/bridge_local.log{RESET}")
        sys.exit(1)


def replay_log(log_file):
    mon = Monitor()
    mon.banner()
    mon.p(f"  {YELLOW}Replaying build from log...{RESET}\n")
    try:
        with open(log_file, 'r') as f:
            for line in f:
                mon.feed(line)
    except FileNotFoundError:
        print(f"{RED}Log file not found: {log_file}{RESET}")
        sys.exit(1)
    if not mon.build_active:
        mon.p(f"  {DIM}No build activity found in log.{RESET}")


def show_summary(log_file):
    mon = Monitor(silent=True)
    mon.t0 = 1
    try:
        with open(log_file, 'r') as f:
            for line in f:
                mon.feed(line)
    except FileNotFoundError:
        print(f"{RED}Log file not found: {log_file}{RESET}")
        sys.exit(1)

    mon.silent = False
    if mon.turn == 0 and mon.tools_run == 0:
        print(f"{DIM}No build activity found in {log_file}{RESET}")
    else:
        mon.summary()


if __name__ == "__main__":
    log = LOG_FILE

    if "--summary" in sys.argv:
        idx = sys.argv.index("--summary")
        log = sys.argv[idx + 1] if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith("--") else LOG_FILE
        show_summary(log)
        sys.exit(0)

    if "--replay" in sys.argv:
        idx = sys.argv.index("--replay")
        log = sys.argv[idx + 1] if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith("--") else LOG_FILE
        replay_log(log)
        sys.exit(0)

    for a in sys.argv[1:]:
        if not a.startswith("--"):
            log = a
            break

    LOG_FILE = log
    monitor_live(log)
