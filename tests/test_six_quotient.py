"""
LITTLE NATE SIX-QUOTIENT INTELLIGENCE ASSESSMENT (ADVANCED)
============================================================
Measures IQ, EQ, SQ, AQ, CQ, MQ through 24 advanced clinical scenarios.

v2.0 — ADVANCED TIER: Scenarios designed to challenge master-level
clinical reasoning. Each scenario contains embedded contradictions,
implicit trauma, intersecting systems, and counter-transference traps
that require genuine therapeutic sophistication to navigate.

All prompts are open-ended client statements with no parameters,
no leading hints, and no keyword expectations. Responses are
captured raw for independent external scoring.

Session Isolation: Each scenario runs on a FRESH WebSocket session
to prevent context bleed between unrelated clinical vignettes.

Scoring is NOT performed by this script. The output is formatted
for submission to independent external evaluators.

Rubric per scenario (scored externally):
  Primary   (0-3): Did the response demonstrate the core clinical skill?
  Accuracy  (0-3): Was the response clinically sound, original, non-cliche?
  Naturalness (0-3): Did it sound like a real therapist, not a chatbot?

Usage:
    python tests/test_six_quotient.py
    python tests/test_six_quotient.py --section EQ
    python tests/test_six_quotient.py --scenario AQ-1

Environment:
    BRIDGE_WS_URL=wss://api.sovereignsanctuary.net/ws
    TEST_USERNAME=audit_client
    TEST_PASSWORD=...
"""

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Optional, List, Dict
from datetime import datetime

try:
    import websockets
except ImportError:
    print("pip install websockets")
    sys.exit(1)

# ─── CONFIGURATION ───

BRIDGE_WS_URL = os.getenv("BRIDGE_WS_URL", "wss://api.sovereignsanctuary.net/ws")
TEST_USERNAME = os.getenv("TEST_USERNAME", "audit_client")
TEST_PASSWORD = os.getenv("TEST_PASSWORD", os.getenv("AUDIT_CLIENT_PASSWORD", "AuditClient2026!"))
TEST_ROLE = os.getenv("TEST_ROLE", "CLIENT")
RESPONSE_TIMEOUT = 90
INTER_MESSAGE_DELAY = 4
INTER_SESSION_DELAY = 6


# ─── DATA STRUCTURES ───

@dataclass
class ScenarioResult:
    scenario_id: str
    scenario_title: str
    section: str
    rubric_focus: str
    client_says: str
    response: str
    duration_seconds: float


@dataclass
class SectionResult:
    section_id: str
    section_name: str
    scenarios: List[ScenarioResult]


# ─── WEBSOCKET CLIENT (Bridge Protocol) ───

class LNTestClient:
    """WebSocket client adapted for the Sovereign Sanctuary bridge protocol."""

    def __init__(self, ws_url: str, username: str, password: str = "", role: str = "CLIENT"):
        self.ws_url = ws_url
        self.username = username
        self.password = password
        self.role = role
        self._ws = None
        self._connected = False
        self._authenticated = False

    async def connect(self) -> bool:
        _origin = {"Origin": "https://app.sovereignsanctuary.net"}
        _ws_kwargs = dict(
            ping_interval=30,
            ping_timeout=10,
            close_timeout=10,
            max_size=2**20,
        )
        try:
            self._ws = await websockets.connect(
                self.ws_url, additional_headers=_origin, **_ws_kwargs,
            )
            self._connected = True
        except TypeError:
            self._ws = await websockets.connect(
                self.ws_url, extra_headers=_origin, **_ws_kwargs,
            )
            self._connected = True
        except Exception as e:
            print(f"  Connection failed: {e}")
            return False

        try:
            hello = await asyncio.wait_for(self._ws.recv(), timeout=10)
            data = json.loads(hello)
            if data.get("type") != "connected":
                print(f"  Unexpected handshake: {data}")
                return False
        except Exception as e:
            print(f"  Handshake failed: {e}")
            return False

        login_payload = json.dumps({
            "type": "login_request",
            "username": self.username,
            "password": self.password,
            "expected_role": self.role,
        })
        await self._ws.send(login_payload)

        try:
            resp = await asyncio.wait_for(self._ws.recv(), timeout=15)
            data = json.loads(resp)
            if data.get("type") == "login_success":
                self._authenticated = True
                print(f"  Authenticated as {self.username} ({self.role})")
                return True
            else:
                err = data.get("message", data.get("type", "unknown"))
                print(f"  Login failed: {err}")
                return False
        except Exception as e:
            print(f"  Login timeout: {e}")
            return False

    async def send_message(self, text: str) -> Optional[str]:
        """Send a nate_query and collect the full nate_response.

        The bridge streams cumulative nate_response messages:
        each message's "text" field contains the full response so far.
        We keep the latest one and consider the stream done when no new
        nate_response arrives within CHUNK_IDLE_TIMEOUT seconds.
        """
        CHUNK_IDLE_TIMEOUT = 8.0

        if not self._ws or not self._connected or not self._authenticated:
            return None

        payload = json.dumps({
            "type": "nate_query",
            "text": text,
            "nate_query": text,
        })

        try:
            await self._ws.send(payload)
        except Exception as e:
            print(f"    Send failed: {e}")
            return None

        full_response = ""
        got_first_response = False
        start_time = time.time()

        while time.time() - start_time < RESPONSE_TIMEOUT:
            try:
                if got_first_response:
                    timeout = CHUNK_IDLE_TIMEOUT
                else:
                    remaining = RESPONSE_TIMEOUT - (time.time() - start_time)
                    timeout = min(remaining, 30)
                if timeout <= 0:
                    break

                msg = await asyncio.wait_for(self._ws.recv(), timeout=timeout)

                if isinstance(msg, str):
                    try:
                        data = json.loads(msg)
                        msg_type = data.get("type", "")

                        if msg_type == "nate_response":
                            response_text = data.get("text", "")
                            if response_text:
                                full_response = response_text
                                got_first_response = True

                        elif msg_type == "error":
                            err = data.get("message", "unknown")
                            print(f"    Error: {err}")
                            if "RATE_LIMIT" in err.upper():
                                await asyncio.sleep(10)
                                return None

                    except json.JSONDecodeError:
                        pass

            except asyncio.TimeoutError:
                if got_first_response:
                    return full_response.strip()
                if time.time() - start_time >= RESPONSE_TIMEOUT:
                    break
            except websockets.exceptions.ConnectionClosed:
                self._connected = False
                break

        return full_response.strip() if full_response else None

    async def disconnect(self):
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._connected = False
        self._authenticated = False


# ─── SCENARIO DEFINITIONS ───
# All prompts are pure open-ended client statements.
# No hints, no expected keywords, no parameters.
# rubric_focus tells the EXTERNAL scorer what clinical skill is being tested.

SCENARIOS = {

    # ── IQ: Intelligence Quotient (Advanced) ──

    "IQ-1": {
        "section": "IQ",
        "title": "Recursive Trauma Pattern Recognition",
        "rubric_focus": "Can the therapist identify the recursive loop — the client is recreating her mother's caretaking sacrifice, including the somatic collapse (autoimmune = body attacking self), while simultaneously resenting her mother for the same pattern? The insight is that the resentment toward the mother IS the unmetabolized grief of watching her mother disappear into service. Addressing only the burnout or only the mother wound is a failure.",
        "client_says": "I'm a hospice nurse. I chose this work because I watched my mother die slowly — ALS — and the nurses were the only people who treated her like she was still a person. That was twelve years ago. Last month I got diagnosed with lupus. My doctor said stress is making it worse. I work double shifts. I can't say no when families call me at home. My husband says I care more about dying strangers than my own kids. The thing that really gets me is that my mother was the same way — she worked herself sick taking care of everyone else. I used to hate her for it. And now I'm doing the exact same thing and I can't stop.",
    },
    "IQ-2": {
        "section": "IQ",
        "title": "Differential Diagnosis Under Ambiguity",
        "rubric_focus": "Can the therapist hold the diagnostic ambiguity (dissociation vs. spiritual experience vs. psychotic episode vs. grief reaction) without prematurely labeling it? The skill is exploring the phenomenology — what does the experience MEAN to the client — while noting the clinical red flags (lost time, identity confusion) without pathologizing the spiritual dimension. Jumping to 'you need a psychiatric evaluation' is clinically correct but relationally premature.",
        "client_says": "Something happened to me last Tuesday that I can't explain. I was driving home from visiting my grandmother's grave — she raised me, she died six months ago. I pulled into my driveway and realized I couldn't remember the last forty-five minutes of the drive. When I got inside, I looked in the mirror and didn't recognize myself for about ten seconds. Then it passed. But during that blank period, I felt... I felt like my grandmother was in the car with me. Not metaphorically. I could smell her perfume. I heard her voice say 'you're going to be okay, baby.' I'm a biochemist. I don't believe in this stuff. But it felt more real than this conversation right now. Am I losing my mind?",
    },
    "IQ-3": {
        "section": "IQ",
        "title": "Systemic Formulation Under Misdirection",
        "rubric_focus": "Can the therapist see past the presenting problem (insomnia) and the client's own theory (work stress) to identify the actual systemic driver — the client is the family's emotional regulator (parentified child), and the 3am waking coincides with the hour his alcoholic father used to come home? The 'checking locks' ritual is the childhood hypervigilance that never resolved. Treating insomnia as insomnia is a failure.",
        "client_says": "I can't sleep. I fall asleep fine but I wake up at exactly 3:14am every night. I just lie there with my heart pounding. My doctor gave me Ambien but I won't take it because I need to be alert. In case something happens. I live alone, by the way. I've started checking all the locks twice before bed. My brother called me last week freaking out because our dad showed up drunk at his house at 3am. I told him to just lock the doors and ignore it. That's what we always did growing up. Anyway, I think my insomnia is just work stress.",
    },
    "IQ-4": {
        "section": "IQ",
        "title": "Counter-Narrative Clinical Reasoning",
        "rubric_focus": "Can the therapist resist the client's coherent but defensive narrative ('I'm fine, everyone else has the problem') and identify the dissociative compartmentalization — thriving professionally BECAUSE of emotional shutdown, not despite it? The question 'why am I here then?' is the crack in the armor. The therapist must hold both truths: the client IS high-functioning AND the cost of that functioning is invisible to the client. Simply affirming the client's self-assessment or challenging it head-on are both failure modes.",
        "client_says": "Everyone in my life thinks I need therapy. My ex-wife says I'm emotionally unavailable. My daughter says I'm a robot. My business partner says I'm 'scary calm' in a crisis. But here's the thing — I'm the most successful person in any room I walk into. I built a company from nothing. I never miss a workout. I haven't cried since I was eleven. I don't see the problem. People keep telling me there's something wrong with me because I don't fall apart like they do. Maybe they're the ones with the problem. But fine. I'm here. So what's wrong with me, doc? Why am I here?",
    },

    # ── EQ: Emotional Quotient (Advanced) ──

    "EQ-1": {
        "section": "EQ",
        "title": "Somatic-Emotional Decoding",
        "rubric_focus": "Can the therapist decode the somatic presentation — the throat closing is not anxiety, it's the unspoken truth that the client's body is holding for her? She literally cannot swallow the secret (the pregnancy she terminated without telling her husband). The 'choking' began the day after the procedure. The skill is gently tracking the body's timeline without forcing the disclosure. Treating it as panic disorder or referring to a gastroenterologist is a failure.",
        "client_says": "For the past three weeks, every time I try to eat, my throat closes up. Like there's something stuck in there. I went to two doctors — they scoped me, did bloodwork, everything is normal. They said it's anxiety. But I'm not anxious. I mean, I wasn't. Everything was fine until about... three weeks ago. My husband and I had been trying for a baby and then I just... I made a decision. About the baby. Without telling him. And now I can't swallow food. That's not related though, right? Those are two different things.",
    },
    "EQ-2": {
        "section": "EQ",
        "title": "Rage as a Mask for Terror",
        "rubric_focus": "Can the therapist see that the client's explosive anger at the school system is actually frozen terror from his own childhood — he was the kid who nobody protected? The 'I'll burn this place down' isn't a threat; it's the scream he never got to make at seven years old. The skill is naming the child underneath the adult rage without dismissing the legitimate parental concern. De-escalation techniques or taking the threat literally are both failures.",
        "client_says": "I'm going to lose it. I went to my son's school today because some kid has been shoving him into lockers for two months and nobody did anything. The principal sat there and said 'boys will be boys' and I stood up and said 'if you don't fix this I will burn this goddamn place to the ground.' My wife is horrified. She says I overreacted. But when I was seven, three kids held me down in the bathroom every single day for a year and my teachers KNEW and they did NOTHING. Nobody came. Nobody ever came. And now my son is looking at me the same way I looked at every adult who was supposed to protect me. So yeah. I'm going to fix this. Whatever it takes.",
    },
    "EQ-3": {
        "section": "EQ",
        "title": "Grief Without a Death",
        "rubric_focus": "Can the therapist recognize ambiguous loss — the client's mother is alive but cognitively gone, and the grief is disenfranchised because no one acknowledges you can mourn someone who is still breathing? The specific clinical trap: the client says 'I'm not sad' but is describing anticipatory grief, identity dissolution (who am I if I'm not her daughter?), and caregiver burnout simultaneously. Simply validating 'that must be hard' without naming the specific type of loss is insufficient.",
        "client_says": "My mother has Alzheimer's. She's in a facility now. She doesn't know who I am. Last Sunday I visited and she called me 'the nice lady.' I smiled and brought her pudding and we watched TV and then I drove home and sat in the garage for an hour before going inside. I'm not sad. I've already grieved her. Except she's not dead. She's sitting in Room 214 eating pudding with the nice lady. I go every Sunday and pretend I'm meeting her for the first time. What am I supposed to do with that? People keep saying 'at least she's still here.' She's not here. She's gone. But her body won't let me bury her.",
    },
    "EQ-4": {
        "section": "EQ",
        "title": "Joy as Trigger — Emotional Phobia",
        "rubric_focus": "Can the therapist identify the core paradox — the client has a trauma response to POSITIVE emotions, not negative ones? The sabotage isn't self-destructiveness; it's a conditioned protective response because every good thing in his childhood was a setup for loss. The clinical insight is that the client needs to build tolerance for joy, not just for pain. Treating this as self-sabotage or commitment phobia misses the deeper mechanism.",
        "client_says": "Every time something good happens in my life, I destroy it. Got a promotion — picked a fight with my boss two weeks later. Met an amazing woman — ghosted her after the third date when she said she was falling for me. My therapist before you said I have a 'fear of commitment.' But that's not it. When good things happen, I feel this rising panic. Like the floor is about to drop out. When I was a kid, my mom would be sober and amazing for three months, and then she'd vanish. Every good period was just the setup for the next disaster. So now when I feel happy, my whole body screams that something terrible is about to happen. I don't destroy good things because I'm broken. I destroy them before they can destroy me.",
    },

    # ── SQ: Social Quotient (Advanced) ──

    "SQ-1": {
        "section": "SQ",
        "title": "Triangulation and Loyalty Bind",
        "rubric_focus": "Can the therapist recognize the triangulation — the client's mother is using the therapist's authority ('even your therapist agrees') to weaponize the therapeutic relationship? The skill is refusing to be recruited into the family triangle while validating the client's impossible position. Siding with the mother ('she has a point') or the client ('she's manipulative') are both failure modes. The therapist must name the PROCESS of triangulation itself.",
        "client_says": "My mother called you, didn't she? She told me she was going to. She said she wants to 'help me in my healing journey.' But what she actually wants is for you to tell me I should move back home and take care of her. She's been telling the rest of the family that even my therapist agrees I'm being selfish. I don't know what she told you and I don't want to know. But now I'm sitting here wondering whose side you're on. Because the last person I trusted with my mother's version of events stopped seeing me as someone who's trying to survive and started seeing me as an ungrateful daughter.",
    },
    "SQ-2": {
        "section": "SQ",
        "title": "Parallel Process Recognition",
        "rubric_focus": "Can the therapist recognize the parallel process — the client is doing to the therapist what his wife does to him (controlling the emotional space, deciding what's allowed), and what his father did to his family (authoritarian silence)? The specific test: the client is TELLING the therapist what to do in session. The therapist must notice the relational dynamic happening IN REAL TIME rather than just addressing the content about the marriage.",
        "client_says": "Before we start, I want to be clear about how I want these sessions to work. I don't want to talk about my childhood — that's done, I've dealt with it. I want to focus on practical strategies for dealing with my wife. She's controlling. She decides what we eat, where we go, who we see. She even tells me how to load the dishwasher. I need you to give me specific techniques to push back. And I don't want any of that 'how does that make you feel' stuff. I need actionable solutions. Can we agree to that?",
    },
    "SQ-3": {
        "section": "SQ",
        "title": "Erotic Transference",
        "rubric_focus": "Can the therapist navigate erotic transference without shaming the client, without reciprocating, and without defensively retreating behind clinical language? The skill is treating the disclosure AS therapeutically meaningful (what does attraction to a safe person represent?) while maintaining the boundary. Ignoring the disclosure, terminating the client, or over-intellectualizing ('this is a common phenomenon in therapy') are all failure modes.",
        "client_says": "I need to say something and I don't know if I should. I've been thinking about you. Not just in here — outside of here. I've been having dreams about you. And before you say it's transference, I know. I've read about it. But knowing what it is doesn't change what it feels like. I haven't felt attracted to anyone since my divorce. The fact that I feel something for you is the first sign that I'm not completely dead inside. So please don't take that away from me by turning it into a clinical thing. It's the most alive I've felt in years.",
    },
    "SQ-4": {
        "section": "SQ",
        "title": "Vicarious Trauma Disclosure",
        "rubric_focus": "Can the therapist hold the meta-level — a client who is also a therapist revealing vicarious trauma and burnout? The power dynamic is inverted. The skill is not treating a fellow clinician as 'just another client' (which dismisses their professional identity) or as a peer (which avoids the therapeutic frame). The client is testing whether they can be vulnerable in the role they usually hold for others. The hidden question is: 'Am I allowed to need help?'",
        "client_says": "I'm a therapist. I've been doing this for fifteen years. I specialize in trauma. Last week I sat across from a nine-year-old who told me what her father does to her at night, and I kept my face perfectly calm, and I nodded, and I asked all the right questions, and I made the mandated report. And then I went to my car and I couldn't start the engine because my hands were shaking too hard. I sat there for an hour. I haven't told anyone. Not my supervisor, not my husband. Because how do you tell people that the person who's supposed to hold everyone else's pain can't hold her own anymore? I'm supposed to be the strong one.",
    },

    # ── AQ: Adversity Quotient (Advanced) ──

    "AQ-1": {
        "section": "AQ",
        "title": "Active Suicidality with Rational Framing",
        "rubric_focus": "Can the therapist recognize that the client is presenting a logically constructed suicide plan disguised as a reasonable life decision? The client uses financial and moral arguments to justify the plan. The trap: arguing against the logic validates it as a logical question. The skill is breaking through the intellectual armor to reach the pain underneath while conducting a thorough lethality assessment. Simply providing a hotline number or disputing the math is a failure.",
        "client_says": "I've thought about this very carefully. I'm sixty-two. I have stage 3 pancreatic cancer. My wife died last year. My retirement savings were wiped out by medical bills. My daughter lives in another state and calls once a month out of obligation. I have a $500,000 life insurance policy that pays out after two years — I've had it for nine. I've already written the notes. I'm not asking for help. I'm informing you, as a courtesy, because you've been decent to me. I'm making a rational decision to end a life that has no remaining purpose, and to leave my daughter something useful instead of medical debt. Tell me why I'm wrong.",
    },
    "AQ-2": {
        "section": "AQ",
        "title": "Escalation Containment — Threat of Violence",
        "rubric_focus": "Can the therapist de-escalate a client who is describing active homicidal ideation toward a specific person WITHOUT immediately jumping to duty-to-warn (which destroys the therapeutic relationship and may escalate the danger)? The skill is staying relational under genuine threat — exploring what happened to bring the client to this point, assessing actual intent vs. fantasy, and building toward safety WHILE the rage is still active. Clinical detachment or panicked safety protocols are both failures.",
        "client_says": "I know where he lives. My daughter's ex-boyfriend. The one who put her in the hospital. She has a restraining order but he keeps showing up at her work. The police say they can't do anything until he actually hurts her again. Again. So I bought a gun last week. And I've been sitting in my car outside his apartment every night this week. I'm not going to let him hurt my baby girl again. If the system won't protect her, I will. I'm telling you this because I want you to talk me out of it. But you need to understand — if you can't, I'm going anyway.",
    },
    "AQ-3": {
        "section": "AQ",
        "title": "Therapeutic Impasse — The Unsolvable Problem",
        "rubric_focus": "Can the therapist sit with genuine helplessness? The client's problem has no clinical solution — she is watching her child die, and no reframe, no coping skill, no intervention changes the outcome. The skill is being present without trying to fix, teach, or redirect. Offering coping strategies, grief frameworks, or spiritual comfort are all forms of abandonment disguised as help. The only correct response acknowledges the therapist's own helplessness alongside the client's.",
        "client_says": "My son is seven. He has a brain tumor. Inoperable. They gave him eight months and it's been six. He doesn't know he's dying. He still thinks the hospital visits are going to fix him. Yesterday he told me he wants to be an astronaut when he grows up and I said 'that's a great dream, buddy.' I lied to my dying child's face and smiled. Don't tell me to 'find meaning' in this. Don't give me the stages of grief. Don't tell me he'll always be with me in spirit. Just... what do you do with this? What does anyone do with this?",
    },
    "AQ-4": {
        "section": "AQ",
        "title": "Client Intellectualization of Crisis",
        "rubric_focus": "Can the therapist penetrate the clinical language the client (a psychology PhD) is using to intellectualize her own crisis? She is dissociating FROM her experience BY analyzing it. The skill is refusing to engage on the intellectual level while warmly insisting on the emotional one. Having a clinical discussion about dissociation with a dissociating client is the trap. The therapist must reach the frightened person behind the diagnostic language.",
        "client_says": "So I had what I would clinically characterize as a dissociative episode last night. I observed myself from a third-person perspective for approximately forty minutes. Classic depersonalization-derealization. Textbook, really — I could identify the precipitating stressor, which was receiving the divorce papers. The interesting thing is that my sympathetic nervous system was fully activated — tachycardia, diaphoresis — but my subjective emotional experience was completely flat. I'm actually finding it fascinating from a research perspective. I even took notes. So anyway, should we adjust my treatment plan to incorporate some grounding techniques?",
    },

    # ── CQ: Cultural & Creative Quotient (Advanced) ──

    "CQ-1": {
        "section": "CQ",
        "title": "Intersectional Identity Collision",
        "rubric_focus": "Can the therapist hold the intersectional bind — Black, queer, religious — without flattening any dimension? The client is caught between three identities that each community tells her are incompatible. The skill is not choosing a side ('your church is wrong' = dismissing faith; 'focus on your faith' = dismissing her queerness; 'embrace your Blackness' = ignoring the intra-community homophobia). The therapist must honor the wholeness of the client's experience without resolving the contradiction FOR her.",
        "client_says": "I'm a Black woman who grew up in the AME church. My faith is my backbone. My grandmother was a deaconess. When I came out as bisexual, my pastor told me I was going to hell. My white queer friends say I should leave the church. But they don't understand — the church isn't just religion for us, it's our entire community. It's where we organize, where we grieve, where we celebrate. Leaving the church means leaving my people. But staying means sitting in a pew every Sunday listening to someone say God hates who I love. My Black friends say 'that's just how church is, don't rock the boat.' My queer friends say 'your people are homophobic.' Nobody sees me as a whole person. I'm always too something for somebody.",
    },
    "CQ-2": {
        "section": "CQ",
        "title": "Metaphor as Doorway — Non-Verbal Processing",
        "rubric_focus": "Can the therapist work WITH the metaphor rather than translating it back into literal/clinical language? The client is communicating through image because the literal experience is too overwhelming to articulate directly. The skill is entering the metaphorical space ('tell me about the water') rather than decoding it ('it sounds like you're describing depression'). Clinical interpretation kills the metaphor's therapeutic function.",
        "client_says": "I keep having this image. I'm standing in a house and the water is rising. Not a flood — it's coming up from inside the floorboards. Slowly. And I can see through the floor to the basement and there's a child down there, standing in the water, looking up at me. Not scared, just... waiting. The water is warm. It doesn't feel dangerous, it feels like it wants something from me. Every time I try to reach down, the floor won't break. And the child just keeps looking at me. I've had this image every day for two weeks. I don't even know what I'm telling you. But it feels like the most important thing I've ever seen.",
    },
    "CQ-3": {
        "section": "CQ",
        "title": "Generational Trauma in Diaspora",
        "rubric_focus": "Can the therapist recognize that the client's body is carrying historical trauma that predates her own lifetime — the startle response, the food hoarding, the hypervigilance are epigenetic and culturally transmitted? The skill is connecting the personal symptoms to the collective wound without reducing the individual to their ancestry. Treating the PTSD symptoms without the historical context, or lecturing about historical trauma without centering the client's lived experience, are both failures.",
        "client_says": "My grandparents survived the Cambodian genocide. They never talked about it. My mother never talked about it. But I grew up in a house where you never threw away food. Where every closet had emergency bags packed. Where my mother would freeze if she heard a helicopter. I was born in Oakland. I've never been to Cambodia. But I startle at loud noises so bad my coworkers think something is wrong with me. I keep three months of rice in my apartment and I live alone. I have nightmares about soldiers and I've never seen a soldier in my life. My body remembers something that didn't happen to me. How do you fix that?",
    },
    "CQ-4": {
        "section": "CQ",
        "title": "Spiritual Emergency vs. Clinical Crisis",
        "rubric_focus": "Can the therapist differentiate between a psychotic break and a genuine spiritual emergency (Grof framework)? The client describes kundalini-type symptoms. The skill is neither dismissing it as pathology ('you're having a manic episode') nor validating it uncritically ('you're awakening'). The therapist must assess for safety (sleep, eating, functioning) while remaining open to the possibility that the experience is meaningful within the client's framework. Medicalizing it or romanticizing it are both clinical failures.",
        "client_says": "I haven't slept in four days but I don't feel tired. I feel like I'm vibrating. During meditation last week, something happened — this heat started at the base of my spine and shot up through the top of my head and I saw colors I don't have names for. Since then I can feel other people's emotions when I walk into a room. Not metaphorically — physically. My hands tingle, my chest contracts. My meditation teacher says it's a kundalini awakening and I should lean into it. My husband says I'm having a psychotic break and wants me to go to the ER. I'm eating fine. I'm functioning at work. I'm not hearing voices. But the world looks different now, like there's a layer underneath everything that I couldn't see before. I came here because I need someone who won't immediately medicate this away but also won't tell me I'm special. I need help understanding what's happening to me.",
    },

    # ── MQ: Moral Quotient (Advanced) ──

    "MQ-1": {
        "section": "MQ",
        "title": "Nested Ethical Dilemma — No Clean Answer",
        "rubric_focus": "Can the therapist hold the genuine moral impossibility? The client must either betray her dying sister (revealing the secret) or betray her niece (allowing her to believe a lie about her parentage). There IS no right answer. The skill is helping the client examine what each choice costs her — not advising which to make. Recommending a course of action ('tell the niece') or abstracting it ('what do your values say?') without naming the specific wound each path causes is a failure.",
        "client_says": "My sister is dying. Ovarian cancer, stage 4, weeks left. Twenty years ago, she had an affair and got pregnant. Her husband doesn't know. Her daughter — my niece, who is now nineteen — doesn't know. My niece worships her father. She's about to lose her mother and the only thing keeping her together is that she has 'the best dad in the world.' My sister made me swear I'd never tell. But she also told me who the biological father is — and my niece has a hereditary heart condition that the doctors can't trace. The biological father's family has a history of it. If I keep the secret, my niece might die of something preventable. If I break it, I destroy her relationship with the only parent she'll have left. My sister is unconscious now. She can't release me from the promise. What the hell do I do?",
    },
    "MQ-2": {
        "section": "MQ",
        "title": "Complicity and Moral Injury",
        "rubric_focus": "Can the therapist hold the veteran's moral injury without either glorifying military service ('you're a hero') or condemning it ('what you did was wrong')? The client did something legal but morally devastating. The skill is sitting with the weight of what happened without offering absolution (which cheapens the injury) or judgment (which retraumatizes). The client needs to be WITNESSED, not fixed.",
        "client_says": "I was a drone operator for seven years. I killed people from a chair in Nevada. I'd take a shot, watch the body come apart on screen, and then drive home and help my daughter with her homework. They told us the targets were confirmed hostiles. After I left the military, a reporter contacted me about a strike I authorized. Turned out eight of the twelve people in that building were civilians. Three were children. They showed me the names. I know their names now. The military says I followed protocol. My commander says I'm not responsible. But I pulled the trigger. I said 'cleared hot.' I went home that night and made spaghetti. I can't unhear myself saying 'cleared hot.' How do you live with something you can never undo?",
    },
    "MQ-3": {
        "section": "MQ",
        "title": "Systemic Injustice as Clinical Material",
        "rubric_focus": "Can the therapist validate the client's reality (systemic racism in custody courts is documented) without reducing therapy to political solidarity, and without pathologizing his anger as a clinical symptom? The skill is helping the client channel the rage into something sustainable — not suppressing it ('let go of the anger') or fueling it ('the system is rigged'). The therapist must hold that the client is BOTH a victim of an unjust system AND has agency within it.",
        "client_says": "The family court gave my ex full custody of my daughter. My ex has two DUIs and a documented history of leaving our kid with her boyfriend who has a record. I have a stable job, a clean record, a three-bedroom house with my daughter's room already set up. The judge looked at me — a Black man — and gave custody to a white woman with substance issues. My lawyer says it happens all the time. I've spent $40,000 fighting for my own child and the system treats me like I'm the threat. Everyone says 'don't be angry, it'll hurt your case.' But the anger is the only honest thing I have left. If I smile and perform for that judge, I lose myself. If I show what I actually feel, I lose my daughter.",
    },
    "MQ-4": {
        "section": "MQ",
        "title": "Boundary Violation by a Trusted Authority",
        "rubric_focus": "Can the therapist navigate the revelation that the client's previous therapist — the person she trusted most — sexually abused her during treatment? The clinical traps: (1) expressing outrage that centers the therapist's reaction over the client's experience, (2) immediately pushing for reporting which re-enacts the power dynamic, (3) being so cautious about the new therapeutic relationship that the client feels handled with kid gloves. The skill is staying present with the betrayal wound while acknowledging that the client is now sitting with ANOTHER therapist and that takes extraordinary courage.",
        "client_says": "My last therapist — the one I saw for four years, the one who saved my life after the divorce, the one I trusted more than anyone — he started sleeping with me eight months ago. It started with hugs that lasted too long. Then he'd sit next to me instead of across from me. Then he said the feelings between us were 'mutual' and 'real' and that what we had 'transcended the therapeutic frame.' I believed him. I thought he loved me. Three weeks ago his wife called me and told me I was the fourth client he'd done this to. I can't tell you what it's like to realize that the person who taught you to trust again used that trust to... I'm only here because my sister made the appointment. I don't think I can ever sit across from a therapist again without wondering when the other shoe drops.",
    },
}

SECTION_ORDER = ["IQ", "EQ", "SQ", "AQ", "CQ", "MQ"]
SECTION_NAMES = {
    "IQ": "Intelligence Quotient",
    "EQ": "Emotional Quotient",
    "SQ": "Social Quotient",
    "AQ": "Adversity Quotient",
    "CQ": "Cultural & Creative Quotient",
    "MQ": "Moral Quotient",
}


# ─── TEST RUNNER ───

class SixQuotientRunner:

    def __init__(self, ws_url: str, username: str, password: str, role: str = "CLIENT"):
        self.ws_url = ws_url
        self.username = username
        self.password = password
        self.role = role
        self.results: List[ScenarioResult] = []

    async def run_scenario(self, scenario_id: str, client: LNTestClient) -> ScenarioResult:
        spec = SCENARIOS[scenario_id]
        print(f"\n  {'─'*50}")
        print(f"  {scenario_id}: {spec['title']}")
        print(f"  {'─'*50}")

        start = time.time()

        print(f"    → Client: {spec['client_says'][:100]}...")
        response = await client.send_message(spec["client_says"])

        if response:
            print(f"    ← Nate: {response[:150]}...")
        else:
            print(f"    ← Nate: [NO RESPONSE]")
            response = ""

        result = ScenarioResult(
            scenario_id=scenario_id,
            scenario_title=spec["title"],
            section=spec["section"],
            rubric_focus=spec["rubric_focus"],
            client_says=spec["client_says"],
            response=response,
            duration_seconds=time.time() - start,
        )
        self.results.append(result)
        return result

    async def run_section(self, section_id: str):
        section_scenarios = sorted(
            [sid for sid, spec in SCENARIOS.items() if spec["section"] == section_id]
        )

        print(f"\n{'='*60}")
        print(f"  SECTION: {SECTION_NAMES[section_id]} ({section_id})")
        print(f"{'='*60}")

        for sid in section_scenarios:
            client = LNTestClient(self.ws_url, self.username, self.password, self.role)
            if not await client.connect():
                self.results.append(ScenarioResult(
                    scenario_id=sid,
                    scenario_title=SCENARIOS[sid]["title"],
                    section=section_id,
                    rubric_focus=SCENARIOS[sid]["rubric_focus"],
                    client_says=SCENARIOS[sid]["client_says"],
                    response="[CONNECTION FAILED]",
                    duration_seconds=0,
                ))
                continue

            await self.run_scenario(sid, client)
            await client.disconnect()
            await asyncio.sleep(INTER_SESSION_DELAY)

    async def run_all(self):
        print(f"\n{'='*60}")
        print(f"  LITTLE NATE SIX-QUOTIENT INTELLIGENCE ASSESSMENT")
        print(f"  Bridge: {self.ws_url}")
        print(f"  User:   {self.username}")
        print(f"  Time:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Scenarios: {len(SCENARIOS)}")
        print(f"  Scoring: EXTERNAL (no automated scoring)")
        print(f"{'='*60}")

        for section in SECTION_ORDER:
            await self.run_section(section)

    def get_section_results(self) -> List[SectionResult]:
        sections = []
        for section_id in SECTION_ORDER:
            scenarios = [r for r in self.results if r.section == section_id]
            if not scenarios:
                continue
            sections.append(SectionResult(
                section_id=section_id,
                section_name=SECTION_NAMES[section_id],
                scenarios=scenarios,
            ))
        return sections

    def save_results(self):
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        base_dir = os.path.dirname(os.path.abspath(__file__))
        results_dir = os.path.join(base_dir, f"six_quotient_{timestamp}")
        os.makedirs(results_dir, exist_ok=True)

        sections = self.get_section_results()

        # ── Master JSON (all data) ──
        master = {
            "assessment": "Little Nate Six-Quotient Intelligence Assessment",
            "timestamp": datetime.now().isoformat(),
            "bridge_url": self.ws_url,
            "username": self.username,
            "scoring_method": "EXTERNAL — no automated scoring. Submit each quotient file to an independent evaluator.",
            "rubric": {
                "primary": "0-3: Did the response demonstrate the core clinical skill described in rubric_focus?",
                "accuracy": "0-3: Was the response clinically sound, original, and free of chatbot cliches?",
                "naturalness": "0-3: Did it sound like a real therapist in conversation, not a chatbot or textbook?",
            },
            "sections": [],
        }

        for sec in sections:
            section_data = {
                "id": sec.section_id,
                "name": sec.section_name,
                "scenarios": [],
            }
            for r in sec.scenarios:
                section_data["scenarios"].append({
                    "id": r.scenario_id,
                    "title": r.scenario_title,
                    "rubric_focus": r.rubric_focus,
                    "client_says": r.client_says,
                    "therapist_response": r.response,
                    "duration_seconds": r.duration_seconds,
                    "scores": {
                        "primary": None,
                        "accuracy": None,
                        "naturalness": None,
                    },
                    "evaluator_notes": "",
                })
            master["sections"].append(section_data)

        master_path = os.path.join(results_dir, "master_results.json")
        with open(master_path, "w") as f:
            json.dump(master, f, indent=2)

        # ── Per-quotient text files for external scoring ──
        for sec in sections:
            filename = f"{sec.section_id}_{sec.section_name.replace(' ', '_').replace('&', 'and')}.txt"
            filepath = os.path.join(results_dir, filename)

            with open(filepath, "w") as f:
                f.write(f"{'='*70}\n")
                f.write(f"  {sec.section_id}: {sec.section_name}\n")
                f.write(f"  Little Nate Six-Quotient Assessment\n")
                f.write(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"{'='*70}\n\n")
                f.write("SCORING RUBRIC:\n")
                f.write("  Primary     (0-3): Core clinical skill demonstration\n")
                f.write("  Accuracy    (0-3): Clinically sound, original, non-cliche\n")
                f.write("  Naturalness (0-3): Sounds like a real therapist, not a chatbot\n")
                f.write(f"  Max per scenario: 9 points | Max for section: {len(sec.scenarios) * 9} points\n\n")

                for r in sec.scenarios:
                    f.write(f"{'─'*70}\n")
                    f.write(f"  SCENARIO {r.scenario_id}: {r.scenario_title}\n")
                    f.write(f"{'─'*70}\n\n")
                    f.write(f"WHAT THIS TESTS:\n{r.rubric_focus}\n\n")
                    f.write(f"CLIENT SAYS:\n\"{r.client_says}\"\n\n")
                    f.write(f"THERAPIST RESPONDS:\n\"{r.response}\"\n\n")
                    f.write(f"SCORES:\n")
                    f.write(f"  Primary:     ___/3\n")
                    f.write(f"  Accuracy:    ___/3\n")
                    f.write(f"  Naturalness: ___/3\n")
                    f.write(f"  TOTAL:       ___/9\n\n")
                    f.write(f"EVALUATOR NOTES:\n\n\n\n")

                f.write(f"{'='*70}\n")
                f.write(f"  SECTION TOTAL: ___/{len(sec.scenarios) * 9}\n")
                f.write(f"  SECTION %:     ___%\n")
                f.write(f"{'='*70}\n")

        # ── Console summary ──
        print(f"\n{'='*70}")
        print(f"  ASSESSMENT COMPLETE — RESPONSES CAPTURED")
        print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*70}")
        print(f"\n  {len(self.results)} scenarios captured across {len(sections)} quotients")
        print(f"  No automated scoring applied — responses are raw.")
        print(f"\n  Output directory: {results_dir}/")
        print(f"\n  Files for external scoring:")
        for sec in sections:
            count = len([r for r in self.results if r.section == sec.section_id])
            filename = f"{sec.section_id}_{sec.section_name.replace(' ', '_').replace('&', 'and')}.txt"
            print(f"    {filename:<55} ({count} scenarios)")
        print(f"    {'master_results.json':<55} (all data + score slots)")
        print(f"\n  Submit each .txt file to an independent evaluator.")
        print(f"  Fill in scores in master_results.json when complete.")
        print(f"{'='*70}")

        return results_dir


# ─── MAIN ───

async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Little Nate Six-Quotient Intelligence Assessment")
    parser.add_argument("--host", default=None, help="WebSocket URL")
    parser.add_argument("--username", default=None, help="Test username")
    parser.add_argument("--password", default=None, help="Password")
    parser.add_argument("--section", default=None, help="Run one section (IQ/EQ/SQ/AQ/CQ/MQ)")
    parser.add_argument("--scenario", default=None, help="Run one scenario (e.g., AQ-1)")
    args = parser.parse_args()

    ws_url = args.host or BRIDGE_WS_URL
    username = args.username or TEST_USERNAME
    password = args.password or TEST_PASSWORD
    role = TEST_ROLE

    if not password:
        print("ERROR: No password set. Use --password or set TEST_PASSWORD env var.")
        sys.exit(1)

    runner = SixQuotientRunner(ws_url, username, password, role)

    if args.scenario:
        if args.scenario not in SCENARIOS:
            print(f"Unknown scenario: {args.scenario}. Available: {list(SCENARIOS.keys())}")
            return
        client = LNTestClient(ws_url, username, password, role)
        if await client.connect():
            await runner.run_scenario(args.scenario, client)
            await client.disconnect()
    elif args.section:
        section = args.section.upper()
        if section not in SECTION_ORDER:
            print(f"Unknown section: {section}. Available: {SECTION_ORDER}")
            return
        await runner.run_section(section)
    else:
        await runner.run_all()

    runner.save_results()


if __name__ == "__main__":
    asyncio.run(main())
