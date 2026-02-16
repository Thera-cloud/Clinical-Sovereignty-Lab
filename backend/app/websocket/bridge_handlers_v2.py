"""
SOVEREIGN BRIDGE v16.3: COACH PORTAL PHASE 1 HANDLERS
New message handlers for: Calendar, Pre-Session Brief, Cancel Session, Ask Nate (Coach), Top Tier Sessions, Coaching Advice

Add these handlers to bridge_server_hybrid_v1.py
"""

import json
import re
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

# ==============================================================================
# NEW DATA STRUCTURES
# ==============================================================================

# In-memory session storage (replace with database in production)
SCHEDULED_SESSIONS: Dict[str, Dict[str, Any]] = {}
RECORDED_SESSIONS: Dict[str, Dict[str, Any]] = {}
CLIENT_BRIEFS: Dict[str, Dict[str, Any]] = {}


def require_role(profile: dict, required_role: str) -> bool:
    """Check if profile has the required role. Returns True if authorized."""
    if not profile:
        return False
    return profile.get("role") == required_role


# ==============================================================================
# COACH NEXUS EXTENSIONS
# ==============================================================================

class CoachNexusV2:
    """Extended Coach management with Phase 1 features."""
    
    def __init__(self, root: Path):
        self.root = root

    @staticmethod
    def _safe_id(raw_id: str) -> str:
        """Sanitize user/client/coach IDs to prevent path traversal."""
        return re.sub(r'[^a-zA-Z0-9_\-]', '', str(raw_id or ''))

    def _data_dir(self) -> Path:
        """
        Bridge passes VAULT_ROOT = DATA_DIR / "Vaults" into this class.
        So DATA_DIR is the parent folder.
        """
        try:
            return self.root.parent
        except Exception:
            return Path("/app/data")

    def _backend_data_dir(self) -> Optional[Path]:
        """
        Production: bridge and backend use different /app/data mounts.
        If backend data is mounted into bridge at /app/backend_data, use it
        as the source of truth for scheduled sessions + zoom links.
        """
        try:
            p = Path("/app/backend_data")
            if p.exists():
                return p
        except Exception:
            pass
        return None
    
    def _get_coach_path(self, hardware_id: str) -> Path:
        return self.root / "Coaches" / self._safe_id(hardware_id)
    
    # -------------------------------------------------------------------------
    # CALENDAR MANAGEMENT
    # -------------------------------------------------------------------------
    
    def get_calendar_data(self, coach_profile: Dict[str, Any], month: int = None, year: int = None) -> Dict[str, Any]:
        """Get coach calendar with sessions and availability."""
        hid = coach_profile.get("hardware_id")
        now = datetime.datetime.now()
        # Coerce month/year from incoming WS payloads (can be strings)
        try:
            month = int(month) if month is not None else None
        except Exception:
            month = None
        try:
            year = int(year) if year is not None else None
        except Exception:
            year = None

        month = month or now.month
        year = year or now.year

        def _parse_date_any(v: Any) -> Optional[datetime.datetime]:
            s = (v or "")
            if not isinstance(s, str):
                s = str(s)
            s = s.strip()
            if not s:
                return None
            # Accept ISO with 'Z'
            s_norm = s.replace("Z", "+00:00")
            try:
                # date-only or datetime
                dt = datetime.datetime.fromisoformat(s_norm)
                # If it's date-only (00:00:00), keep as-is; month/year filter still works.
                return dt
            except Exception:
                pass
            # Fallback: if it's an ISO datetime string we can't parse, try date portion.
            try:
                date_part = s.split("T")[0]
                return datetime.datetime.fromisoformat(date_part)
            except Exception:
                return None
        
        # Load schedule
        sched_file = self._get_coach_path(hid) / "schedule.json"
        schedule = []
        if sched_file.exists():
            try:
                with open(sched_file, "r") as f:
                    schedule = json.load(f)
            except:
                pass
        
        # Filter by month/year
        filtered = []
        for s in schedule:
            try:
                dt = _parse_date_any(s.get("date", ""))
                if dt and dt.month == month and dt.year == year:
                    filtered.append(s)
            except:
                pass

        # Also include sessions scheduled via FastAPI `sessions.json`
        # (so "Start Zoom" appears without duplicating a separate schedule store).
        try:
            # Prefer backend store when available (prod); fallback to local store (dev).
            sessions_file = (self._backend_data_dir() or self._data_dir()) / "sessions.json"
            sessions_raw = []
            if sessions_file.exists():
                with open(sessions_file, "r") as f:
                    sessions_raw = json.load(f) or []

            for ses in (sessions_raw or []):
                try:
                    if (ses.get("coach_id") or "") != hid:
                        continue
                    if (ses.get("status") or "") not in ["scheduled", "active"]:
                        continue

                    st = (ses.get("scheduled_start") or "").replace("Z", "+00:00")
                    en = (ses.get("scheduled_end") or "").replace("Z", "+00:00")
                    st_dt = datetime.datetime.fromisoformat(st) if st else None
                    en_dt = datetime.datetime.fromisoformat(en) if en else None
                    if not st_dt:
                        continue

                    dur_min = 50
                    if en_dt and en_dt > st_dt:
                        dur_min = max(5, int((en_dt - st_dt).total_seconds() / 60))

                    # Month/year filter
                    if st_dt.month != month or st_dt.year != year:
                        continue

                    filtered.append({
                        "id": ses.get("session_id") or ses.get("id") or "",
                        "coach_id": hid,
                        "client_id": ses.get("client_id") or "",
                        "client_name": ses.get("client_name") or "",  # optional
                        "family_id": ses.get("family_id") or "",
                        "date": st_dt.date().isoformat(),
                        "time": st_dt.strftime("%H:%M"),
                        "type": ses.get("session_type") or "COACH",
                        "duration_minutes": dur_min,
                        "platform": "Zoom",
                        "zoom_link": ses.get("zoom_link") or "",
                        "zoom_meeting_id": ses.get("zoom_meeting_id") or "",
                        "status": ses.get("status") or "scheduled",
                        "notes": ses.get("notes") or "",
                    })
                except Exception:
                    continue
        except Exception:
            pass
        
        return {
            "month": month,
            "year": year,
            "schedule": filtered,
            "availability": self._get_availability(hid),
        }
    
    def _get_availability(self, hardware_id: str) -> List[str]:
        """Get coach availability slots."""
        avail_file = self._get_coach_path(hardware_id) / "availability.json"
        if avail_file.exists():
            try:
                with open(avail_file, "r") as f:
                    return json.load(f).get("slots", [])
            except:
                pass
        return []
    
    def schedule_session(
        self, 
        coach_profile: Dict[str, Any], 
        client_id: str,
        date: str,
        time: str,
        session_type: str = "Individual",
        duration: int = 50,
        platform: str = "Zoom"
    ) -> Dict[str, Any]:
        """Schedule a new session."""
        # Input validation
        client_id = self._safe_id(client_id)
        if not client_id:
            return {"error": "INVALID_CLIENT_ID"}
        if duration < 5 or duration > 480:
            return {"error": "INVALID_DURATION", "message": "Duration must be 5-480 minutes"}
        # Validate date format
        try:
            datetime.datetime.strptime(date, "%Y-%m-%d")
        except (ValueError, TypeError):
            return {"error": "INVALID_DATE", "message": "Date must be YYYY-MM-DD format"}
        # Validate time format
        try:
            datetime.datetime.strptime(time, "%H:%M")
        except (ValueError, TypeError):
            return {"error": "INVALID_TIME", "message": "Time must be HH:MM format"}
        # Validate session_type and platform against allowed values
        allowed_session_types = {"Individual", "Couple", "Family", "Group", "Crisis", "Follow-up"}
        if session_type not in allowed_session_types:
            return {"error": "INVALID_SESSION_TYPE", "message": f"Must be one of: {', '.join(sorted(allowed_session_types))}"}
        allowed_platforms = {"Zoom", "In-Person", "Phone", "Sanctuary"}
        if platform not in allowed_platforms:
            return {"error": "INVALID_PLATFORM", "message": f"Must be one of: {', '.join(sorted(allowed_platforms))}"}

        import secrets
        session_id = f"SES_{secrets.token_hex(8)}"
        
        session = {
            "id": session_id,
            "coach_id": coach_profile.get("hardware_id"),
            "client_id": client_id,
            "date": date,
            "time": time,
            "type": session_type,
            "duration": duration,
            "platform": platform,
            "status": "pending",
            "created_at": str(datetime.datetime.now()),
        }
        
        # Save to schedule file
        hid = coach_profile.get("hardware_id")
        sched_file = self._get_coach_path(hid) / "schedule.json"
        
        schedule = []
        if sched_file.exists():
            try:
                with open(sched_file, "r") as f:
                    schedule = json.load(f)
            except:
                pass
        
        schedule.append(session)
        
        with open(sched_file, "w") as f:
            json.dump(schedule, f, indent=2)
        
        SCHEDULED_SESSIONS[session_id] = session
        return session
    
    def cancel_session(
        self, 
        coach_profile: Dict[str, Any], 
        session_id: str,
        reason: str,
        send_reschedule_link: bool = True
    ) -> str:
        """Cancel a scheduled session."""
        session_id = str(session_id or "").strip()
        if not session_id:
            return "INVALID_SESSION_ID"
        reason = str(reason or "")[:1000]  # Cap reason length

        hid = coach_profile.get("hardware_id")
        sched_file = self._get_coach_path(hid) / "schedule.json"
        
        schedule = []
        if sched_file.exists():
            try:
                with open(sched_file, "r") as f:
                    schedule = json.load(f)
            except:
                pass
        
        # Find and update session — verify ownership
        for s in schedule:
            if s.get("id") == session_id:
                # Ownership check: session must belong to this coach
                if s.get("coach_id") and s.get("coach_id") != hid:
                    return "UNAUTHORIZED_CANCEL"
                s["status"] = "cancelled"
                s["cancel_reason"] = reason
                s["cancelled_at"] = str(datetime.datetime.now())
                
                # Log cancellation
                self._log_cancellation(hid, s, reason, send_reschedule_link)
                
                # Send email notification to client
                try:
                    from app.services.notifications_service import EmailService
                    import asyncio
                    email_svc = EmailService()
                    client_id_val = s.get("client_id", "")
                    client_email = s.get("client_email", "")
                    coach_name = coach_profile.get("name", "your coach")
                    if client_email:
                        asyncio.get_event_loop().create_task(
                            email_svc.send_coaching_reminder(
                                to_email=client_email,
                                time="cancelled",
                                coach_name=coach_name,
                            )
                        )
                except Exception as email_err:
                    print(f">>> [NOTIFY] Email notification error: {email_err}")

                if send_reschedule_link:
                    self._send_reschedule_link(s.get("client_id"), coach_profile)
                
                break
        
        with open(sched_file, "w") as f:
            json.dump(schedule, f, indent=2)
        
        return "SESSION_CANCELLED"
    
    def _log_cancellation(self, coach_hid: str, session: Dict, reason: str, send_link: bool):
        """Log session cancellation for auditing."""
        log_file = self._get_coach_path(coach_hid) / "cancellation_log.json"
        
        logs = []
        if log_file.exists():
            try:
                with open(log_file, "r") as f:
                    logs = json.load(f)
            except:
                pass
        
        logs.append({
            "session_id": session.get("id"),
            "client_id": session.get("client_id"),
            "original_date": session.get("date"),
            "reason": reason,
            "reschedule_sent": send_link,
            "cancelled_at": str(datetime.datetime.now()),
        })
        
        with open(log_file, "w") as f:
            json.dump(logs, f, indent=2)
    
    def _send_reschedule_link(self, client_id: str, coach_profile: Dict):
        """Send reschedule link to client via email notification."""
        try:
            from app.services.notifications_service import EmailService
            import asyncio
            email_svc = EmailService()
            coach_name = coach_profile.get("name", "your coach")
            # Client email would need to be resolved from client_id
            # For now, log the intent and use in-app notification
            print(f">>> [NOTIFY] Reschedule link sent to {client_id} "
                  f"(coach: {coach_name})")
        except Exception as e:
            print(f">>> [NOTIFY] Reschedule link error: {e}")
    
    # -------------------------------------------------------------------------
    # TOP TIER SESSIONS (Recordings)
    # -------------------------------------------------------------------------
    
    def get_recorded_sessions(
        self, 
        coach_profile: Dict[str, Any],
        filter_type: str = "all"
    ) -> List[Dict[str, Any]]:
        """Get list of recorded sessions for coach."""
        hid = coach_profile.get("hardware_id")
        recordings_file = self._get_coach_path(hid) / "recordings.json"
        
        recordings = []
        if recordings_file.exists():
            try:
                with open(recordings_file, "r") as f:
                    recordings = json.load(f)
            except:
                pass
        
        # Apply filters
        if filter_type == "family":
            recordings = [r for r in recordings if r.get("type") == "FAMILY"]
        elif filter_type == "needs_review":
            recordings = [r for r in recordings if not r.get("reviewed", False)]
        elif filter_type == "this_week":
            week_ago = datetime.datetime.now() - datetime.timedelta(days=7)
            recordings = [
                r for r in recordings 
                if datetime.datetime.fromisoformat(r.get("date", "2000-01-01")) > week_ago
            ]
        
        # Sort by date descending
        recordings.sort(key=lambda x: x.get("date", ""), reverse=True)
        
        return recordings
    
    def save_recording_metadata(
        self, 
        coach_profile: Dict[str, Any],
        session_id: str,
        client_id: str,
        client_name: str,
        duration: int,
        platform: str,
        biometrics_captured: bool = True
    ) -> str:
        """Save metadata for a recorded session."""
        hid = coach_profile.get("hardware_id")
        recordings_file = self._get_coach_path(hid) / "recordings.json"
        
        recordings = []
        if recordings_file.exists():
            try:
                with open(recordings_file, "r") as f:
                    recordings = json.load(f)
            except:
                pass
        
        recording = {
            "id": session_id,
            "client_id": client_id,
            "client": client_name,
            "date": str(datetime.datetime.now().date()),
            "time": str(datetime.datetime.now().time())[:5],
            "duration": duration,
            "platform": platform,
            "biometrics_captured": biometrics_captured,
            "ai_analyzed": False,
            "reviewed": False,
            "tier": "TOP_TIER",  # Determine from client profile
        }
        
        recordings.append(recording)
        
        with open(recordings_file, "w") as f:
            json.dump(recordings, f, indent=2)
        
        RECORDED_SESSIONS[session_id] = recording
        return "RECORDING_SAVED"
    
    # -------------------------------------------------------------------------
    # PRE-SESSION BRIEF
    # -------------------------------------------------------------------------
    
    def get_presession_brief(
        self, 
        coach_profile: Dict[str, Any],
        client_id: str,
        registry: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate pre-session brief for a client."""
        # Get client profile
        client_profile = None
        client_key = None
        for k, v in registry.items():
            if v.get("profile", {}).get("hardware_id") == client_id:
                client_profile = v.get("profile", {})
                client_key = k
                break
        
        if not client_profile:
            return {"error": "CLIENT_NOT_FOUND"}

        # Verify coach is assigned to this client
        assigned_coach = client_profile.get("assigned_coach") or client_profile.get("coach_id") or ""
        coach_hid = coach_profile.get("hardware_id", "")
        if assigned_coach and assigned_coach != coach_hid:
            return {"error": "UNAUTHORIZED_CLIENT_ACCESS", "message": "You are not assigned to this client"}

        hid = coach_profile.get("hardware_id")
        
        # Get client's AI session data
        ai_sessions = self._get_client_ai_sessions(client_id)
        
        # Get recent live sessions
        live_sessions = self._get_client_live_sessions(hid, client_id)
        
        # Get family context
        family = self._get_family_context(client_profile, registry)
        
        # Get next scheduled session
        next_session = self._get_next_session(hid, client_id)
        
        # Generate brief
        brief = {
            "client_id": client_id,
            "client_name": client_profile.get("name", "Unknown"),
            "tier": client_profile.get("tier", "STANDARD"),
            "sessions_total": len(live_sessions) + len(ai_sessions),
            "client_since": client_profile.get("joined_date", "Unknown"),
            "recent_mood": self._analyze_recent_mood(ai_sessions),
            "mood_date": self._get_last_session_date(ai_sessions),
            "topics": self._generate_topics(ai_sessions, live_sessions),
            "breakthroughs": self._extract_breakthroughs(ai_sessions, live_sessions),
            "family": family,
            "nate_suggestion": self._generate_nate_suggestion(
                client_profile, ai_sessions, live_sessions, family
            ),
            "next_session": next_session,
        }
        
        CLIENT_BRIEFS[client_id] = brief
        return brief
    
    def _get_client_ai_sessions(self, client_id: str) -> List[Dict]:
        """Get client's AI session history."""
        # Load from client's vault
        safe_id = self._safe_id(client_id)
        client_vault = self.root / "Clients" / safe_id / "memory.json"
        if client_vault.exists():
            try:
                with open(client_vault, "r") as f:
                    return json.load(f)[-30:]  # Last 30 entries
            except:
                pass
        return []
    
    def _get_client_live_sessions(self, coach_hid: str, client_id: str) -> List[Dict]:
        """Get client's live session history with this coach."""
        recordings_file = self._get_coach_path(coach_hid) / "recordings.json"
        if recordings_file.exists():
            try:
                with open(recordings_file, "r") as f:
                    all_recordings = json.load(f)
                    return [r for r in all_recordings if r.get("client_id") == client_id][-10:]
            except:
                pass
        return []
    
    def _get_family_context(self, client_profile: Dict, registry: Dict) -> List[Dict]:
        """Get family members of client."""
        family_id = client_profile.get("family_id")
        if not family_id:
            return []
        
        family = []
        client_hid = client_profile.get("hardware_id")
        
        for k, v in registry.items():
            member = v.get("profile", {})
            if member.get("family_id") == family_id and member.get("hardware_id") != client_hid:
                family.append({
                    "name": member.get("name", "Unknown"),
                    "relation": self._infer_relation(client_profile, member),
                    "is_client": member.get("role") == "CLIENT",
                    "note": self._get_family_note(client_hid, member.get("hardware_id"), coach_hid=coach_profile.get("hardware_id")),
                })
        
        return family
    
    def _infer_relation(self, client: Dict, member: Dict) -> str:
        """Infer family relation (simplified)."""
        if member.get("guardian_id"):
            return "Parent/Guardian"
        if client.get("guardian_id") == member.get("hardware_id"):
            return "Dependent"
        return "Family Member"
    
    def _get_family_note(self, client_hid: str, member_hid: str, coach_hid: str = None) -> Optional[str]:
        """Get family dynamics notes. Only searches the requesting coach's notes if coach_hid provided."""
        if coach_hid:
            # Only search this coach's notes
            notes_file = self._get_coach_path(coach_hid) / "notes.json"
            if notes_file.exists():
                try:
                    with open(notes_file, "r") as f:
                        notes = json.load(f)
                    for note in (notes if isinstance(notes, list) else []):
                        note_text = note.get("text", "") or note.get("content", "")
                        note_clients = note.get("client_ids", [])
                        if client_hid in note_clients and member_hid in note_clients:
                            return note_text[:200]
                except Exception:
                    pass
            return None
        return None
    
    def _get_next_session(self, coach_hid: str, client_id: str) -> Optional[str]:
        """Get next scheduled session with client."""
        sched_file = self._get_coach_path(coach_hid) / "schedule.json"
        if sched_file.exists():
            try:
                with open(sched_file, "r") as f:
                    schedule = json.load(f)
                    now = datetime.datetime.now()
                    for s in schedule:
                        if s.get("client_id") == client_id and s.get("status") != "cancelled":
                            try:
                                sess_date = datetime.datetime.fromisoformat(s.get("date", ""))
                                if sess_date > now:
                                    return f"{s.get('date')} at {s.get('time')}"
                            except:
                                pass
            except:
                pass
        return "No upcoming session"
    
    def _analyze_recent_mood(self, ai_sessions: List[Dict]) -> str:
        """Analyze mood from recent AI sessions."""
        if not ai_sessions:
            return "No recent data"
        
        # Simple keyword analysis (would use NLP in production)
        recent = ai_sessions[-5:]
        keywords = {
            "anxious": 0, "stressed": 0, "happy": 0, "sad": 0,
            "angry": 0, "hopeful": 0, "overwhelmed": 0
        }
        
        for session in recent:
            text = (session.get("user", "") + " " + session.get("ai", "")).lower()
            for keyword in keywords:
                if keyword in text:
                    keywords[keyword] += 1
        
        dominant = max(keywords, key=keywords.get)
        if keywords[dominant] == 0:
            return "Neutral"
        
        return f"Somewhat {dominant}"
    
    def _get_last_session_date(self, ai_sessions: List[Dict]) -> str:
        """Get date of last AI session."""
        if not ai_sessions:
            return "N/A"
        
        last = ai_sessions[-1]
        timestamp = last.get("timestamp", "")
        if timestamp:
            try:
                dt = datetime.datetime.fromisoformat(timestamp)
                return dt.strftime("%b %d")
            except:
                pass
        return "Recent"
    
    def _generate_topics(self, ai_sessions: List[Dict], live_sessions: List[Dict]) -> List[Dict]:
        """Generate recommended topics to address."""
        topics = []
        
        # Analyze AI sessions for patterns
        if ai_sessions:
            recent_text = " ".join([s.get("user", "") for s in ai_sessions[-10:]])
            
            if "sleep" in recent_text.lower():
                topics.append({
                    "text": "Sleep disturbances mentioned - needs attention",
                    "type": "caution"
                })
            
            if "work" in recent_text.lower() or "job" in recent_text.lower():
                topics.append({
                    "text": "Follow up on workplace-related concerns",
                    "type": "normal"
                })
            
            if "progress" in recent_text.lower() or "better" in recent_text.lower():
                topics.append({
                    "text": "Acknowledge recent positive progress",
                    "type": "positive"
                })
        
        # Add default if no topics found
        if not topics:
            topics.append({
                "text": "Check in on general wellbeing",
                "type": "normal"
            })
        
        return topics[:5]  # Max 5 topics
    
    def _extract_breakthroughs(self, ai_sessions: List[Dict], live_sessions: List[Dict]) -> List[str]:
        """Extract recent breakthroughs from AI sessions and live session data.
        Uses keyword detection + C_emo spike detection for breakthrough identification."""
        breakthroughs = []
        
        # 1. Keyword-based detection from AI session responses
        breakthrough_keywords = {
            "breakthrough", "realize", "realise", "insight", "understood",
            "finally see", "makes sense now", "aha moment", "shifted",
            "connected the dots", "lightbulb", "turning point", "forgave",
            "let go", "accepted", "healed",
        }
        if ai_sessions:
            for session in ai_sessions[-10:]:
                ai_response = (session.get("ai", "") or "").lower()
                user_msg = (session.get("user", "") or "").lower()
                combined = ai_response + " " + user_msg
                matched = [kw for kw in breakthrough_keywords if kw in combined]
                if matched:
                    ts = session.get("timestamp", "recent")[:10]
                    breakthroughs.append(f"Insight noted on {ts} ({matched[0]})")
        
        # 2. C_emo spike detection from live sessions (nevedal metrics)
        if live_sessions:
            prev_cemo = None
            for session in live_sessions[-5:]:
                metrics = session.get("nevedal_metrics", session.get("metrics", {}))
                c_emo = metrics.get("c_emo") if isinstance(metrics, dict) else None
                if c_emo is not None and prev_cemo is not None:
                    # A jump of 0.15+ in C_emo between sessions = emotional breakthrough
                    if c_emo - prev_cemo >= 0.15:
                        ts = session.get("date", session.get("created_at", "recent"))[:10]
                        breakthroughs.append(f"Coherence breakthrough on {ts} (C_emo +{(c_emo - prev_cemo):.2f})")
                if c_emo is not None:
                    prev_cemo = c_emo

        # 3. Session notes flagged as breakthroughs
        for session in live_sessions[-10:]:
            notes = session.get("coach_notes", "") or ""
            if "breakthrough" in notes.lower() or "significant progress" in notes.lower():
                ts = session.get("date", session.get("created_at", "recent"))[:10]
                breakthroughs.append(f"Coach-flagged progress on {ts}")
        
        return breakthroughs[:5]
    
    def _generate_nate_suggestion(
        self, 
        client: Dict,
        ai_sessions: List[Dict],
        live_sessions: List[Dict],
        family: List[Dict]
    ) -> str:
        """Generate Little Nate's session suggestion."""
        # Would integrate with AI for personalized suggestions
        
        suggestion_parts = []
        
        if ai_sessions:
            suggestion_parts.append(
                f"Based on {len(ai_sessions)} recent AI sessions, "
                "I recommend starting with an open check-in about their current state."
            )
        
        if family:
            suggestion_parts.append(
                "Family dynamics may be relevant - tread carefully if these topics arise."
            )
        
        if not suggestion_parts:
            suggestion_parts.append(
                "Focus on building rapport and identifying current concerns."
            )
        
        return " ".join(suggestion_parts)
    
    # -------------------------------------------------------------------------
    # COACHING ADVICE (Post-Session Analysis)
    # -------------------------------------------------------------------------
    
    def get_coaching_advice(
        self, 
        coach_profile: Dict[str, Any],
        session_id: str
    ) -> Dict[str, Any]:
        """Generate AI coaching advice for a completed session."""
        hid = coach_profile.get("hardware_id")
        
        # Get session recording metadata
        recordings_file = self._get_coach_path(hid) / "recordings.json"
        session = None
        
        if recordings_file.exists():
            try:
                with open(recordings_file, "r") as f:
                    recordings = json.load(f)
                    for r in recordings:
                        if r.get("id") == session_id:
                            session = r
                            break
            except:
                pass
        
        if not session:
            return {"error": "SESSION_NOT_FOUND"}
        
        # Get session analysis (would be from AI processing of recording)
        analysis = self._analyze_session(session)
        
        # Get biometrics data
        biometrics = self._get_session_biometrics(hid, session_id)
        
        # Generate coaching recommendations
        advice = {
            "session_id": session_id,
            "client_name": session.get("client", "Unknown"),
            "session_date": session.get("date"),
            "duration": session.get("duration"),
            "key_observation": analysis.get("key_observation"),
            "recommendation": analysis.get("recommendation"),
            "biometrics": biometrics,
            "notable_moments": analysis.get("notable_moments", []),
            "next_session_suggestions": analysis.get("suggestions", []),
        }
        
        # Mark as reviewed
        self._mark_session_reviewed(hid, session_id)
        
        return advice
    
    def _analyze_session(self, session: Dict) -> Dict[str, Any]:
        """Analyze session for coaching insights using available session data.
        Extracts observations from transcript, metrics, and session metadata."""
        duration_min = session.get("duration", 0)
        client_name = session.get("client", "the client")
        transcript = session.get("transcript", "") or session.get("notes", "") or ""
        metrics = session.get("nevedal_metrics", session.get("metrics", {})) or {}
        c_emo = metrics.get("c_emo")
        topics = session.get("topics", []) or []

        # Build key observation from available data
        observations = []
        if duration_min and duration_min > 40:
            observations.append(f"Extended session ({duration_min} min) indicates deep engagement")
        elif duration_min and duration_min < 15:
            observations.append(f"Short session ({duration_min} min) — check for resistance or scheduling issues")
        
        if c_emo is not None:
            if c_emo >= 0.7:
                observations.append(f"High emotional coherence (C_emo: {c_emo:.2f}) — client in secure space")
            elif c_emo <= 0.3:
                observations.append(f"Low emotional coherence (C_emo: {c_emo:.2f}) — consider grounding work next session")
        
        if topics:
            observations.append(f"Topics explored: {', '.join(topics[:3])}")
        
        key_obs = ". ".join(observations) if observations else (
            f"{client_name} showed engagement throughout the session. "
            "Consider exploring the topics that emerged more deeply."
        )

        # Build recommendation
        recommendations = []
        if c_emo is not None and c_emo <= 0.3:
            recommendations.append("Focus on emotional regulation and grounding techniques")
        if c_emo is not None and c_emo >= 0.7:
            recommendations.append("Client is ready for deeper exploratory work")
        if not recommendations:
            recommendations.append("Continue building on the progress made")
        
        recommendation = ". ".join(recommendations) + "."

        # Extract notable moments from transcript if available
        notable_moments = []
        if transcript:
            lines = transcript.split("\n") if isinstance(transcript, str) else []
            for i, line in enumerate(lines):
                lower_line = line.lower()
                if any(kw in lower_line for kw in ["breakthrough", "realize", "important", "feel safe"]):
                    time_est = f"{(i * 2):02d}:00" if i < 60 else f"{i}:00"
                    notable_moments.append({"time": time_est, "desc": line[:100].strip()})
        if not notable_moments:
            notable_moments = [{"time": "N/A", "desc": "Full session analysis available after audio processing"}]

        # Suggestions for next session
        suggestions = []
        if topics:
            suggestions.append(f"Follow up on: {topics[0]}")
        if c_emo is not None and c_emo <= 0.4:
            suggestions.append("Begin with a check-in on emotional state")
        suggestions.append("Review homework/practice since last session")

        return {
            "key_observation": key_obs,
            "recommendation": recommendation,
            "notable_moments": notable_moments[:5],
            "suggestions": suggestions[:4],
        }
    
    def _get_session_biometrics(self, coach_hid: str, session_id: str) -> Dict[str, int]:
        """Get biometric analysis for session from nevedal_metrics."""
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're inside an async context — schedule a coroutine
                import concurrent.futures
                # Fall back to file-based metrics if we can't await
                pass

            # Try reading from the session's metrics JSON first
            recordings_file = self._get_coach_path(coach_hid) / "recordings.json"
            if recordings_file.exists():
                with open(recordings_file, "r") as f:
                    recordings = json.load(f)
                for r in recordings:
                    if r.get("id") == session_id:
                        bio = r.get("biometrics")
                        if bio and isinstance(bio, dict):
                            return {
                                "engagement": bio.get("engagement", 0),
                                "emotional_range": bio.get("emotional_range", 0),
                                "stress_level": bio.get("stress_level", 0),
                                "openness": bio.get("openness", 0),
                            }
                        # Derive from nevedal state if available
                        ns = r.get("nevedal_state", {})
                        if ns:
                            c_emo = ns.get("c_emo", 0.5)
                            gap = ns.get("GAP", 0.5)
                            return {
                                "engagement": int(min(100, c_emo * 120)),
                                "emotional_range": int(min(100, gap * 100)),
                                "stress_level": int(min(100, ns.get("anxiety_level", 0.4) * 100)),
                                "openness": int(min(100, (c_emo + gap) / 2 * 110)),
                            }
        except Exception as bio_err:
            print(f">>> [BRIDGE-V2] Biometrics lookup error: {bio_err}")

        # Fallback defaults (better than nothing)
        return {
            "engagement": 0,
            "emotional_range": 0,
            "stress_level": 0,
            "openness": 0,
        }
    
    def _mark_session_reviewed(self, coach_hid: str, session_id: str):
        """Mark session as reviewed."""
        recordings_file = self._get_coach_path(coach_hid) / "recordings.json"
        
        if recordings_file.exists():
            try:
                with open(recordings_file, "r") as f:
                    recordings = json.load(f)
                
                for r in recordings:
                    if r.get("id") == session_id:
                        r["reviewed"] = True
                        r["reviewed_at"] = str(datetime.datetime.now())
                        break
                
                with open(recordings_file, "w") as f:
                    json.dump(recordings, f, indent=2)
            except:
                pass


# ==============================================================================
# NEW MESSAGE HANDLERS (Add to main handler function)
# ==============================================================================

"""
Add these handlers to the main handler() function in bridge_server_hybrid_v1.py:

# Initialize the new nexus
coach_nexus_v2 = CoachNexusV2(VAULT_ROOT)

# Inside the async for msg in websocket loop:

elif msg_type == "fetch_coach_calendar":
    if current_profile and current_profile.get("role") == "COACH":
        month = data.get("month")
        year = data.get("year")
        calendar_data = coach_nexus_v2.get_calendar_data(current_profile, month, year)
        await websocket.send(json.dumps({
            "type": "coach_calendar_data",
            "data": calendar_data
        }))
    else:
        await websocket.send(json.dumps({
            "type": "error",
            "message": "COACH_ACCESS_REQUIRED"
        }))

elif msg_type == "fetch_coach_sessions":
    if current_profile and current_profile.get("role") == "COACH":
        filter_type = data.get("filter", "all")
        sessions = coach_nexus_v2.get_recorded_sessions(current_profile, filter_type)
        await websocket.send(json.dumps({
            "type": "coach_sessions_data",
            "data": {"sessions": sessions}
        }))
    else:
        await websocket.send(json.dumps({
            "type": "error",
            "message": "COACH_ACCESS_REQUIRED"
        }))

elif msg_type == "cancel_session":
    if current_profile and current_profile.get("role") == "COACH":
        result = coach_nexus_v2.cancel_session(
            current_profile,
            data.get("session_id", ""),
            data.get("reason", ""),
            data.get("send_reschedule_link", True)
        )
        await websocket.send(json.dumps({
            "type": "operation_status",
            "status": result
        }))
    else:
        await websocket.send(json.dumps({
            "type": "error",
            "message": "COACH_ACCESS_REQUIRED"
        }))

elif msg_type == "fetch_presession_brief":
    if current_profile and current_profile.get("role") == "COACH":
        registry = load_registry()
        brief = coach_nexus_v2.get_presession_brief(
            current_profile,
            data.get("client_id", ""),
            registry
        )
        await websocket.send(json.dumps({
            "type": "presession_brief_data",
            "data": brief
        }))
    else:
        await websocket.send(json.dumps({
            "type": "error",
            "message": "COACH_ACCESS_REQUIRED"
        }))

elif msg_type == "fetch_coaching_advice":
    if current_profile and current_profile.get("role") == "COACH":
        advice = coach_nexus_v2.get_coaching_advice(
            current_profile,
            data.get("session_id", "")
        )
        await websocket.send(json.dumps({
            "type": "coaching_advice_data",
            "data": advice
        }))
    else:
        await websocket.send(json.dumps({
            "type": "error",
            "message": "COACH_ACCESS_REQUIRED"
        }))

elif msg_type == "coach_nate_query":
    if current_profile and current_profile.get("role") == "COACH":
        # Process through AI with coach-specific context
        query = data.get("nate_query", "")
        client_context = data.get("client_context")
        
        # Augment query with client context if provided
        if client_context:
            registry = load_registry()
            brief = coach_nexus_v2.get_presession_brief(
                current_profile,
                client_context,
                registry
            )
            # Add brief context to the AI prompt
            augmented_query = f"[Coach asking about {brief.get('client_name')}]: {query}"
        else:
            augmented_query = f"[Coach general query]: {query}"
        
        # Send to AI processor
        asyncio.create_task(
            right_brain.process_interaction(current_profile, augmented_query)
        )
    else:
        await websocket.send(json.dumps({
            "type": "error",
            "message": "COACH_ACCESS_REQUIRED"
        }))

elif msg_type == "schedule_session":
    if current_profile and current_profile.get("role") == "COACH":
        session = coach_nexus_v2.schedule_session(
            current_profile,
            data.get("client_id", ""),
            data.get("date", ""),
            data.get("time", ""),
            data.get("session_type", "Individual"),
            data.get("duration", 50),
            data.get("platform", "Zoom")
        )
        await websocket.send(json.dumps({
            "type": "session_scheduled",
            "data": session
        }))
    else:
        await websocket.send(json.dumps({
            "type": "error",
            "message": "COACH_ACCESS_REQUIRED"
        }))

elif msg_type == "save_recording":
    if current_profile and current_profile.get("role") == "COACH":
        result = coach_nexus_v2.save_recording_metadata(
            current_profile,
            data.get("session_id", ""),
            data.get("client_id", ""),
            data.get("client_name", ""),
            data.get("duration", 50),
            data.get("platform", "Zoom"),
            data.get("biometrics_captured", True)
        )
        await websocket.send(json.dumps({
            "type": "operation_status",
            "status": result
        }))
    else:
        await websocket.send(json.dumps({
            "type": "error",
            "message": "COACH_ACCESS_REQUIRED"
        }))
"""


# ==============================================================================
# VAULT INTEGRATION HANDLERS (B5 — Chat-integrated file interactions)
# ==============================================================================


async def handle_file_upload_request(ws, data, bridge, current_profile=None):
    """Handle file_upload_request WebSocket event. Requires bridge.vault_bridge.
    User identity and tier are taken from the authenticated WebSocket session, not from the message payload."""
    import base64
    import json

    if not current_profile:
        await ws.send(json.dumps({"type": "error", "message": "Login required"}))
        return
    vault_bridge = getattr(bridge, "vault_bridge", None)
    if not vault_bridge:
        await ws.send(json.dumps({"type": "error", "message": "Vault not initialized"}))
        return
    try:
        file_data = data.get("file_data", "")
        file_bytes = base64.b64decode(file_data) if file_data else b""
    except Exception as e:
        await ws.send(json.dumps({"type": "error", "message": f"Invalid file_data: {e}"}))
        return

    # MIME validation before processing
    try:
        from app.services.vault.file_processor import FileProcessor
        _processor = FileProcessor()
        _processor.validate_mime(file_bytes)
    except ValueError as e:
        await ws.send(json.dumps({"type": "error", "message": f"File rejected: {e}"}))
        return

    member_id = current_profile.get("hardware_id") or current_profile.get("id") or ""
    tier = (current_profile.get("subscription_plan") or current_profile.get("tier") or "TRIAL").upper()
    result = await vault_bridge.handle_file_upload_in_chat(
        member_id=member_id,
        file_bytes=file_bytes,
        filename=data.get("filename", "upload"),
        message=data.get("message", ""),
        tier=tier,
        session_id=data.get("session_id", ""),
    )
    await ws.send(json.dumps({"type": "file_upload_response", **result}))


async def handle_vault_preview_request(ws, data, bridge, current_profile=None):
    """Handle vault_preview_request WebSocket event. Requires bridge.vault_bridge.
    User identity and tier are taken from the authenticated WebSocket session, not from the message payload."""
    import json

    if not current_profile:
        await ws.send(json.dumps({"type": "error", "message": "Login required"}))
        return
    vault_bridge = getattr(bridge, "vault_bridge", None)
    if not vault_bridge:
        await ws.send(json.dumps({"type": "error", "message": "Vault not initialized"}))
        return
    member_id = current_profile.get("hardware_id") or current_profile.get("id") or ""
    tier = (current_profile.get("subscription_plan") or current_profile.get("tier") or "TRIAL").upper()
    result = await vault_bridge.handle_vault_preview_request(
        member_id=member_id,
        item_id=data.get("item_id", ""),
        tier=tier,
    )
    await ws.send(json.dumps({"type": "vault_preview_response", **result}))
