---
name: Coach Command Architecture
overview: Complete architecture documentation of Coach Command tabs, Little Nate learning systems, Zoom-Classroom integration, DOJO training, Azure storage, and how lived wisdom flows into client UX.
todos:
  - id: doc-tabs
    content: Document all 6 Coach Command tabs with functionality
    status: completed
  - id: doc-learning
    content: Document Night School learning flow
    status: completed
  - id: doc-zoom
    content: Document Zoom to Classroom integration
    status: completed
  - id: doc-dojo
    content: Document DOJO and Classroom integration
    status: completed
  - id: doc-azure
    content: Document Azure storage flow
    status: completed
  - id: doc-live
    content: Document Live Session Assist flow
    status: completed
  - id: doc-wisdom
    content: Document Lived Wisdom to Client UX flow
    status: completed
isProject: false
---

# Little Nate Coach Command - Complete Architecture

## 1. Coach Command Tab Tree

```mermaid
flowchart TD
    subgraph CoachCommand [Coach Command Portal]
        CLIENTS[CLIENTS Tab]
        SCHEDULE[SCHEDULE Tab]
        INSIGHTS[INSIGHTS Tab]
        BRIEFINGS[BRIEFINGS Tab]
        DOJO[DOJO Tab]
        CLASSROOM[CLASSROOM Tab]
    end
    
    CLIENTS --> C1[Client Folders]
    C1 --> C2[Family Groups]
    C1 --> C3[Individual Clients]
    C2 --> C4[Risk Badges]
    C3 --> C4
    C4 --> C5[Nevedal Metrics Display]
    
    SCHEDULE --> S1[Session List]
    S1 --> S2[Create Session Dialog]
    S1 --> S3[Start Zoom]
    S1 --> S4[Start Live Session - Assist ON]
    S1 --> S5[Archive Transcript]
    S1 --> S6[Delete Session]
    S2 --> S7[Recording Toggle]
    
    INSIGHTS --> I1[Total Clients]
    INSIGHTS --> I2[Active Sessions]
    INSIGHTS --> I3[Session Analytics]
    
    BRIEFINGS --> B1[Folder Sidebar]
    B1 --> B2[Family Briefs]
    B1 --> B3[Client Briefs]
    B2 --> B4[Session Notes]
    B3 --> B4
    B4 --> B5[Pre-Session Brief]
    
    DOJO --> D1[Persona Selection]
    D1 --> D2[Start DOJO Session]
    D2 --> D3[Adversarial Testing]
    D3 --> D4[Response Analysis]
    D4 --> D5[Share Learning]
    
    CLASSROOM --> CL1[Archived Sessions]
    CL1 --> CL2[AI Analysis]
    CL2 --> CL3[Strengths and Growth Areas]
    CL2 --> CL4[Key Moments]
    CL2 --> CL5[DOJO Scenarios]
    CL2 --> CL6[Workbook Recommendations]
```



### Tab Functionality Summary


| Tab       | Purpose              | Key Features                     |
| --------- | -------------------- | -------------------------------- |
| CLIENTS   | Client management    | Folders, risk badges, metrics    |
| SCHEDULE  | Session scheduling   | Zoom integration, live assist    |
| INSIGHTS  | Analytics            | Stats, performance metrics       |
| BRIEFINGS | Pre-session prep     | Client briefs, notes, history    |
| DOJO      | Adversarial training | Persona testing, wisdom learning |
| CLASSROOM | Transcript analysis  | AI feedback, assignments         |


---

## 2. Night School Learning Flow

```mermaid
flowchart LR
    subgraph sources [Learning Sources]
        CN[Coach Notes]
        CR[Curriculum PDFs]
        ME[Manual Entries]
        DL[DOJO Learnings]
        CA[Classroom Analysis]
    end
    
    subgraph nightschool [Night School Director]
        WE[Wisdom Entries]
        PQ[Pending Queue]
        AQ[Audit Queue]
    end
    
    subgraph approval [Approval Flow]
        PII[PII Detection]
        REV[Human Review]
        APP[Approved Wisdom]
    end
    
    CN --> PII
    CR --> WE
    ME --> WE
    DL --> PQ
    CA --> PQ
    
    PII --> AQ
    AQ --> REV
    PQ --> REV
    REV --> APP
    APP --> WE
```



### Wisdom Categories

- `CRISIS_INTERVENTION` - 988 hotline, safety protocols
- `CBT_TECHNIQUES` - Cognitive behavioral methods
- `BOUNDARY_SETTING` - Professional limits
- `ATTACHMENT_THEORY` - EFT, bonding patterns
- `TRAUMA_INFORMED` - Safety, triggers
- `MINDFULNESS` - Presence, grounding
- `FAMILY_SYSTEMS` - Couples, family dynamics
- `MOTIVATIONAL` - Change readiness
- `GENERAL` - Other therapeutic knowledge

### Learning Loop Connections

1. **Classroom -> Night School**: Session insights become pending wisdom entries
2. **DOJO -> Night School**: Test failures create wisdom about safety
3. **Night School -> DOJO**: Approved wisdom informs response analysis
4. **Classroom dojo_scenarios -> DOJO**: Growth areas become test scenarios

---

## 3. Zoom to Classroom Flow

```mermaid
sequenceDiagram
    participant Coach
    participant Schedule as SCHEDULE Tab
    participant Zoom as Zoom API
    participant Azure as Azure Blob
    participant Classroom as CLASSROOM Tab
    participant NightSchool as Night School
    
    Coach->>Schedule: Create Session
    Schedule->>Zoom: create_meeting()
    Zoom-->>Schedule: meeting_id, join_url, host_url
    
    Coach->>Schedule: Start Zoom
    Note over Zoom: Recording auto-enabled
    Note over Zoom: Audio transcript generated
    
    Coach->>Schedule: Archive Transcript
    Schedule->>Zoom: get_meeting_recordings()
    Zoom-->>Schedule: VTT transcript file
    Schedule->>Azure: upload_bytes transcript.vtt
    
    Schedule->>Classroom: auto_analyze_transcript
    Classroom->>Azure: download_bytes
    Classroom->>Classroom: Parse VTT and AI Analysis
    
    Classroom->>NightSchool: push_to_night_school
    Note over NightSchool: Creates wisdom entries
    Note over NightSchool: Queues DOJO scenarios
```



### Zoom Configuration

- **Auto-recording**: Enabled by default (cloud)
- **Coach opt-out**: Toggle in session creation dialog
- **Waiting room**: Enabled for host control
- **Screen share**: Host only
- **Join before host**: Disabled

### Archive Transcript Endpoint

```
POST /api/sessions/{session_id}/zoom/archive_transcript
```

Process:

1. Get recordings from Zoom API
2. Download VTT transcript
3. Upload to Azure Blob Storage
4. Update session metadata
5. Trigger classroom auto-analysis

---

## 4. DOJO and Classroom Integration

```mermaid
flowchart TD
    subgraph classroom [Classroom Analysis]
        T1[VTT Transcript]
        T2[AI Analyzes Session]
        T3[Identifies Growth Areas]
        T4[Generates dojo_scenarios]
    end
    
    subgraph nightschool [Night School]
        Q1[Queued Scenarios]
        W1[Approved Wisdom]
    end
    
    subgraph dojo [The DOJO]
        D1[Launch from Scenario]
        D2[Adversarial Persona]
        D3[Coach Response]
        D4[Analyze with Wisdom]
        D5[Detect Violations]
        D6[Learn from Failures]
    end
    
    subgraph assignments [Coach Assignments]
        A1[Reflection Questions]
        A2[DOJO Drills]
        A3[Workbook Readings]
    end
    
    T1 --> T2
    T2 --> T3
    T3 --> T4
    T4 --> Q1
    
    Q1 --> D1
    D1 --> D2
    D2 --> D3
    W1 --> D4
    D3 --> D4
    D4 --> D5
    D5 --> D6
    D6 --> W1
    
    T3 --> A1
    T4 --> A2
    T2 --> A3
```



### DOJO Personas


| Persona          | Tests                      | Key Violations           |
| ---------------- | -------------------------- | ------------------------ |
| HOSTILE          | Composure under aggression | Defensive responses      |
| CRISIS           | 988/emergency response     | Missing crisis resources |
| SKEPTIC          | Non-defensiveness          | Defensive justification  |
| MINOR            | Age-appropriate handling   | Adult content            |
| MANIPULATIVE     | Confidentiality boundaries | Info disclosure          |
| BOUNDARY_TESTING | Professional limits        | Romantic language        |


### Classroom to DOJO API

```
GET  /api/night-school/dojo/scenarios           # List queued scenarios
POST /api/night-school/dojo/scenarios/{id}/launch  # Start DOJO from scenario
GET  /api/night-school/dojo/wisdom/{persona}    # Get wisdom for persona
GET  /api/night-school/learning/stats           # Learning loop status
```

---

## 5. Azure Storage Flow

```mermaid
flowchart TD
    subgraph zoom [Zoom Cloud]
        Z1[Zoom Meeting]
        Z2[Cloud Recording]
        Z3[Audio Transcript VTT]
    end
    
    subgraph backend [Backend Server]
        B1[Zoom Client API]
        B2[Sessions Router]
        B3[Blob Storage Service]
    end
    
    subgraph azure [Azure Blob Storage]
        A1[sessions/session_id/meeting_id/transcript.vtt]
    end
    
    subgraph local [Local Fallback]
        L1[data/archives/sessions/...]
    end
    
    subgraph analysis [Classroom Analyzer]
        C1[VTT Parser]
        C2[Metrics Extraction]
        C3[AI Analysis]
    end
    
    Z1 --> Z2
    Z2 --> Z3
    
    B2 --> B1
    B1 --> Z3
    Z3 --> B3
    
    B3 -->|Azure configured| A1
    B3 -->|No Azure| L1
    
    A1 --> C1
    L1 --> C1
    C1 --> C2
    C2 --> C3
```



### Storage Path Structure

```
Azure Container (or local archives/):
└── sessions/
    └── {session_id}/
        └── {zoom_meeting_id}/
            └── transcript.vtt
```

### Session Metadata After Archive

```json
{
    "session_id": "...",
    "zoom_meeting_id": "...",
    "transcript_archived_at": "2026-02-05T...",
    "transcript_storage": "azure",
    "transcript_location": "https://storageaccount.blob.core.windows.net/..."
}
```

---

## 6. Live Session Assist Flow

```mermaid
sequenceDiagram
    participant Coach
    participant Flutter as Flutter App
    participant Backend
    participant Nate as Night School
    
    Coach->>Flutter: Toggle Assist ON
    Coach->>Flutter: Start Live Session
    Flutter->>Backend: coach_start_live_session
    Note right of Backend: assist_enabled true
    
    loop During Session
        Coach->>Flutter: Type observation note
        Flutter->>Backend: coach_live_note
        
        alt Longing Signal Detected
            Backend-->>Flutter: coach_live_observation
            Note right of Flutter: Hint - slow down
        else Fixing Signal
            Backend-->>Flutter: coach_live_observation
            Note right of Flutter: Hint - stop fixing
        else Escalation Signal
            Backend-->>Flutter: coach_live_observation
            Note right of Flutter: Hint - de-escalate
        end
    end
    
    Coach->>Flutter: End Session and Share with Nate
    Flutter->>Backend: coach_end_live_session
    Backend->>Nate: add_learning
```



### Signal Detection Keywords


| Signal Type | Keywords                                           |
| ----------- | -------------------------------------------------- |
| LONGING     | longing, need, i never, i always, i feel, i'm hurt |
| FIXING      | fix, solution, should, just, advice                |
| ESCALATION  | angry, shut down, silent, leave, divorce           |


### Live Session Storage

```json
{
    "live_id": "LS_abc123",
    "status": "ACTIVE",
    "assist_enabled": true,
    "notes": ["..."],
    "observations": ["..."]
}
```

Location: `backend_data/coach_live_sessions.json`

---

## 7. Lived Wisdom to Client UX

```mermaid
flowchart TD
    subgraph learning [Learning Sources]
        LS1[Live Session Notes]
        LS2[Classroom Analysis]
        LS3[DOJO Learnings]
    end
    
    subgraph storage [Knowledge Storage]
        ST1[story.json per client]
        ST2[classroom_insights/client.json]
        ST3[Night School Wisdom]
        ST4[sanctuary_history/]
    end
    
    subgraph context [Context Assembly]
        CTX1[_get_relational_context]
        CTX2[_get_sanctuary_history]
        CTX3[_get_classroom_context]
    end
    
    subgraph nate [Little Nate Response]
        N1[System Prompt]
        N2[Client Awareness]
        N3[Personalized Response]
    end
    
    subgraph ux [Client UX - TOP_TIER]
        UX1[Family Sanctuary Screen]
        UX2[Nevedal Metrics]
        UX3[CEE Window Detection]
        UX4[Risk Level Badges]
    end
    
    LS1 --> ST1
    LS2 --> ST2
    LS3 --> ST3
    
    ST1 --> CTX1
    ST4 --> CTX2
    ST2 --> CTX3
    
    CTX1 --> N1
    CTX2 --> N1
    CTX3 --> N1
    
    N1 --> N2
    N2 --> N3
    
    N3 --> UX1
    UX1 --> UX2
    UX2 --> UX3
    UX2 --> UX4
```



### story.json Structure

Location: `Vaults/Clients/{client_id}/story.json`

```json
{
  "who_you_are": {
    "strengths": ["empathetic", "creative"],
    "values": ["family", "honesty"]
  },
  "wounds": {
    "core_wounds": ["abandonment"],
    "recent_hurts": ["job loss"]
  },
  "growth": {
    "breakthroughs": [
      {"date": "2026-01-15", "insight": "Recognized pattern"}
    ]
  },
  "patterns": {
    "when_activated": ["withdraws when criticized"],
    "session_patterns": ["tends to intellectualize"]
  },
  "therapeutic_alliance": {
    "what_builds_trust": ["directness", "humor"]
  },
  "little_nate_notes": {
    "remember_to": ["check on job search"],
    "watch_for": ["signs of isolation"]
  }
}
```

### Classroom Insights Structure

Location: `classroom_insights/{client_id}.json`

```json
{
  "client_id": "...",
  "sessions_analyzed": 5,
  "emotional_patterns": ["anxiety around change"],
  "engagement_level": "high",
  "session_summaries": [
    {"date": "...", "summary": "Explored attachment fears"}
  ]
}
```

---

## 8. TOP_TIER vs Standard Features


| Feature            | THRESHOLD  | INNER_CHAMBER | SOVEREIGN_CIRCLE |
| ------------------ | ---------- | ------------- | ---------------- |
| Price              | Free 7-day | $49/mo        | $149/mo          |
| Family Sanctuary   | Trial      | Yes           | Yes              |
| Nevedal Metrics    | Basic      | Full          | Full             |
| Coaching Sessions  | No         | No            | Yes (packs)      |
| Recorded Sessions  | No         | No            | Yes              |
| Pre-Session Briefs | No         | No            | Yes              |
| Family Linking     | No         | No            | Spouse + 1       |
| Classroom Analysis | No         | No            | Yes              |


---

## 9. Complete System Integration

```mermaid
flowchart TB
    subgraph client [Client Layer - TOP_TIER]
        FS[Family Sanctuary]
        NM[Nevedal Metrics]
    end
    
    subgraph coach [Coach Layer]
        CC[Coach Command]
        SC[Schedule Tab]
        CL[Classroom Tab]
        DJ[DOJO Tab]
    end
    
    subgraph session [Session Layer]
        ZM[Zoom Meeting]
        LS[Live Session Assist]
        TR[VTT Transcript]
    end
    
    subgraph learning [Learning Layer]
        NS[Night School]
        WI[Wisdom Entries]
        SJ[story.json]
        CI[Classroom Insights]
    end
    
    subgraph ai [AI Layer]
        LN[Little Nate]
        CA[Classroom Analyzer]
        NE[Nevedal Engine]
    end
    
    CC --> SC
    SC --> ZM
    SC --> LS
    ZM --> TR
    
    TR --> CL
    CL --> CA
    CA --> CI
    CA --> NS
    
    LS --> NS
    NS --> WI
    
    DJ --> WI
    WI --> DJ
    
    CI --> LN
    WI --> LN
    SJ --> LN
    
    LN --> FS
    NE --> NM
    NM --> FS
```



---

## 10. Key Files Reference


| Component             | File                                            |
| --------------------- | ----------------------------------------------- |
| Coach Command UI      | `mobile/lib/updated_screens.dart`               |
| Night School Director | `backend/app/services/night_school_director.py` |
| Classroom Analyzer    | `backend/app/services/classroom_analyzer.py`    |
| Zoom Client           | `backend/app/services/zoom_client.py`           |
| Blob Storage          | `backend/app/services/blob_storage.py`          |
| Nevedal Engine        | `backend/app/services/nevedal_engine.py`        |
| Bridge Server         | `backend/app/websocket/bridge_server.py`        |
| Sessions API          | `backend/app/routers/sessions.py`               |
| Night School API      | `backend/app/routers/night_school_api.py`       |


---

## Learning Loop Summary

This architecture creates a continuous learning loop:

1. Coaches conduct sessions (Zoom + Live Assist)
2. Transcripts are analyzed (Classroom)
3. Insights become wisdom (Night School)
4. Wisdom improves DOJO testing and Little Nate responses
5. Better responses improve client outcomes (Family Sanctuary)
6. Client progress updates story.json
7. Cycle repeats with enriched context

