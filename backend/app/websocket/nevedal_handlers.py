"""
LITTLE NATE — Nevedal WebSocket Handlers
Version: 1.0
Date: January 21, 2026

Integrates the Nevedal Engine with the existing bridge_server_hybrid.py.
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Set, Any
import time

# Support both:
# - production: `python -m app.websocket.bridge_server` (package imports)
# - local dev: running files directly from this folder
try:
    from .nevedal_engine import NevedalEngine, NevedalState, create_nevedal_engine
except Exception:
    from nevedal_engine import NevedalEngine, NevedalState, create_nevedal_engine


class NevedalHandler:
    """Handles all Nevedal-related WebSocket messages."""
    
    def __init__(self, vault_root: Path, db_pool=None):
        self.vault_root = vault_root
        self.db_pool = db_pool
        self.engine = create_nevedal_engine()
        self.subscribers: Dict[str, Set] = {}
        self.admin_subscribers: Set = set()
        self.last_update: Dict[str, float] = {}
        self.min_update_interval = 0.5
        self.crisis_callbacks: list = []
        print(">>> [NEVEDAL] Handler initialized")
    
    async def handle_biometric_update(self, websocket, data: Dict, profile: Dict):
        """Process biometric data and compute Nevedal state"""
        session_id = data.get('session_id')
        user_id = data.get('user_id', profile.get('hardware_id'))
        biometrics = data.get('biometrics', {})
        context = data.get('context')
        
        if not session_id or not biometrics:
            await self._send_error(websocket, "Missing session_id or biometrics")
            return
        
        # Rate limiting
        now = time.time()
        if now - self.last_update.get(session_id, 0) < self.min_update_interval:
            return
        self.last_update[session_id] = now
        
        try:
            state = self.engine.process_biometrics(
                session_id=session_id,
                user_id=user_id,
                dyad_partner_id=data.get('dyad_partner_id'),
                biometrics=biometrics,
                context=context
            )
            
            await self._send_state(websocket, state)
            await self._broadcast_state(session_id, state)
            await self._store_state(state)
            await self._check_crisis_indicators(state, profile)
            
            if state.cee_window and state.cee_duration_seconds >= 15:
                print(f">>> [NEVEDAL] 🌟 CEE Window: {session_id} ({state.cee_duration_seconds}s)")
                
        except Exception as e:
            print(f">>> [NEVEDAL] Error: {e}")
            await self._send_error(websocket, str(e))
    
    async def handle_subscribe(self, websocket, data: Dict):
        """Subscribe to session updates"""
        session_id = data.get('session_id')
        
        if session_id == 'admin':
            self.admin_subscribers.add(websocket)
        elif session_id:
            if session_id not in self.subscribers:
                self.subscribers[session_id] = set()
            self.subscribers[session_id].add(websocket)
        
        await websocket.send(json.dumps({
            "type": "nevedal_subscribed",
            "session_id": session_id
        }))
    
    async def handle_unsubscribe(self, websocket, data: Dict):
        """Unsubscribe from updates"""
        session_id = data.get('session_id')
        if session_id == 'admin':
            self.admin_subscribers.discard(websocket)
        elif session_id in self.subscribers:
            self.subscribers[session_id].discard(websocket)
    
    async def handle_get_history(self, websocket, data: Dict):
        """Get historical metrics with timeline, statistics, CEE events, and breakthroughs"""
        user_id = data.get('user_id')
        session_id = data.get('session_id')
        limit = min(data.get('limit', 100), 1000)
        
        history = [
            s.to_dict() for s in self.engine.state_history
            if s.user_id == user_id and (not session_id or s.session_id == session_id)
        ][-limit:]
        
        # Build timeline (all 7 Nevedal variables)
        timeline = []
        for h in history:
            timeline.append({
                "timestamp": h.get("timestamp", ""),
                "c_emo": h.get("c_emo", 0.5),
                "p_ent": h.get("p_ent", 0.5),
                "t_tunnel": h.get("t_tunnel", 0.5),
                "d_distance": h.get("d_distance", 0.5),
                "gamma_env": h.get("gamma_env", 0.3),
                "e_g_joint": h.get("e_g_joint", 0.4),
                "tau_emo": h.get("tau_emo", 1.0),
                "cee_window": h.get("cee_window", False),
            })
        
        # Compute statistics
        c_emo_vals = [t["c_emo"] for t in timeline if t["c_emo"] is not None]
        statistics = {
            "avg_c_emo": round(sum(c_emo_vals) / len(c_emo_vals), 3) if c_emo_vals else 0,
            "peak_c_emo": round(max(c_emo_vals), 3) if c_emo_vals else 0,
            "lowest_c_emo": round(min(c_emo_vals), 3) if c_emo_vals else 0,
            "total_cees": sum(1 for t in timeline if t.get("cee_window")),
        }
        
        # Extract CEE events from history
        cee_events = []
        for h in history:
            if h.get("cee_window"):
                cee_events.append({
                    "timestamp": h.get("timestamp", ""),
                    "c_emo": h.get("c_emo", 0),
                    "duration_seconds": h.get("cee_duration_seconds", 0),
                    "context": h.get("interpretation", ""),
                })
        
        # Breakthroughs: CEEs with high C_emo (>= 0.85)
        breakthroughs = [e for e in cee_events if (e.get("c_emo") or 0) >= 0.85]
        breakthroughs.sort(key=lambda e: e.get("c_emo", 0), reverse=True)
        
        await websocket.send(json.dumps({
            "type": "nevedal_history",
            "user_id": user_id,
            "count": len(history),
            "data": history,
            "timeline": timeline,
            "statistics": statistics,
            "cee_events": cee_events,
            "breakthroughs": breakthroughs[:10],
        }))
    
    async def handle_session_summary(self, websocket, data: Dict):
        """Get session summary"""
        session_id = data.get('session_id')
        summary = self.engine.get_session_summary(session_id)
        
        await websocket.send(json.dumps({
            "type": "nevedal_session_summary",
            "session_id": session_id,
            "data": summary
        }))
    
    async def handle_get_cee_events(self, websocket, data: Dict):
        """Get CEE events"""
        session_id = data.get('session_id')
        limit = min(data.get('limit', 50), 200)
        
        events = self.engine.cee_events
        if session_id:
            events = [e for e in events if e.session_id == session_id]
        
        events_data = [
            {
                "session_id": e.session_id,
                "start_time": e.start_time.isoformat(),
                "end_time": e.end_time.isoformat(),
                "duration_seconds": e.duration_seconds,
                "peak_c_emo": e.peak_c_emo,
            }
            for e in events[-limit:]
        ]
        
        await websocket.send(json.dumps({
            "type": "nevedal_cee_events",
            "count": len(events_data),
            "data": events_data
        }))
    
    async def _send_state(self, websocket, state: NevedalState):
        """Send state to client"""
        try:
            await websocket.send(json.dumps({
                "type": "nevedal_state",
                "data": state.to_dict()
            }))
        except Exception as e:
            print(f">>> [NEVEDAL] Send error: {e}")
    
    async def _send_error(self, websocket, message: str):
        """Send error to client"""
        try:
            await websocket.send(json.dumps({
                "type": "nevedal_error",
                "message": message
            }))
        except:
            pass
    
    async def _broadcast_state(self, session_id: str, state: NevedalState):
        """Broadcast to subscribers"""
        message = json.dumps({
            "type": "nevedal_update",
            "session_id": session_id,
            "data": state.to_dict()
        })
        
        # Session subscribers
        if session_id in self.subscribers:
            dead = set()
            for ws in self.subscribers[session_id]:
                try:
                    await ws.send(message)
                except:
                    dead.add(ws)
            for ws in dead:
                self.subscribers[session_id].discard(ws)
        
        # Admin subscribers
        dead = set()
        for ws in self.admin_subscribers:
            try:
                await ws.send(message)
            except:
                dead.add(ws)
        for ws in dead:
            self.admin_subscribers.discard(ws)
    
    async def _store_state(self, state: NevedalState):
        """Store in database. Resolves hardware_id → UUID for FK columns."""
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                user_uuid = await conn.fetchval(
                    "SELECT id FROM users WHERE hardware_id = $1 OR username = $1 LIMIT 1",
                    state.user_id,
                )
                if not user_uuid:
                    return

                session_uuid = None
                if state.session_id:
                    try:
                        import uuid as _uuid_mod
                        parsed = _uuid_mod.UUID(str(state.session_id))
                        exists = await conn.fetchval("SELECT 1 FROM sessions WHERE id = $1", parsed)
                        if exists:
                            session_uuid = parsed
                    except (ValueError, AttributeError):
                        pass

                dyad_uuid = None
                if state.dyad_partner_id:
                    dyad_uuid = await conn.fetchval(
                        "SELECT id FROM users WHERE hardware_id = $1 OR username = $1 LIMIT 1",
                        state.dyad_partner_id,
                    )

                await conn.execute("""
                    INSERT INTO nevedal_metrics (
                        session_id, user_id, dyad_partner_id, recorded_at,
                        c_emo, p_ent, t_tunnel, gamma_env, e_g_joint,
                        cee_window, cee_duration_seconds
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                """,
                    session_uuid, user_uuid, dyad_uuid,
                    state.timestamp, state.c_emo, state.p_ent, state.t_tunnel,
                    state.gamma_env, state.e_g_joint, state.cee_window,
                    state.cee_duration_seconds
                )
        except Exception as e:
            print(f">>> [NEVEDAL] DB error: {e}")
    
    async def _check_crisis_indicators(self, state: NevedalState, profile: Dict):
        """Check for crisis"""
        if state.gamma_env > 0.8 and state.e_g_joint > 0.7:
            print(f">>> [NEVEDAL] ⚠️ Crisis: {profile.get('name')}")
            for cb in self.crisis_callbacks:
                try:
                    await cb(state, profile)
                except:
                    pass
    
    def cleanup_connection(self, websocket):
        """Cleanup on disconnect"""
        for sid in list(self.subscribers.keys()):
            self.subscribers[sid].discard(websocket)
            if not self.subscribers[sid]:
                del self.subscribers[sid]
        self.admin_subscribers.discard(websocket)


# =============================================================================
# INTEGRATION INSTRUCTIONS
# =============================================================================
"""
Add to bridge_server_hybrid.py:

1. Import:
   from nevedal_handlers import NevedalHandler

2. Initialize after VAULT_ROOT:
   nevedal_handler = NevedalHandler(VAULT_ROOT)

3. Add message handlers:
   elif msg_type == "biometric_update":
       await nevedal_handler.handle_biometric_update(websocket, data, current_profile)
   elif msg_type == "nevedal_subscribe":
       await nevedal_handler.handle_subscribe(websocket, data)
   elif msg_type == "nevedal_get_history":
       await nevedal_handler.handle_get_history(websocket, data)
   elif msg_type == "nevedal_get_session_summary":
       await nevedal_handler.handle_session_summary(websocket, data)
   elif msg_type == "nevedal_get_cee_events":
       await nevedal_handler.handle_get_cee_events(websocket, data)

4. Cleanup on disconnect:
   finally:
       nevedal_handler.cleanup_connection(websocket)
"""
