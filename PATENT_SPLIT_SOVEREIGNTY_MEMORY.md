# PROVISIONAL PATENT APPLICATION

## SPLIT-SOVEREIGNTY MEMORY MODEL FOR AI-ASSISTED THERAPEUTIC COMPANIONS

**Filing Date:** March 2, 2026
**Inventor:** Dr. Nathan Nevedal, Stafford, Texas 77477
**Assignee:** Clinical Sovereignty Lab / Sovereign Sanctuary

---

## CROSS-REFERENCE TO RELATED APPLICATIONS

This application is related to but filed independently from the following patent applications by the same inventor:

1. **"Quantum Emotional Coherence"** series (6 provisional applications filed February–March 2026, Customer # 224423) — which describes, among other inventions, a quantum-inspired emotional coherence formula, a noetic helix cognitive architecture, and an oscillating dual-process echo (ODPE) method for dual-topology cognitive evaluation. The present application's federated memory architecture may be queried with ODPE-driven adaptive context budgets but is not dependent on the ODPE system.

2. **"Oscillating Dual-Process Echo: Systems and Methods for Applying Concurrent Geometric Polyhedron Topologies to Multi-Agent Cognitive Evaluation"** filed March 2026 — which describes a domain-agnostic method for structuring multi-agent evaluation using geometric polyhedron topologies. The ODPE method's adaptive resource allocation mechanism (LOCKED → compressed retrieval, TENSION → expanded retrieval) may govern the context budget for federated queries against the split-sovereignty memory stores described herein.

---

## FIELD OF THE INVENTION

The present invention relates to artificial intelligence memory architectures for therapeutic companion systems, and more particularly to a split-sovereignty memory model that distributes conversation memory between a server-side distilled knowledge store and a client-side raw conversation archive, with federated on-device query delegation and emotional coherence-driven memory distillation.

---

## BACKGROUND OF THE INVENTION

### Prior Art Limitations

Existing AI companion and chatbot systems employ one of three memory architectures, each with significant limitations:

**1. Cloud-Only Storage.** Systems such as ChatGPT, Replika, and similar conversational AI platforms store all conversation history on remote servers. Users have no control over data retention, cannot search their history using local compute, and face privacy concerns regarding the storage of sensitive therapeutic disclosures. In the mental health domain, cloud-only storage creates regulatory and ethical vulnerabilities, as raw therapeutic conversations contain protected health information (PHI) that may be subject to HIPAA, GDPR, or state-level privacy regulations.

**2. Local-Only Storage.** Some therapy apps store conversations exclusively on the user's device. While this maximizes privacy, it prevents the AI from developing longitudinal understanding across sessions, limits the AI's ability to detect long-term emotional patterns, and loses all data when the user changes devices. The AI cannot build a cumulative model of the user's psychological growth because each device is an isolated silo.

**3. Simple Synchronization.** Systems that mirror data between server and client (e.g., iCloud sync, Firebase) solve the device-switching problem but reintroduce cloud storage concerns and provide no mechanism for the server to hold a qualitatively different representation than the client. The server and client hold identical copies, wasting storage and offering no architectural distinction between what each party needs.

None of these prior art approaches provide:
- A mechanism for the server to hold **distilled psychological insight** while the client holds **raw conversation data**
- A protocol for the server to **query the client device** for specific information without the client sending its entire history
- A method for **emotional coherence-driven distillation** that transforms ephemeral conversations into structured identity representations

### Objects of the Invention

It is an object of the present invention to provide an AI therapeutic companion memory system in which data sovereignty is structurally enforced by architecture, not merely by policy.

It is a further object to provide a federated query delegation protocol that enables the AI to access client-device conversation history without requiring bulk data transmission.

It is a still further object to provide an emotional coherence engine that distills raw therapeutic conversations into structured identity representations using quantum-inspired emotional coherence mathematics.

---

## SUMMARY OF THE INVENTION

The present invention provides a Split-Sovereignty Memory Model comprising three interconnected innovations:

### Innovation 1: Dual-Store Architecture

The system maintains two qualitatively distinct stores:

- **Server Store (PostgreSQL):** Holds conversation history as a primary database with full-text search indexing. Entries are processed by an emotional coherence engine and distilled into "Identity Crystals" — structured representations of the user's psychological patterns, growth milestones, and emotional signatures. Raw conversation entries are retained in PostgreSQL for operational recall, while the distilled crystals represent the server's cumulative understanding. A capped JSON backup (1,000 entries) provides disaster recovery.

- **Client Store (SQLite with FTS5):** Holds the complete, uncapped lifetime conversation history on the user's device. This store is never transmitted to the server in bulk. It uses SQLite Full-Text Search version 5 (FTS5) for efficient local querying. The client store serves as the user's sovereign copy of every exchange.

Neither store alone provides a complete picture. The server holds distilled insight (what the user's patterns mean); the client holds raw data (what was actually said). This separation is not a limitation — it is the core architectural innovation.

### Innovation 2: Federated On-Device Query Delegation

When the AI companion needs to recall information from past conversations, the system executes a federated search:

1. The server performs a PostgreSQL full-text search on its conversation_history table using GIN-indexed tsvector matching
2. Simultaneously, the server sends a `device_search_request` message to the connected client via WebSocket, containing a query identifier, search terms, result limit, and context
3. The client application checks the user's consent preference (stored locally as one of: always allow, ask each time, or never)
4. If consent is granted, the client executes an FTS5 MATCH query against its local SQLite database
5. Only the matching results (not the full database) are transmitted back to the server as `device_search_results` with a timeout of 5 seconds
6. The server merges both result sets by relevance score, deduplicates by content hash, and returns the unified results to the AI context

If the user declines or the device is offline, the AI proceeds with server-side results only. The protocol includes a `device_search_declined` message type for explicit refusal.

### Innovation 3: Emotional Coherence-Driven Memory Distillation

The "Me2Me" pipeline absorbs conversation history through a clinical coherence engine based on the Nevedal Formula for quantum emotional coherence:

```
C_emo(t) = [β · p_ent · T_tunnel] / [γ_env + E_G^(joint)/ℏ] × exp[-(γ_env + E_G^(joint)/ℏ) × t]
```

Where:
- C_emo(t) represents the emotional coherence function over time
- β is the coupling strength between therapeutic and emotional states
- p_ent is the entanglement probability derived from voice biometric analysis
- T_tunnel is the tunneling coefficient through emotional barriers
- γ_env is the environmental decoherence rate
- E_G^(joint) is the joint gravitational energy representing relational depth

The pipeline operates as follows:

1. **Imprint Accumulation:** Raw conversation entries marked `me2me_absorbed = FALSE` are periodically scanned (batch size: 100 entries). Each entry is processed through the coherence engine to extract emotional vectors.

2. **Pattern Crystallization:** When sufficient imprints accumulate (configurable threshold), the system identifies statistically significant emotional patterns and crystallizes them into "Identity Crystals" — JSON objects containing the pattern type, emotional dimensions, confidence score, supporting evidence references, and temporal trajectory.

3. **Legacy Fabrication:** Identity Crystals are assembled into a "Sovereign Legacy Fabric" (SLF) — a portable, exportable representation of the user's psychological identity that can be transferred to a new device or shared with a new therapeutic provider.

4. **Absorption Tracking:** The `me2me_absorbed` boolean column in the conversation_history table ensures each entry is processed exactly once, with a partial PostgreSQL index on `WHERE me2me_absorbed = FALSE` for efficient batch queries.

---

## DETAILED DESCRIPTION OF PREFERRED EMBODIMENTS

### System Architecture

The preferred embodiment comprises:

**Server Components:**
- A PostgreSQL 15+ database hosting the `conversation_history` table with columns: id (BIGSERIAL), user_id (TEXT), session_id (TEXT), user_text (TEXT), ai_text (TEXT), word_count_user (INT), word_count_ai (INT), metadata (JSONB), me2me_absorbed (BOOLEAN), created_at (TIMESTAMPTZ)
- Five PostgreSQL indexes: user_id lookup, session_id lookup, user_id + created_at DESC compound, GIN full-text search on tsvector('english', user_text || ' ' || ai_text), and a partial index on user_id WHERE me2me_absorbed = FALSE
- A Python FastAPI backend providing REST endpoints for memory search, session grouping, and administrative operations
- A WebSocket bridge server handling real-time communication with client devices
- An ImprintAccumulator service processing unabsorbed conversation entries
- An IdentityCrystallizer service generating Identity Crystals from accumulated imprints
- Azure Blob Storage warm and cold tiers for long-term crystal archival

**Client Components:**
- A Flutter/Dart mobile application with a LocalHistoryService singleton
- A SQLite database (nate_history.db) with a `history` table and corresponding `history_fts` FTS5 virtual table
- INSERT triggers maintaining FTS5 index synchronization
- SharedPreferences-backed consent management for federated search

**Communication Protocol:**
- WebSocket-based real-time messaging between server and client
- Three new message types: `nate_history_entry` (server → client, records new conversation entry), `device_search_request` (server → client, requests local search), `device_search_results` / `device_search_declined` (client → server, returns search results or refusal)

### Write Path

When a user interacts with the AI companion:

1. The server's MemorySystem.memorize() method executes an asynchronous INSERT into the PostgreSQL conversation_history table as the primary write
2. Concurrently, the method writes to a local memory.json file as a capped backup (1,000 entries maximum, disaster recovery only)
3. The method emits a `nate_history_entry` WebSocket message to the connected client device
4. The client's LocalHistoryService receives the message and inserts the entry into its local SQLite database
5. The SQLite INSERT trigger automatically updates the FTS5 index

### Read Path (Standard Recall)

When the AI needs conversational context:

1. MemorySystem.recall_async() queries PostgreSQL: SELECT user_text, ai_text FROM conversation_history WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2
2. Results are formatted as a human-readable context string
3. If PostgreSQL is unavailable, the system falls back to reading memory.json

### Read Path (Federated Search)

When the user or AI initiates a memory search:

1. MemorySystem.search_pg() executes a PostgreSQL full-text search using ts_rank for relevance scoring
2. If the client device is connected and the user has not disabled device search, a device_search_request is dispatched via WebSocket
3. The client app checks SharedPreferences for the consent setting
4. If "always_allow" or user approves the dialog, the client runs FTS5 MATCH against local SQLite
5. Results include user_text, ai_text, created_at, and a relevance score
6. The server merges server-side and client-side results, deduplicating by content similarity
7. Merged results are returned to the requestor

### Distillation Path (Me2Me Pipeline)

1. ImprintAccumulator.absorb_from_conversations() queries: SELECT id, user_text, ai_text, session_id, created_at FROM conversation_history WHERE user_id = $1 AND me2me_absorbed = FALSE ORDER BY created_at ASC LIMIT 100
2. Each entry is analyzed through the Nevedal coherence engine to extract emotional dimensions (pitch variance, energy, speech rate correlates, linguistic markers)
3. Extracted dimensions are stored as imprint entries in the me2me_imprint_entries table
4. After processing, entries are marked: UPDATE conversation_history SET me2me_absorbed = TRUE WHERE id = ANY($1::bigint[])
5. When sufficient imprints accumulate, IdentityCrystallizer generates a Crystal and archives it

### Administrative Operations

- **Wipe:** DELETE FROM conversation_history WHERE user_id = $1, followed by clearing the backup JSON file
- **Purge:** Same as wipe, with additional clearing of imprint entries and crystals
- **Export:** SELECT all entries for a user in chronological order, packaged as part of the Sovereign Legacy Fabric

---

## CLAIMS

### System Claims

**Claim 1.** A computer-implemented system for managing AI therapeutic companion conversation memory, the system comprising:
- a server-side database storing conversation entries in a relational database with full-text search indexing;
- a client-side database on a user device storing conversation entries in a local database with full-text search capability;
- a communication channel between the server and client for transmitting new conversation entries and search queries;
- a distillation engine that processes server-side conversation entries to extract structured psychological insight representations; and
- a federated search coordinator that queries both the server-side and client-side databases and merges results.

**Claim 2.** The system of claim 1, wherein the server-side database is PostgreSQL with GIN-indexed tsvector full-text search, and the client-side database is SQLite with FTS5 full-text search.

**Claim 3.** The system of claim 1, wherein the distillation engine implements an emotional coherence function C_emo(t) = [β · p_ent · T_tunnel] / [γ_env + E_G^(joint)/ℏ] × exp[-(γ_env + E_G^(joint)/ℏ) × t] to analyze emotional patterns in conversation entries.

**Claim 4.** The system of claim 1, wherein the server-side database includes a boolean column tracking whether each conversation entry has been processed by the distillation engine, with a partial index on unprocessed entries for efficient batch querying.

**Claim 5.** The system of claim 1, wherein the communication channel is a WebSocket connection supporting at least three message types: a history entry message for recording new conversations on the client device, a search request message for querying the client device, and a search results message for returning client-side search results to the server.

**Claim 6.** The system of claim 1, further comprising a consent management module on the client device that stores user preferences for federated search authorization, the preferences including at least: always allow, ask for each request, and never allow.

**Claim 7.** The system of claim 1, wherein the server-side database maintains a capped backup file (limited to a configurable maximum number of entries) for disaster recovery purposes, the backup being a secondary store that does not limit the primary database retention.

### Method Claims

**Claim 8.** A method for recording and retrieving AI therapeutic conversation memory, comprising the steps of:
(a) receiving a user input and AI response pair during a therapeutic session;
(b) inserting the pair into a server-side relational database as a primary write;
(c) writing the pair to a capped local backup file as a secondary write;
(d) transmitting the pair to the user's device via a real-time communication channel;
(e) storing the pair on the user's device in a local database with full-text search capability;
(f) upon a search request, querying both the server-side and client-side databases; and
(g) merging the results from both databases by relevance score.

**Claim 9.** The method of claim 8, further comprising:
(h) periodically scanning the server-side database for entries not yet processed by a distillation engine;
(i) extracting emotional coherence dimensions from unprocessed entries;
(j) generating structured psychological insight representations from accumulated dimensions; and
(k) marking processed entries as absorbed.

**Claim 10.** The method of claim 8, wherein step (f) further comprises:
sending a search request message from the server to the client device;
checking a locally stored consent preference on the client device;
if consent is granted, executing a full-text search query on the local database; and
returning only matching results to the server within a timeout period.

**Claim 11.** The method of claim 10, wherein if consent is not granted or the timeout expires, the method proceeds with server-side results only.

**Claim 12.** The method of claim 8, wherein the server-side relational database stores entries with no maximum retention limit, providing lifetime conversation history.

**Claim 13.** The method of claim 9, wherein the structured psychological insight representations are portable and exportable as a data bundle that can be transferred to a new therapeutic provider or device.

**Claim 14.** The method of claim 8, wherein administrative wipe operations delete entries from both the server-side relational database and the capped backup file.

### Device Claims

**Claim 15.** A mobile computing device configured as an AI therapeutic companion client, the device comprising:
- a processor and memory;
- a local SQLite database with a full-text search virtual table storing lifetime conversation history with the AI companion;
- a WebSocket client maintaining a persistent connection to a therapeutic companion server;
- a consent management module storing user preferences for federated search authorization; and
- a search responder module that, upon receiving a search request from the server, checks consent and executes a local full-text search if authorized.

**Claim 16.** The device of claim 15, wherein the local database stores entries without any maximum retention limit, enabling lifetime on-device conversation history.

**Claim 17.** The device of claim 15, wherein the consent management module presents a user interface allowing selection among: always allow device searches, ask for permission on each search request, and never allow device searches.

**Claim 18.** The device of claim 15, wherein the search responder module measures search execution time and reports it to the server along with search results.

**Claim 19.** The device of claim 15, further comprising a history recording module that receives conversation entries from the server via WebSocket and inserts them into the local database in real time as conversations occur.

**Claim 20.** The device of claim 15, wherein the full-text search virtual table is maintained in synchronization with the primary conversation table via database triggers that execute on each insert operation.

**Claim 21.** A computer-readable medium storing instructions that, when executed by a processor, cause the processor to perform the method of claim 8.

### Always-On Semantic Recall Claims (CIP Extension — March 7, 2026)

**Claim 22.** The system of claim 1, further comprising:
- a vector embedding database comprising a plurality of semantic indexes, each index storing vector embeddings of a distinct content type including at least conversations, vault files, wisdom extractions, identity patterns, session notes, and photo analyses;
- an always-on semantic recall module that, upon receiving any user message, automatically generates a vector embedding of the message and queries all semantic indexes concurrently to retrieve semantically similar past content without requiring explicit user search intent; and
- a relevance-gated injection module that filters retrieved results by a minimum relevance score threshold and injects only qualifying results into the AI companion's context for natural reference during response generation.

**Claim 23.** The system of claim 22, wherein the vector embedding database comprises six separate indexes queried concurrently with a top-K retrieval parameter of at least 30 per index, and the relevance score threshold is configurable with a default minimum of 0.30.

**Claim 24.** The system of claim 22, further comprising an entity extraction module that, upon each conversation memorization, extracts structured metadata from the combined user input and AI response using pattern-based extraction without invoking a large language model, the extracted metadata comprising at least: color references, clothing items, people mentioned, places referenced, emotional states, therapeutic topics, and temporal references, stored as a JSON object within the conversation record's metadata column.

**Claim 25.** The method of claim 8, further comprising:
(l) upon receiving any user message, generating a vector embedding of the message text;
(m) querying a plurality of semantic vector indexes concurrently using the embedding to retrieve semantically similar content from at least six content categories;
(n) filtering the retrieved results to include only those with a relevance score above a configurable threshold; and
(o) injecting the filtered results into the AI companion's response context for natural conversational reference, without requiring the user to explicitly request a memory search.

**Claim 26.** The method of claim 25, wherein step (l) through (o) execute at zero marginal cost by utilizing edge-distributed vector databases that charge no per-query fees, enabling the always-on recall to operate on every user message without cost constraints.

**Claim 27.** The method of claim 8, further comprising:
at the time of each conversation memorization in step (b), extracting structured entities from the combined user input and AI response text using pattern matching, the entities including colors, clothing, people, places, emotions, topics, and temporal references, and storing the extracted entities as metadata within the conversation record.

---

## ABSTRACT

A split-sovereignty memory architecture for AI-assisted therapeutic companion systems distributes conversation memory between a server-side relational database and a client-side local database. The server holds both raw conversation entries and distilled psychological insight representations ("Identity Crystals") generated by an emotional coherence engine based on the Nevedal Formula. The client device holds lifetime raw conversation history in a full-text searchable local database. A federated query delegation protocol enables the server to request searches of the client's local history with user consent, merging server-side and client-side results by relevance. The system provides comprehensive AI recall while preserving user data sovereignty through structural architecture rather than policy alone. The emotional coherence engine periodically distills raw conversations into structured identity representations that are portable and exportable as a Sovereign Legacy Fabric.
