# Sovereign Sanctuary — Coach Discoverability & AI Search — MASTER DOCUMENT
**Version:** 4.0 (consolidated) · §22 workers #61–#64 IMPLEMENTED with passing proof (35/35); §21 conditionals resolved; Claim #3 corrected mechanism (sampling + distributed substance, not batching) · §21 outcome verification audit — five claims tested, one corrected as false-as-written, amendments built to PASS · §20 three-lever mastery: entity proof, information gain, un-gated value as OPTIMIZED OBJECTIVES with trio ownership and crystal compounding · §19 real-world risk resolutions: authority cold-start, programmatic-content penalty, funnel drop-off + crisis safety · §18 pipeline gap resolutions added with executable proof (`disco_pipeline.py` + `test_disco_pipeline.py`, 27/27 checks passing) · Supersedes and contains, in full:
`coach-discoverability-ai-search-plan.md` v2.3, `tier-0-completion.md`, and
`tier-1-4-deliverables.md`. Nothing was summarized, condensed, or dropped in
the merge — see the Combining Checklist (Part D) for the verification record.

**Document map**
- **PART A — The Plan** (§1–§17): strategy, technical layers, automation, self-adaptation, completion checklist. Original section numbering preserved; all internal §-references remain valid.
- **PART B — Tier 0 completion record**: pricing/trial confirmation, brand copy + Organization schema, counsel brief, D1/D3 decisions, credential registry interim path.
- **PART C — Tier 1–4 authored deliverables**: taxonomy, crawler files, probe set, autonomy config, product/brand copy, corrections C1–C6.
- **PART D — Combining checklist**: what merged, what changed, what was verified.
- **PART E — §18 pipeline gap resolutions**: eight execution gaps closed, each with a runnable reference implementation and passing test.
- **PART F — §19 real-world risk resolutions**: domain-authority cold-start, programmatic-content penalty, and funnel drop-off — plus the sub-gaps each exposes, including two corrections to prior sections.
- **PART I — §22 implementation of workers #61–#64**: runnable code closing every §21 conditional, with 35/35 passing checks and two corrections to the submitted specifications.
- **PART H — §21 outcome verification audit**: the five claimed results tested against the architecture; verdicts, corrections, and the amendments (workers #61–#64) required to make the final conclusion defensible.
- **PART G — §20 three-lever mastery**: verifiable entity proof, net-new information gain, and un-gated immediate value converted from static rules into measured objective functions the autonomous system optimizes, with LN7 / Little Nate / Queens ownership and crystal compounding.

**Reading order for execution:** Part D (what's done) → Part B and C (ready-to-use artifacts) → Part A §17 (tier gates) → Part A §1–16 (rationale when needed).

---

# PART A — THE PLAN

## Scope note (from original plan header)
**Separate initiative; consumes v1.5 build outputs; does NOT join the single push or its gate.**
**Version:** 2.3 · T1.2/T1.10/T2.8/T2.9/T3.1/T4.11 AUTHORED (see tier-1-4-deliverables.md); C4+C5 RESOLVED — canonical pricing claim corrected to '$5/day for you and your partner' (Sovereign Circle = HoH + partner; dependents are add-ons); add-on pricing deprioritized (settings pointer, excluded from schema); Tier 0–4 authored items closed · TIER 0 CLOSED (see tier-0-completion.md — decisions made, copy/consent drafted; remaining Tier 0 work is execution + smoke test only) · v2.0 §17 completion checklist — binding no-partial-build rule, tier gates, 100% completion definition · v1.9 §16 campaign↔discovery learning bridge: autonomous historical backfill, cross-coach marketing crystals, campaign assets as capture surfaces · v1.8 §15 supersedes all cadences: continuous signal-triggered adaptation, multi-horizon pattern memory (7/30/90/180/365), effortless-by-default for coach and Admin · v1.1 §9 gap closures · v1.2 §10 strategic upgrades · v1.3 §11 brand/org entity layer · v1.4 §12 product & category track · v1.6 §13 automation layer · v1.7 §14 self-adaptation layer (closes sensors into motors; autonomous learning under Queens boundary)

**Objective:** When someone asks ChatGPT, Perplexity, Gemini, Claude, or Google
"find me a trauma-informed family coach near Detroit" (or any specialty ×
location × modality query), Sovereign Sanctuary coaches and therapists appear
as named, cited, linkable answers.

**Core insight from current research:** AI engines don't rank pages — they
retrieve, extract, and cite entities. ChatGPT Search rides Bing's index
(~73% overlap); Gemini rides Google's; all of them parse JSON-LD structured
data to confirm who you are before naming you; and a majority of AI citations
(~65%) come from third-party sources (directories, review sites, publications)
rather than a business's own site. Strategy must therefore cover: own surface
(directory) + machine readability (schema/llms.txt/crawlers) + third-party
footprint (listings, mentions, reviews) + fresh cited content (the flywheel
the main build already produces).

---

## 1. The asset: a public Coach Directory (the centerpiece)

- Public, crawlable pages on the platform domain: `/coaches/{coach-slug}` —
  strictly OPT-IN per coach; zero client data anywhere on public surfaces.
- Each profile: name, photo, credential badge, specialties/modalities, service
  area (in-person/virtual), languages, plain-language FAQ ("What is family
  systems coaching?", "Do you work with teens?"), consented testimonials,
  authored articles, booking CTA into the existing intake flow (T1 chain).
- **The differentiator: the §15.1 credential registry becomes a public trust
  signal.** "Verified: LMFT, Michigan, verified by Sovereign Sanctuary" is an
  E-E-A-T authority marker competitors' generic directories can't match — AI
  engines weight credentialed, verifiable entities for health-adjacent queries
  (YMYL category).
- Programmatic hub pages: specialty × location ("Family coaches in Michigan",
  "Trauma-informed therapists — virtual, EU") and comparison/listicle formats —
  listicles and comparison structures earn disproportionate AI citations for
  commercial-intent queries.
- Freshness discipline: visible "last updated" dates; profiles re-render when
  coaches update; stale pages redirect.

## 2. Machine-readability layer (the technical unlock)

### 2.0 Entity Canonicalization (first-class mechanism; the "legibility" layer)
Field evidence and research agree: AI engines recommend the coaches whose
digital record AGREES WITH ITSELF — same name, city, and specialty wording
across every surface. Inconsistent vocabulary splits one practitioner into
several faint entities, none strong enough to be named.
- **Canonical Identity Record (per coach, in DB):** exact display name,
  credential string, city/service area, and 2–3 canonical specialty phrases.
  Rendered CHARACTER-IDENTICALLY across every platform-controlled surface:
  directory page, JSON-LD, llms.txt entries, article bylines, GBP guided
  setup, newsletter footers, LN Widget intro. Platform advantage: enforcement
  is programmatic for all coaches at once.
- **Client-language rule (binding for discovery surfaces):** canonical
  specialty phrases are chosen from QUERY language (what a prospective client
  types/asks — "postpartum anxiety therapist"), not clinical self-description
  ("perinatal mental wellness"). LN proposes phrases per coach from realistic
  query phrasing; clinical synonyms appear as secondary page text. This is a
  deliberate carve-out from §15.1 formal-vocabulary rules, which continue to
  govern consent/clinical documents.
- **sameAs entity stitching:** every profile's JSON-LD Person includes a
  sameAs array linking the coach's own website, Google Business Profile,
  LinkedIn, and external directory profiles — the explicit machine signal
  that scattered profiles are ONE entity.
- **GBP claim step:** onboarding includes claiming (not just creating) the
  coach's Google Business Profile — unclaimed auto-generated GBPs are silent
  or wrong and actively fragment the entity.
- **External drift audit (LN-run, periodic):** LN checks the coach's own
  website and external directory listings against the Canonical Identity
  Record and flags vocabulary drift to the coach with suggested fixes —
  the platform can't edit external surfaces, but it can watch them.

### 2.1 Vocabulary coverage model (expand reach WITHOUT fragmenting the entity)
Canonicalization and coverage are layered, not traded off:
- **Layer 1 — Canonical spine:** the 2–3 identity phrases (2.0), identical
  everywhere. Never expanded.
- **Layer 2 — Coverage placements (schema-correct):** synonym/related-term
  breadth lives in the properties designed for it — `knowsAbout` arrays
  (preferring entity URIs, e.g. Wikidata concepts, alongside strings for
  unambiguous machine grounding), `serviceType` + `hasOfferCatalog` of named
  services, FAQPage entries phrased in varied client registers ("Do you work
  with postpartum depression (PPD)?"), and specialty hub pages that each own
  a term CLUSTER. Coverage terms must describe real, visible competencies on
  the page — no invisible-markup stuffing.
- **Layer 3 — Therapeutic & Coaching Vocabulary Taxonomy (platform asset):**
  central table: canonical concept → clinical term, colloquial phrasings,
  acronyms, query-language variants, PER LANGUAGE (EU jurisdictions require
  native query vocabulary, not translated clinical terms). Curated in the org
  library (versioned, Admin-reviewed); LN generates each coach's coverage set
  from it. One taxonomy row serves every relevant coach permanently.
- **Credential gate (binding):** every taxonomy term carries a register.
  clinical-class profiles may render treatment language ("treatment of
  postpartum anxiety"); coaching-class profiles render the same CONCEPT in
  coaching register ("coaching and support for postpartum anxiety") — equal
  query coverage, correct scope of practice, enforced automatically from
  §15.1 relationship/credential class. Treatment-register terms on a
  coaching-class public surface are a build-blocking violation.

### 2.2 Location model (global roster; "near me" solved by data, not words)
Coaches and therapists are based everywhere; no city is privileged. "Near me" /
"close by" queries are resolved by the ENGINE from the searcher's location and
matched against declared service areas — so the work is per-coach serve-area
data, not location keywords:
- **Three service modes per coach:** in-person (LocalBusiness + geo + claimed
  GBP per physical location), virtual (`areaServed` regions with the service
  marked remote/telehealth), hybrid (both on one entity).
- **BINDING — licensure-derived areaServed:** clinical-class profiles derive
  `areaServed` from §15.1 credential-registry jurisdictions (incl. registered
  compacts); the platform never advertises clinical service beyond lawful
  practice area. Coaching-class profiles may declare multi-country/global
  virtual reach.
- **Supply-gated programmatic pages:** location × specialty hubs generate only
  where actual coach supply exists; zero-supply pages are never created (thin
  programmatic pages are punished). Country/language hubs come from the
  taxonomy's per-language layer.
- Virtual-intent coverage ("online", "virtual", "telehealth") is a taxonomy
  register applied across all virtual-mode profiles.

### 2.3 Freshness rotation engine (adapts without destabilizing the entity)
Rotation NEVER touches the canonical spine (Layer 1); it cycles coverage
(Layer 2) and content:
- **Trend ingestion:** T4 Industry Reporter + LN monitoring feed a
  trending-topics queue — seasonal cycles (New Year, back-to-school, holiday
  grief, awareness months), emerging client vocabulary, news-driven demand.
- **Curated rotation (Admin/MC-approved):** approved terms flow to (a) new
  taxonomy rows → refreshed knowsAbout/FAQ coverage on matching profiles,
  (b) content_topics → LN article pipeline (dated, citable, fresh content),
  (c) the monthly visibility-panel prompt set, so measurement tracks current
  client questions.
- **Ethics gate (binding):** tragedy-driven demand spikes receive
  supportive-resource treatment or silence — never opportunistic SEO. All
  rotated terms respect taxonomy credential registers.
- **Hygiene:** visible last-updated dates on hubs/profiles; re-render on
  rotation; superseded pages redirect. Cadence: coverage refresh quarterly,
  content rotation continuous, canonical spine permanent.


- **JSON-LD on every public page:** Person + ProfessionalService (+
  LocalBusiness where a physical location exists), FAQPage schema on profile
  FAQs, Review/AggregateRating only where genuine consented reviews exist.
  Schema states exactly what the visible page states — no markup inflation.
- **Crawler policy (deliberate, documented):** public directory ALLOWS
  OAI-SearchBot, ChatGPT-User, GPTBot, PerplexityBot, ClaudeBot,
  Google-Extended, Applebot-Extended. The authenticated app, Coach Command,
  and client surfaces remain fully BLOCKED. Check Cloudflare defaults — they
  commonly block AI crawlers silently.
- **llms.txt at domain root:** Markdown map of the directory, specialty hubs,
  and platform description for AI agents; maintained as part of directory
  deploys.
- **Index coverage:** submit sitemaps to BOTH Google Search Console and Bing
  Webmaster Tools (Bing = ChatGPT's retrieval pool; absence from Bing =
  absence from ChatGPT regardless of Google rank).
- Clean semantic HTML, fast loads, mobile-first; answer-shaped copy (a model
  should be able to lift a self-contained, accurate sentence about any coach).

## 3. Third-party footprint (where most AI citations actually come from)

- Per-coach NAP consistency (name, address/service-area, phone, site)across:
  Google Business Profile, Bing Places, Apple Business Connect, Foursquare
  (a primary location dataset for AI local lookup), plus profession-specific
  directories (e.g., Psychology Today-class listings for licensed clinicians).
- Review generation loop: post-engagement, coaches invite consented public
  reviews on Google Business Profile (ethics rules per jurisdiction for
  clinical relationships — counsel check; coaching-class relationships are
  simpler). Never synthetic or incentivized reviews.
- Earned mentions: pitch coaches into "best of" lists, local publications, and
  podcasts — the Industry Reporter (T4) doubles as a source of outlets and
  trends worth pitching into.

## 4. Google Workspace leverage (honest scope)

Workspace is mostly a PRIVATE surface — its discoverability role is the
production line, not the stage:
- **Google Business Profile per coach** (adjacent to Workspace): the single
  highest-impact local/AI-local signal; guided setup joins coach onboarding
  alongside SendGrid domain auth.
- **Docs → publish pipeline:** LN drafts public articles from flagged topics
  (§12.2 content_topics) in Docs for coach review/comment, then publishes to
  the coach's public article page — the newsletter/campaign engine gains a
  public, crawlable, citable output it currently lacks (LinkedIn is
  low-crawlability; the directory article page is the indexable home).
- **Search Console + GA4 monitoring** under the org's Google account; AI
  referrer segments (chatgpt.com, perplexity.ai, copilot) tracked as a
  first-class acquisition channel; referral hits write to campaign_engagements
  (channel addition: 'ai_search').
- Per-coach authenticated domains (already built for SendGrid) reinforce
  entity consistency.

## 5. What this plan does NOT do (binding)

- No client data, client stories, or session-derived content on any public
  surface, ever. Testimonials are consented, coach-relationship-appropriate,
  and jurisdiction-checked for clinical-class relationships.
- No schema spam, fake reviews, keyword stuffing, or AI-generated bulk pages
  detached from real coaches — LLMs punish inconsistency and thin content,
  and the platform's core asset is verified trust.
- No coupling to the v1.5 push: this plan has its own timeline, own review,
  and consumes (never modifies) the main build's outputs — credential
  registry, content engine, intake webhook, LN Widget.

## 6. Measurement

- Monthly AI visibility panel: a fixed set of realistic prompts ("family coach
  in {city}", "certified {modality} coach online") run across ChatGPT,
  Perplexity, Gemini, Claude; log who gets named/cited; track share-of-voice
  over time.
- GA4: AI-referrer sessions, branded-search volume trend (leading indicator of
  AI exposure), directory → intake conversion.
- Search Console + Bing Webmaster index coverage of directory pages.

## 7. Phasing (independent of the main push)

- **P1 — Foundation:** Canonical Identity Records + directory pages + schema
  (incl. sameAs) + robots/llms.txt + Bing/GSC submission + opt-in flow with
  consent language. (Prereq: none — can start now; credential badges activate
  when §15.1 ships.)
- **P2 — Footprint:** Business Profile CLAIM + setup onboarding step, listings
  sync from the Canonical Record, review-invite loop (counsel check for
  clinical-class), LN external drift audit v1.
- **P3 — Content engine coupling:** Docs→publish article pipeline from
  content_topics; hub/listicle pages; freshness automation.
- **P4 — Widget + measurement:** LN Widget embedded on directory profiles and
  coach sites; monthly visibility panel automated (LN can run and log it);
  'ai_search' engagement channel live.

## 8. Open items

- D1: Directory domain strategy — platform subdirectory (recommended for
  authority consolidation) vs. per-coach subdomains.
- D2: Counsel — review-solicitation and testimonial rules for clinical-class
  relationships per jurisdiction (pairs with O6 counsel engagement).
- D3: Opt-in consent language for public profiles (coach-facing; versioned per
  §15.8 pattern).
- D4: Whether the Queens' anomaly/rate-limit posture needs a carve-out for
  allowed AI crawlers on the public directory (they crawl aggressively).

---

## 9. Gap closures (v1.1)

### 9.1 Rendering architecture (P1 foundational — binding)
Directory, hub, and article pages are statically generated or server-side
rendered; JSON-LD inline in initial HTML. AI crawlers largely do not execute
JavaScript — a client-rendered SPA directory is invisible to them. Verify with
raw-HTML fetch tests (curl-level) as part of P1 acceptance.

### 9.2 GBP ownership model (binding)
The COACH owns their Google Business Profile under their own Google account;
the platform is added as MANAGER for canonical-record enforcement. The
platform never claims coach GBPs under org accounts. Onboarding walks the
coach through claim-then-delegate.

### 9.3 Coach offboarding / profile lifecycle
Profile statuses: active → paused ("not currently accepting clients") →
departed. On departure: profile page 301-redirects to the matching specialty
hub; sitemap + llms.txt updated; de-indexing requested where appropriate;
sameAs links removed so the coach's independent entity persists cleanly;
platform manager access on their GBP relinquished. Accumulated page authority
routes to hubs, never 404s.

### 9.4 Credential-state propagation (binding)
Public badge, clinical-register vocabulary, and clinical areaServed are LIVE-
DRIVEN by the §15.1 credential registry: credential lapse → badge removed,
treatment-register terms fall back to coaching register or profile pauses,
page re-renders same day, caches purged. A stale "Verified" badge is treated
as an incident, not a cosmetic bug.

### 9.5 Public-surface privacy compliance
EU-compliant consent banner + Google Consent Mode before any analytics on
public pages; booking/intake CTA carries its own privacy notice at the form;
prospect data from public pages enters the same GDPR machinery as all
platform data.

### 9.6 Misrepresentation monitoring
The visibility panel logs WHAT engines claim about named coaches (specialty,
location, credentials), not only who is named. Inaccuracies trigger: source-
page reinforcement (the correct fact stated more extractably), engine feedback
where channels exist, and coach notification. Health-adjacent misattribution
is a same-week fix class.

### 9.7 Scrape protection + entity-home policy
Public profiles expose booking CTAs and forms only — never raw email or phone
(also routes all inquiries through intake → LN + campaign_engagements
attribution). Crawlability for allowed AI/search bots; rate limits for the
rest (pairs with D4). For coaches with independent websites: directory page
and coach site are complementary canonical surfaces stitched by sameAs; never
duplicate page text across them. LN-drafted public articles carry real author
schema (the coach), disclosed human review, and dated bylines (E-E-A-T).

---

## 10. Strategic completeness upgrades (v1.2 — from best-implementation review)

### 10.1 Barbell query strategy (re-weights §1 vs §3 honestly)
A new domain will not out-cite incumbent directories on head terms for years,
regardless of schema quality. Sequence by query class:
- **Years 0–2 head terms** ("therapist near me", "anxiety therapist {city}"):
  offense runs through the surfaces engines already trust — GBP, major
  directories, review platforms — with Canonical Identity enforcement applied
  to THOSE listings. §3 is the early spearhead, not the supporting act.
- **Long tail** (specialty × modality × situation × language × virtual): our
  directory wins where incumbents are thin and legibility decides — realistic
  horizon 6–12 months of consistent P1 (SSR, supply-gated hubs, indexation),
  not day one; live-probe evidence shows even mid-tail local queries are
  currently 100% directory/platform-dominated, and the platform directories
  that rank (LifeStance/Grow/Zencare pattern — structurally identical to our
  hub design) took years plus scale. Hub generation prioritizes long-tail
  clusters first.
- **Supply conditional (foundational):** every capture path presumes a
  Sanctuary coach serves the resolved area/specialty — capture probability is
  ~zero outside coverage regardless of execution. §10.4's demand→recruiting
  flywheel is therefore the denominator of the plan, not an enhancement.
- **Own-domain head terms** are the year-3 objective, funded by compounding
  long-tail authority. Report visibility by query class so progress is honest.

### 10.2 Agent-queryable layer (B2A — category-defining, absent from v1.0)
Beyond being READ by crawlers, be QUERYABLE by agents:
- Public read-only find-a-coach API and/or MCP server: canonical records,
  taxonomy specialties, credential-verification status, areaServed,
  accepting-clients signal, booking link. Opt-in per coach; serves only
  §5-compliant public data. **List the MCP server in agent connector
  registries/directories (Anthropic MCP directory-class surfaces) so
  assistants can suggest and query the Sanctuary finder directly in
  conversation — interaction capture, not just citation capture.**
- **Credential verification endpoint:** machine-checkable attestation
  ("credential X verified as of DATE") derived from §15.1 — public trust
  infrastructure other surfaces and engines can reference; positions
  Sanctuary as the SOURCE rather than one directory among many.
- Hedge value: owned queryable surface reduces dependence on third-party
  platform ToS (GBP, listings, engine feedback channels).

### 10.3 Review-velocity engine (coaching-class) + advertising-rule matrix
- Coaching-class: automated, ethical post-engagement review invites (GBP-
  first) riding existing email rails, LN-timed to satisfaction moments —
  treated as a PRIMARY local-AI lever, not a P2 sub-bullet.
- Clinical-class: replace "counsel check on reviews" with a per-jurisdiction
  **professional advertising-rule matrix** (several US boards restrict
  therapist testimonials outright; EU states carry their own rules) gating
  ALL public-surface elements — reviews, testimonials, superlatives, badges —
  per credential jurisdiction. Pairs with the O6 counsel engagement.

### 10.4 Demand-sensing → recruiting flywheel (closes the measurement loop)
Visibility-panel and query data identify demand clusters with zero Sanctuary
supply (specialty × geo × language prompts where no coach can be named).
These feed a recruiting-targets queue: recruit → supply-gated hub opens →
captured demand justifies the recruit. Discoverability doubles as the
platform's supply-growth instrument — a loop generic directories cannot run.

### 10.5 Self-ranking disclosure + parasite-SEO defense
Hub/listicle pages disclose scope visibly ("Sovereign Sanctuary verified
coaches"); rankings among own roster are framed as a verified-network
directory, not neutral "best of the web" claims. Defense against engine
penalties for low-substance directory patterns = substantive profiles worth
citing + honest disclosure + coach-owned sites as co-primary entity homes.

---

## 11. Brand & Organization entity layer (v1.3 — routes discovery to the three destinations)

### 11.1 www.sovereignsanctuary.net = Organization entity home
- **D1 RESOLVED: directory ships as a subdirectory** (sovereignsanctuary.net/
  coaches/…) so all profile/hub/article authority accrues to the brand domain.
  Citation loop: coach cited → domain seen → branded search → homepage capture
  (branded-search volume tracked as the leading indicator).
- Organization JSON-LD on the homepage (Squarespace code injection): what the
  org IS in canonical terms, sameAs → LinkedIn company page + other org
  profiles, founder → Person entity; llms.txt and the §10.2 verification
  endpoint live on this domain.
- **Homepage legibility (binding):** the homepage and meta description pass
  the same Canonical Identity test enforced on coaches — a machine-extractable
  statement of what the platform is (verified certified/licensed coaches +
  AI companion, who it serves, how, where). Register discipline: §15.1
  vocabulary rules apply to platform-owned pages; therapeutic/treatment
  register only where accurate and licensure-backed; extraordinary-claim copy
  ("sentient", "quantum", "healing finally made possible") is replaced with
  verifiable trust claims on discovery-facing surfaces — YMYL engines cite
  measured sources and discount hype.

### 11.2 app.sovereignsanctuary.net = conversion endpoint (never a discovery surface)
Crawler-blocked (per §2/§9 app-blocking rule). Every CTA terminates here:
profile booking, T1 intake, MCP finder booking link, homepage Sign Up.
Measured via GA4 source attribution + campaign_engagements; never indexed.

### 11.3 Founder entity (LinkedIn stitching)
- Organization schema `founder` → Person (Nathaniel Nevedal) with sameAs →
  his LinkedIn profile; founder-bylined articles on the www domain (author
  schema) link back; the voice-campaign LinkedIn engine posts from/via the
  founder account referencing directory articles (crawlable↔social loop).
- Founder profile headline/description passes the canonicalization test —
  identical vocabulary to the Organization schema. E-E-A-T: an identifiable,
  credential-transparent founder strengthens every health-adjacent citation
  decision on the domain.

---

## 12. Product & category discoverability track (v1.4 — THE MISSING HALF)

The coach track (§1–§11) competes for "therapist near me" — queries where
established directories are strong and Sanctuary is one option among many.
The platform's actual differentiator (AI companion + verified human
professionals + family/affordability model) has NO incumbent and NO directory.
This track claims that category.

### 12.1 Category & product queries to own
- Product-intent: "AI therapy app that remembers my history", "AI companion
  with real therapists", "mental health support between sessions".
- Affordability/family: "affordable mental health support for a family",
  "therapy alternative when I can't afford weekly sessions", "family mental
  health plan".
- Comparison: vs. traditional therapy, vs. AI-only chat apps, vs. subscription
  therapy platforms — honest, sourced comparison pages (comparison/listicle
  formats earn disproportionate AI citation).
- Explainer: "what is Little Nate", how pairing works, what the AI does and
  does not do, clinical safety model.

### 12.2 Schema & surfaces
- SoftwareApplication + Service + Offer (pricing/tiers) + FAQPage on product
  pages; Organization (§11.1) as parent entity.
- Pricing and family-plan pages built to ANSWER affordability queries with
  concrete, extractable figures — not gated behind a signup.
- Clinical-safety page (already exists) upgraded into the trust/citation
  anchor: verification process, human-in-the-loop, crisis escalation, data
  handling. This is the page that decides whether a cautious engine will
  recommend the platform at all.

### 12.3 Positioning discipline (binding)
Claim precision governs citability and regulatory exposure: describe the
product as an AI companion paired with verified certified/licensed human
professionals — NOT "AI therapy", not diagnostic, not treatment. Extraordinary
framing ("sentient", "quantum") is excluded from discovery surfaces (§11.1).
§15.1 register rules apply to all product copy.

### 12.4 Upstream client-journey content (pre-provider search)
Clients search symptoms and situations long before they search "therapist":
"why do I feel numb after having a baby", "how to know if I need therapy",
"postpartum rage is that normal". LN-authored, coach-reviewed, coach-bylined
articles target this layer, route to both the directory (§1) and the product
track (§12.1), and feed the §2.3 rotation engine. This is the largest
volume-and-empathy surface in the plan and the natural home of the content
engine's output.

### 12.5 Coach-recruitment discoverability (supply side)
§10.4's flywheel needs recruits to arrive: target professional-intent queries
("platforms for therapists to see clients online", "how coaches get clients",
"telehealth platform for licensed therapists") with a Join-as-a-Coach hub —
credential requirements, economics, supervision model, Coach Command feature
set. Supply acquisition is a discoverability problem too.

### 12.6 Brand-defense queries (highest intent, currently unowned)
"Is Sovereign Sanctuary legitimate", "Sovereign Sanctuary reviews", "Sovereign
Sanctuary pricing", "who is Nathaniel Nevedal": for a new AI-adjacent mental
health brand these are the last queries before signup, and unanswered, engines
improvise. Own them with substantive About/Team/Safety/Pricing pages, founder
entity (§11.3), verified third-party presence, and genuine reviews. Monitor
brand-query answers in the §6 visibility panel with the same accuracy
discipline as §9.6.

---

## 13. Automation layer specification (v1.6 — workers, triggers, flags, ACs)

Discipline at scale is a systems property, not a habit. §1–§12 describe
behaviors; this section assigns each an owning worker. Workers run under the
Queens with the same GREEN/YELLOW/RED governance as platform workers. Naming
convention: `disco_*`. All workers are flag-gated and idempotent.

### 13.1 Data spine
```sql
canonical_identity (coach_id PK, display_name, credential_string, service_mode,
  areaServed JSONB, canonical_phrases TEXT[], languages TEXT[], profile_status
  TEXT CHECK (profile_status IN ('draft','active','paused','departed')),
  same_as JSONB, version INT, updated_at)
vocabulary_taxonomy (id, concept, language, register CHECK (register IN
  ('clinical','coaching')), terms TEXT[], entity_uri, status, version)
discovery_pages (id, page_type, slug, entity_ref, last_rendered_at,
  last_indexed_check, status)
visibility_probes (id, prompt, engine, run_at, named_entities JSONB,
  claims JSONB, accuracy_flags JSONB)
recruiting_targets (id, specialty, geo, language, demand_signal, status)
trending_topics (id, term, source, detected_at, approval_status, ethics_flag)
```
Canonical identity is the single source; every rendered surface derives from
it (drift becomes structurally impossible on platform-owned surfaces).

### 13.2 Worker registry (A-items 1–16, fully automated)
| # | Worker | Trigger | Flag |
|---|---|---|---|
| 1 | `disco_canonical_renderer` — record → page + JSON-LD + sameAs + llms.txt + bylines + footers | canonical_identity change | `DISCO_RENDER` |
| 2 | `disco_onboarding_pipeline` — LN generates canonical record, register-correct phrases, profile copy, FAQs, per-directory listing text blocks, GBP claim packet | coach activation | `DISCO_ONBOARD` |
| 3 | `disco_hub_generator` — supply-gated hub creation + sitemap + llms.txt + GSC/Bing submission | supply change | `DISCO_HUBS` |
| 4 | `disco_credential_propagator` — lapse → badge off, register downgrade, re-render, cache purge (same-day) | credential registry event | `DISCO_CREDSTATE` |
| 5 | `disco_lifecycle` — pause/depart → 301s, sameAs unstitch, de-index, GBP manager release | profile_status change | `DISCO_LIFECYCLE` |
| 6 | `disco_drift_auditor` — weekly crawl of coach site + external listings, diff vs canonical, flag to coach | weekly cron | `DISCO_DRIFT` |
| 7 | `disco_rotation_executor` — quarterly coverage refresh, dated re-render, superseded redirects | quarterly cron | `DISCO_ROTATION` |
| 8 | `disco_trend_ingestor` — T4 + LN monitoring → trending_topics queue | daily cron | `DISCO_TRENDS` |
| 9 | `disco_visibility_panel` — monthly prompt set across engines; logs named entities AND claims | monthly cron | `DISCO_PANEL` |
| 10 | `disco_referrer_attribution` — AI referrers → campaign_engagements(channel='ai_search') | request-time | `DISCO_ATTRIB` |
| 11 | `disco_demand_sensor` — zero-supply clusters → recruiting_targets | panel completion | `DISCO_DEMAND` |
| 12 | `disco_review_dispatcher` — coaching-class only, LN-timed post-engagement invites | engagement event | `DISCO_REVIEWS` |
| 13 | `disco_agent_api` — find-a-coach API/MCP + credential-verification endpoint, canonical-synced | canonical change | `DISCO_AGENT_API` |
| 14 | `disco_build_deploy` — SSR/static build, raw-HTML crawlability test gate | page change | `DISCO_BUILD` |
| 15 | `disco_register_linter` — blocks treatment-register terms on coaching-class surfaces | pre-publish (blocking) | `DISCO_LINT` |
| 16 | `disco_area_deriver` — areaServed from credential jurisdictions (+compacts) | credential change | `DISCO_AREA` |

### 13.3 Human-in-the-loop queue (B-items 17–21)
One approval surface in Coach Command (Admin/MC): article publishing (17),
trend rotation approvals incl. ethics gate (18), misrepresentation corrections
(19), taxonomy expansion curation (20), testimonial/review approval with
jurisdiction check (21). LN drafts everything; humans approve in minutes.
Queue SLA: weekly sitting; items aging >14 days escalate.

### 13.4 Human-required, non-automatable (C-items 22–28 — do not build around)
GBP claiming (owner-only) (22); external directory account creation (ToS)
(23); counsel advertising matrix / O6 / D2 (24); recruitment conversations +
credential verification (25); brand positioning copy decisions (26); engine
correction submissions requiring a human (27); pricing/trial-model decisions
(28). Automation's job here is to prepare every input so the human step is
minutes of clicking, never hours of writing.

### 13.5 New workers closing D-items 29–33
| # | Worker | Purpose | Flag |
|---|---|---|---|
| 29 | `disco_decay_monitor` | detect staling pages (age, traffic decline, lost citations) → refresh queue | `DISCO_DECAY` |
| 30 | `disco_competitor_watch` | log who else is named for target prompts; share-of-voice trend | `DISCO_COMPWATCH` |
| 31 | `disco_funnel_instrumentation` | citation → click → signup → subscriber attribution; replaces estimates with measured rates | `DISCO_FUNNEL` |
| 32 | `disco_schema_validator` | JSON-LD validation in CI; malformed markup blocks deploy | `DISCO_SCHEMA` |
| 33 | `disco_index_watch` | Bing/Google index-coverage alerting on page drop-out | `DISCO_INDEXWATCH` |

### 13.6 Automation acceptance criteria
- DAC1: A canonical_identity edit propagates to every platform-owned surface
  (page, JSON-LD, sameAs, llms.txt, hub, byline, footer) within one build
  cycle; no surface can diverge (audit query returns zero drift).
- DAC2: Coach activation to fully-legible (profile live, schema valid, listing
  packets + GBP claim packet delivered) completes same-day, unattended.
- DAC3: A simulated credential lapse removes badge and clinical-register terms
  and re-renders within 24h; a treatment-register term on a coaching-class
  surface is blocked at publish by the linter (13.2 #15).
- DAC4: A departure produces 301s to hubs, sameAs unstitching, de-index
  requests, and zero 404s from prior profile URLs.
- DAC5: Monthly panel executes unattended and records named entities AND
  claims; misattribution flags open correction items; competitor share-of-voice
  charts.
- DAC6: Raw-HTML fetch (no JS execution) of any public page contains full
  content + JSON-LD; CI blocks deploy on schema validation failure.
- DAC7: Zero-supply demand clusters appear in recruiting_targets within one
  panel cycle of detection.
- DAC8: Every flag in 13.2/13.5 kills its worker independently with graceful
  degradation and no orphaned queue state.

### 13.8 Automation upgrades — reclassified from "human-required" (v1.6.1)
Several C-items were classified by habit, not by real constraint. Corrected:

| # | Worker | What automates / what stays human | Flag |
|---|---|---|---|
| 34 | `disco_listing_orchestrator` (upgrades C#23) | Detects existing listings per coach per platform; generates copy pre-fitted to each directory's field structure/limits; tracks per-platform completion; nags incompletes. HUMAN: paste + submit only (ToS). ~80% automated | `DISCO_LISTINGS` |
| 35 | `disco_gbp_manager` (upgrades C#22) | Detects unclaimed/auto-generated GBPs per coach; generates claim packet; tracks verification. Once coach grants manager access, pushes canonical data, posts, and updates via GBP API. HUMAN: the one-time claim only | `DISCO_GBP` |
| 36 | `disco_correction_dispatcher` (upgrades C#27) | Detects misattribution (§9.6), assembles evidence + correct facts + canonical URLs + submission-ready text; submits via API where available. HUMAN: form submission where no API exists | `DISCO_CORRECT` |
| 37 | `disco_credential_prechecker` (upgrades C#25, partial) | Automated lookup against state board / registry databases where available; expiry monitoring; renewal reminders; re-verification scheduling. HUMAN: final approval + edge cases + all recruiting conversations | `DISCO_CREDCHECK` |
| 38 | `disco_listing_tracker` (NEW gap) | Closes the loop the drift auditor leaves open: verifies pasted listings landed correctly and remain correct; coverage state per coach per platform | `DISCO_LISTTRACK` |
| 39 | `disco_queue_manager` (NEW gap) | Batches and impact-prioritizes the §13.3 approval queue; auto-approves low-risk classes under standing Admin rules (e.g. in-register taxonomy synonyms); escalates aging items. Reserves human attention for judgment calls only | `DISCO_QUEUE` |
| 40 | `disco_content_scheduler` (NEW gap) | Plans the upstream-symptom article calendar against rotation trends, seasonal cycles, and demand-cluster gaps; feeds LN authoring pipeline | `DISCO_SCHEDULE` |

**Remains genuinely human (final list):** counsel's advertising/legal matrix
(C#24), brand positioning decisions (C#26), pricing/trial model (C#28),
credential final approval + recruiting conversations (C#25 residual), GBP
claim click (C#22 residual), external directory paste/submit (C#23 residual),
non-API engine corrections (C#27 residual).

- DAC9: A coach with no external listings receives platform-fitted copy for
  each target directory and a GBP claim packet within one day of activation;
  completion state is tracked per platform and incompletes are nagged.
- DAC10: After manager access is granted, canonical changes propagate to the
  coach's GBP automatically; a detected misattribution produces a complete,
  submission-ready correction packet without human drafting.
- DAC11: The approval queue auto-clears low-risk classes per standing rules
  and presents only judgment items; no item ages past 14 days unescalated.

### 13.9 Autonomous audience-acquisition loop (v1.6.2 — trio ownership)

**Staller conversions (removes human-dependency, not just reminders):**
| Staller | Conversion |
|---|---|
| #7 directory paste/submit | One-time onboarding AUTHORIZATION making the platform the coach's listing agent (signed consent); platform-level directory feeds/partnerships where available; LN walks residual manual clicks conversationally in-app during onboarding with copy pre-loaded; activation gate + `disco_listing_tracker` completion state |
| #6 GBP claim | Manager access requested at onboarding as part of the same authorization → `disco_gbp_manager` (#35) then fully automates data, posts, updates via API |
| #3 pricing decision | Ship a defensible starting model NOW; `disco_funnel_instrumentation` (#31) measures conversion by tier and query class; LN proposes evidence-backed changes; Admin approves in minutes. Never a blocking strategic project |

**Ownership of the acquisition loop:**
- **Little Nate — demand, content, conversion.** Senses zero-supply demand
  clusters (#11) → schedules (#40) and authors upstream-symptom articles →
  publishes to directory → sequences campaigns via the voice/newsletter engine
  → MEETS ARRIVING TRAFFIC via the public LN Widget on directory/product
  pages, answers visitor questions, and walks them into intake. Discovery →
  engagement → conversion is one continuous LN surface, no handoff.
- **LN7 — technical loop + self-healing.** Renders, builds, deploys, agent API,
  index-coverage and schema monitoring — and AUTO-REMEDIATES its own detections
  (failed renders re-run, schema errors block+fix, index drop-outs trigger
  resubmission) rather than queueing them for humans.
- **Queens — governance of an autonomous system.** Register linter (blocking),
  trend ethics gate, jurisdiction/advertising compliance, crawl+traffic anomaly
  detection, RED on misattribution. AUTHORITY BOUNDARY (binding): no
  auto-publish outside approved registers; no action taken on a coach's behalf
  beyond their granted authorization scope; all agent-acted listing changes
  logged and coach-visible.

- DAC12: A coach completing onboarding authorization reaches full external
  listing + GBP coverage with zero post-onboarding human tasks outside
  irreducible third-party clicks, which LN completes conversationally in-session.
- DAC13: The loop runs a full cycle unattended — demand cluster detected →
  article scheduled, authored, published → campaign sequenced → visitor met by
  LN Widget → intake created → engagement attributed — with human involvement
  limited to §13.3 judgment approvals.

### 13.7 Forecast impact (why this section exists)
Automation compresses: brand/category capture 12mo → 3–5mo; coach legibility
months → same-day per coach AND undegraded at roster scale (the manual failure
point is ~20 coaches); long-tail own-domain 6–12mo → 4–8mo. It does NOT
compress index/authority accrual below ~4 months, and cannot buy domain
authority for local head terms (year-3 outcome unchanged). Automation's real
prize: removes execution consistency as a constraint, leaving supply density
(§10.4) as the only remaining lever on local capture.

---

## 14. Self-adaptation layer (v1.7 — the plan becomes autonomous)

§13 made the plan AUTOMATIC: it executes a fixed strategy at scale. §14 makes
it AUTONOMOUS: it learns from its own results, varies what it tries, selects
what works, and reallocates its own effort — inside a governed boundary.
Diagnosis this section fixes: every measurement worker in §13 was a SENSOR WITH
NO MOTOR. Data landed in tables and waited for a human. Here, each sensor is
wired to an actuator.

### 14.1 The three requirements of a self-adapting system
1. **Feedback** — measurement closes into action without a human relay.
2. **Variation** — the system tries things it was not told to try.
3. **Selection** — winners are promoted, losers retired, automatically.
Missing any one, the system can only ever execute today's guesses forever.

### 14.2 Learning data spine
```sql
citation_outcomes (id, probe_id, engine, page_ref, phrasing_pattern JSONB,
  page_structure JSONB, was_cited BOOL, position, observed_at)
content_performance (id, content_ref, impressions, clicks, intakes,
  subscribers, decay_score, updated_at)
experiments (id, hypothesis, variant_a JSONB, variant_b JSONB, surface_scope,
  metric, started_at, sample_n, result JSONB, status CHECK (status IN
  ('running','won','lost','inconclusive','promoted','rolled_back')))
strategy_allocation (id, track, period, effort_share, measured_return,
  proposed_share, decided_by CHECK (decided_by IN ('system','admin')))
term_performance (id, taxonomy_term_id, citations, converting_queries,
  last_surfaced_at, lifecycle CHECK (lifecycle IN ('candidate','active',
  'declining','retired')))
```

### 14.3 Adaptive workers (motors on the sensors)
| # | Worker | Loop it closes | Flag |
|---|---|---|---|
| 41 | `disco_performance_rotator` | REPLACES calendar rotation (#7): refresh on decay_score and citation loss, not on the quarter. Winning pages left alone; decaying pages regenerated first | `DISCO_ADAPT_ROTATE` |
| 42 | `disco_citation_learner` | Panel logs WHAT was cited — phrasing patterns, page structures, schema shapes — and derives templates for the next page generation. The system learns what makes it citable | `DISCO_ADAPT_LEARN` |
| 43 | `disco_content_loop` | Articles producing intakes/subscribers shape the next articles' topics, depth, and structure; non-performers decay out of rotation | `DISCO_ADAPT_CONTENT` |
| 44 | `disco_taxonomy_evolver` | Terms appearing in winning citations and converting queries auto-propose as candidates; never-surfacing terms retire. Register/ethics gates still apply (Queens) | `DISCO_ADAPT_TAXONOMY` |
| 45 | `disco_experimenter` | VARIATION MECHANISM: controlled A/B on page structure, meta descriptions, FAQ phrasing, CTA placement, hub layouts; auto-promotes winners, rolls back losers, logs all results | `DISCO_ADAPT_EXPERIMENT` |
| 46 | `disco_allocator` | Shifts effort across §10.1 barbell tracks (third-party / long-tail / category / upstream / recruitment) on MEASURED return, replacing the weights estimated at authoring time | `DISCO_ADAPT_ALLOCATE` |
| 47 | `disco_crystal_bridge` | Discoverability learnings crystallize into LN memory (domain='marketing', anonymized per §12.3 of the build spec) so intelligence compounds platform-wide instead of dying in dashboards | `DISCO_ADAPT_CRYSTAL` |
| 48 | `disco_supply_optimizer` | Recruiting targets (#11) re-ranked continuously by measured conversion value per cluster, not raw demand volume | `DISCO_ADAPT_SUPPLY` |

### 14.4 Queens autonomy boundary (binding — what the system may change alone)
**MAY self-change without human approval:** page structure and layout, meta
descriptions, FAQ phrasing within an approved register, internal linking,
publishing cadence, rotation timing, term coverage among APPROVED taxonomy
terms, effort allocation across tracks, experiment variants within these
bounds, recruiting-target ranking.

**MUST escalate to human (never self-changed):** register boundaries
(clinical vs coaching language), positioning and product claims (§12.3),
pricing, anything touching credentials, licensure, or clinical vocabulary,
new taxonomy CONCEPTS (as opposed to phrasings), tragedy/ethics-flagged
trends, and any change that would alter what the platform asserts about a
coach's qualifications or lawful service area.

**Safety rails:** every autonomous change is versioned and revertible;
`disco_experimenter` runs bounded sample sizes with automatic rollback on
metric degradation; a global `ADAPT_FREEZE` flag halts all self-modification
instantly; Queens RED on any attempted change crossing the escalation list;
weekly autonomy digest to Admin summarizing what the system changed and why.

### 14.5 Autonomy acceptance criteria
- DAC14: A page losing citations triggers regeneration from learned templates
  without human action; a winning page is left untouched (calendar rotation no
  longer fires blindly).
- DAC15: `disco_experimenter` runs an experiment end-to-end — variant created,
  sample gathered, winner promoted, loser rolled back — with zero human input,
  and every step is logged and revertible.
- DAC16: An article that produced subscribers measurably shifts the next
  scheduling cycle's topic/structure choices (traceable in content_performance
  → scheduler inputs).
- DAC17: Effort allocation across tracks changes in response to measured
  return, and the change is explainable in the weekly autonomy digest.
- DAC18: An attempted autonomous change to register, pricing, positioning, or
  credential-related content is BLOCKED and escalated, with Queens RED logged.
- DAC19: `ADAPT_FREEZE` halts all self-modification within one cycle, leaving
  the automatic (§13) layer fully functional.

### 14.6 What autonomy changes about the forecast
Self-adaptation does not beat index time or domain authority (§13.7 stands).
What it changes: the strategy stops being frozen at authoring time. Where §13
executes the barbell weights and taxonomy guessed in 2026 indefinitely, §14
reallocates toward whatever is actually converting, learns the citation
patterns engines currently reward (which will shift as engines change), and
compounds those learnings into LN. The practical effect is resilience: the
plan survives changes in engine behavior, competitor entry, and demand shifts
without a human rewriting it — which, given how fast this field moves, is the
difference between a plan that ages well and one that decays into a 2026
artifact.

---

## 15. v1.8 — Continuous autonomy, multi-horizon memory, effortless by design

**This section SUPERSEDES every cadence in §13 and §14.** All calendar-based
triggers (quarterly rotation, monthly panel, weekly audits, weekly approval
sittings) are removed. They were human scheduling artifacts imposed on a
machine that processes signal continuously — and they guaranteed the system
ran a stale strategy between firings. Replaced by continuous, signal-triggered
operation with daily consolidation.

### 15.1 Continuous operation (replaces all cadences)
| Was (v1.6/1.7) | Now |
|---|---|
| Quarterly coverage rotation (#7/#41) | Continuous: regenerate on decay/citation-loss signal, per page, as detected |
| Monthly visibility panel (#9) | Continuous probing with ADAPTIVE SAMPLING: baseline sweep daily; sampling rate rises automatically on volatility, competitor movement, or ranking loss |
| Weekly drift audit (#6) | Continuous crawl queue; re-check frequency per surface volatility |
| Weekly approval sitting (§13.3) | No sitting. Items surface only when they touch §15.4 gated classes; everything else executes immediately |
| Quarterly/periodic library + taxonomy curation | Continuous: terms adopt automatically when in-register and semantically clean (§15.4) |
| Bounded experiments, slow promotion (#45) | Many concurrent experiments; promote at statistical significance, roll back on degradation, no waiting period |
| Human-queued index resubmission / corrections | Auto-submitted where an API exists; packet auto-prepared where not |

### 15.2 Multi-horizon pattern memory (7 / 30 / 90 / 180 / 365)
The system reasons across five rolling windows simultaneously; every metric in
`citation_outcomes`, `content_performance`, `term_performance`, and
`visibility_probes` is aggregated at all five horizons.
```sql
pattern_horizons (id, subject_type CHECK (subject_type IN ('term','page',
  'track','engine','cluster','coach')), subject_ref, horizon_days CHECK
  (horizon_days IN (7,30,90,180,365)), metric, value, delta_vs_prior,
  trend CHECK (trend IN ('rising','stable','declining','volatile')),
  computed_at)
seasonal_memory (id, subject_ref, period_signature JSONB, confidence,
  years_observed, next_expected_window, computed_at)
```
Interpretation rules (binding):
- **7d** — noise floor + acute shifts; triggers investigation, never strategy change alone.
- **30d** — operational truth; primary trigger for rotation, content, and term decisions.
- **90d** — track-level allocation (§10.1 barbell reweighting).
- **180d** — structural trends: engine behavior change, competitor entry, category maturation.
- **365d** — seasonality; `seasonal_memory` PRE-POSITIONS content and coverage ahead of predicted demand windows (back-to-school, New Year, holiday grief, awareness months) rather than reacting to them.
- **Divergence rule:** when short and long horizons disagree (7d spike vs 180d decline), the longer horizon governs strategy while the shorter triggers an experiment — the system tests rather than lurches.

### 15.3 Algorithm-shift detection (keeps pace with engine changes)
`disco_shift_detector` (flag `DISCO_SHIFT`): watches for correlated citation/
ranking movement across many pages and engines simultaneously — the signature
of an engine-side change rather than a page-side one.
On detection: raise sampling rate, freeze non-essential experiments, launch a
structured re-learning sweep (#42 citation learner) to derive the NEW citation
patterns, regenerate templates, and log the shift into `pattern_horizons` at
180d so the system accumulates a history of how engines have evolved. No human
trigger, no human interpretation required.

### 15.4 Effortless by default — gated classes reduced to four
The system ACTS by default. It pauses only for four content classes, and
never for cadence, volume, or routine judgment:
1. Register boundary (clinical vs coaching language on a specific profile)
2. Positioning/product claims (§12.3)
3. Pricing
4. Any assertion about a coach's credentials, licensure, or lawful service area

Everything else — including NEW TAXONOMY CONCEPTS (reclassified from v1.7),
page structure, phrasing, cadence, coverage, content topics, experiments,
allocation, corrections, resubmissions — executes autonomously. New concepts
adopt immediately when in-register and semantically clean; ethics-flagged
trends (§2.3) still route to a human.

**Approval is a tap, not a project:** gated items arrive as LN-pre-drafted
decisions with evidence, recommendation, and a one-tap approve/reject —
delivered through the Chat rail. **Auto-approve-on-timeout for LOW-RISK gated
items only** (configurable, default 72h) so an absent Admin never stalls the
system; the four classes above never auto-approve — they wait, while
everything around them keeps running.

**Coach effort: zero after onboarding authorization.** No coach ever receives
a discoverability task. LN detects, drafts, and acts under the §13.9
authorization; the coach sees only outcomes (visibility, inquiries, bookings)
in Coach Command.

### 15.5 Deeper capture & funneling (the growth objective)
Autonomy's purpose is not tidiness — it is compounding capture:
- **Funnel-aware generation:** content and pages are generated toward measured
  conversion, not traffic. `content_performance` subscriber attribution feeds
  topic, depth, structure, and CTA choices continuously (#43 + #31).
- **Path learning:** the system learns which discovery→intake paths convert per
  cluster (query class × geo × specialty × language) and preferentially builds
  more of what converts.
- **Adaptive funnel construction:** where a converting path lacks a step
  (missing hub, missing explainer, missing comparison page, missing
  language variant), the system builds it automatically.
- **LN Widget as the closer:** arriving traffic is met conversationally,
  qualified, and routed to intake; widget transcripts feed the same learning
  loops (anonymized, per crystal rules).
- **Supply pull:** clusters converting above threshold with insufficient coach
  coverage escalate in `recruiting_targets` (#48) — demand pulls supply
  automatically.

### 15.6 Acceptance criteria
- DAC20: No worker in §13/§14 fires on a fixed calendar; every trigger is
  signal-derived (audit of scheduler config returns zero fixed-cadence jobs
  except daily horizon consolidation).
- DAC21: All five horizons compute daily for every tracked subject; a 7d spike
  contradicting a 180d decline produces an experiment, not a strategy change.
- DAC22: A simulated engine-behavior shift is detected without human input,
  raises sampling, triggers re-learning, and regenerates templates.
- DAC23: A seasonal window recurring in 365d memory causes content and coverage
  to be pre-positioned BEFORE the window opens.
- DAC24: Zero coach-facing discoverability tasks exist post-authorization;
  Admin receives only §15.4-class decisions, one-tap, with low-risk items
  auto-approving on timeout while the system continues running.
- DAC25: Content/page generation demonstrably shifts toward higher-converting
  clusters over time (traceable subscriber attribution → generation inputs).

---

## 16. v1.9 — Campaign ↔ discovery learning bridge (autonomous backlog + continuous learning)

The coach campaign engine (newsletters, LinkedIn posts, drip touches — built in
the v1.5 spec §12/WS-C) and this discoverability system currently learn in
isolation: two learning systems, same domain, no shared brain. §16 merges them
and makes the merge retroactive — the system mines everything already produced
before it starts learning from new output.

### 16.1 Autonomous backlogging (retroactive learning — no human curation)
On activation, `disco_backfill_miner` (flag `DISCO_BACKFILL`) ingests ALL
historical assets and outcomes without prompting: every marketing_content row
(published posts, drips, newsletters), campaign_engagements history, review-
queue decisions (approve/reject/rewrite notes = preference signal), voice
transcripts and Voice Profiles, session-derived language patterns (anonymized),
existing site/page content, and any prior email performance data. It scores
each against outcomes, derives initial patterns, seeds
`term_performance`/`content_performance`/`pattern_horizons` at all five
horizons (§15.2), and — critically — BACKFILLS SEASONAL MEMORY from historical
dates so year-one seasonality is available on day one rather than after 365
days of observation.
Continuous mode after backfill: every new asset and outcome enters the same
pipeline automatically. Backlog is never a one-time job — new coaches'
histories are mined at onboarding, and re-mining triggers whenever the citation
learner (#42) derives new pattern classes worth re-scoring old assets against.

### 16.2 Bidirectional learning bridge
| Direction | What flows | Effect |
|---|---|---|
| Campaign → discovery | High-performing subject lines, hooks, pillar/topic performance, reply-generating language | Candidate taxonomy terms, article angles, page phrasing, meta descriptions |
| Discovery → campaign | Learned client query language, converting cluster vocabulary, citation-winning phrasings | Next campaign generation speaks in the terms the audience is already searching |
One vocabulary learned from both directions; `disco_taxonomy_evolver` (#44)
consumes both streams.

### 16.3 Cross-coach marketing crystals (the compounding advantage)
Anonymized, aggregated campaign performance across the roster crystallizes as
marketing-domain wisdom (build spec §12.3 rules apply: anonymized AT CREATION,
domain='marketing'): which pillars convert per specialty, which cadences hold
attention per audience type, which hooks land per language/region.
Effect: a brand-new coach's FIRST campaign starts from what worked across the
entire network instead of from zero — an asset no individual practitioner and
no listing directory can replicate.
BOUNDARY (binding): aggregate patterns are platform wisdom; an individual
coach's client list, prospect data, or proprietary methodology is never shared
or cross-generated. Anonymization failure = crystal rejected, not stored.

### 16.4 Campaign assets as capture surfaces
Every asset LN already writes becomes indexable, not just sent:
- Newsletter issues → crawlable web archive on the brand domain (canonical,
  schema'd, dated).
- LinkedIn posts → expanded into indexable articles on the coach's directory
  profile (LinkedIn itself is poorly indexed; the profile article is the
  citable home).
- Drip content → FAQ layer on the coach's public page (FAQPage schema).
- All carry booking CTAs into the platform (app.sovereignsanctuary.net).
Written once by LN, serving nurture AND discovery simultaneously.

### 16.5 Unified funnel learning
Campaign channels join discovery tracks as first-class allocation targets in
`disco_allocator` (#46): the system measures subscribers-per-effort across
newsletter, drip, LinkedIn, directory, category pages, and upstream articles
per cluster (query class × geo × specialty × language), then reallocates
generation effort continuously toward what converts — including shifting
effort BETWEEN campaign and discovery work, which neither system could do
alone.

### 16.6 Acceptance criteria
- DAC26: On activation, historical marketing_content, engagements, review
  decisions, and voice assets are mined unattended; horizons and seasonal
  memory are populated from historical dates with no human curation.
- DAC27: A high-performing campaign phrase appears as a candidate taxonomy
  term (register-checked) and, conversely, a learned converting query phrase
  appears in subsequently generated campaign content — both traceable.
- DAC28: Cross-coach marketing crystals contain zero re-identifiable coach or
  client specifics; a new coach's first campaign measurably inherits network
  patterns.
- DAC29: Newsletter/post/drip assets exist as indexed, schema'd public pages
  with booking CTAs within one build cycle of publication.
- DAC30: Allocation shifts effort between campaign and discovery channels on
  measured subscriber attribution, explainable in the autonomy digest.

---

## 17. v2.0 — Completion checklist (BINDING: no partial builds)

### 17.0 The no-partial-build rule (binding)
A half-built discoverability system is worse than none: partial canonicalization
fragments entities (the exact failure this plan exists to fix), sensors without
motors produce dashboards nobody reads, and adaptive workers without measurement
optimize noise. Therefore:
1. **Tier completion is atomic.** A tier is DONE only when every item in it
   passes. No tier activates in production with unchecked items.
2. **Dependency direction is absolute.** No tier may start before the prior tier
   is 100% complete and verified. Tier 4 (adaptation) without Tier 3
   (measurement) is prohibited — it would adapt on nothing.
3. **Partial = OFF.** Any item that cannot be completed causes its FLAG to stay
   OFF and its tier to remain incomplete; it never ships "mostly working."
4. **Verification, not assertion.** Each item is checked by its DAC/test, not by
   someone's judgment that it looks fine.
5. **Rollback obligation.** If an item regresses after go-live, its flag returns
   to OFF until repaired — the tier reverts to incomplete.

### 17.1 TIER 0 — Human prerequisites — ✅ CLOSED (decisions made; see `tier-0-completion.md`)
All Tier 0 DECISIONS are made and all drafts written. Remaining boxes are
IMPLEMENTATION + SMOKE TEST only — no further judgment required.
- [x] T0.1 Pricing/trial model — DECIDED (pre-existing): Trial-Threshold (7-day, card required, 10K tokens) → Inner Chamber $49/mo → Sovereign Circle $149/mo; Coach-Only $0; family of three ≈ $5/day. Stripe, zero IAP. Lifecycle: day-4/day-6 warnings → day-7 expiry → 3-day grace → day-10 lockout.
- [x] T0.2 Brand positioning + copy — DRAFTED: canonical positioning sentence, meta description, title tag, hero copy, register-correction table, Organization JSON-LD with Offer markup. → IMPLEMENT: paste into site (interim: Squarespace code injection today), fill 2 sameAs URLs. SMOKE TEST: raw-HTML fetch shows new meta + positioning sentence + valid JSON-LD.
- [x] T0.3 Advertising/testimonial matrix — COUNSEL BRIEF DRAFTED (Deliverable 3). → IMPLEMENT: send brief with attachments. Gates CLINICAL-CLASS surfaces only; coaching-class proceeds.
- [x] T0.4 Retention/erasure values — SAME BRIEF (Deliverables 1–2, incl. crypto-shred validation + EU residency). → IMPLEMENT: send. Gates clinical-class + ENABLE_CLINICAL_ERASURE only.
- [x] T0.5 D1 + D3 — DECIDED: directory = subdirectory `/coaches/{slug}` on brand domain; marketing site MIGRATES OFF SQUARESPACE to own stack (SSR/SSG required — added to Tier 1 scope, incl. 1:1 301 map, GSC/Bing re-verify, zero-404 cutover). D3 coach public-profile + listing-agent consent text DRAFTED (3 separable scopes). → IMPLEMENT: build/migrate; publish consent at onboarding.
- [x] T0.6 Credential registry — INTERIM STRUCTURE DEFINED from existing pre-authorization verifications (credential_class, credential_type, jurisdiction, identifier, verified_at, verified_by, expires_at); Tier 1 workers read it unchanged when the full §15.1 table ships. → IMPLEMENT: structure existing records. GATE: no credential record = no public profile.

### 17.2 TIER 1 — Foundation (must be 100% before ANY page publishes)
- [ ] T1.1 `canonical_identity` + `vocabulary_taxonomy` + `discovery_pages` schema live (§13.1)
- [x] T1.2 Seed taxonomy AUTHORED — 10 concepts × clinical/coaching registers, EN query-language complete; DE/FR seed rows need native query phrasings before EU surfaces publish (C6). → IMPLEMENT: load into `vocabulary_taxonomy`
- [ ] T1.3 `disco_canonical_renderer` (#1) — one record → every surface (DAC1)
- [ ] T1.4 `disco_build_deploy` (#14) SSR/static + raw-HTML crawlability gate (DAC6)
- [ ] T1.5 `disco_schema_validator` (#32) blocking in CI (DAC6)
- [ ] T1.6 `disco_register_linter` (#15) blocking pre-publish (DAC3)
- [ ] T1.7 `disco_area_deriver` (#16) licensure→areaServed (§2.2)
- [ ] T1.8 `disco_credential_propagator` (#4) same-day lapse propagation (DAC3)
- [ ] T1.9 `disco_lifecycle` (#5) pause/depart redirects + unstitch (DAC4)
- [x] T1.10 robots.txt (brand + SEPARATE app-host file, C2) and llms.txt AUTHORED; `/api/v1/public/` allow-carve added (C1); agent endpoints commented until T5.1/T5.2 live (C3). → IMPLEMENT: deploy + verify Cloudflare not blocking allowed crawlers
- [ ] T1.11 Organization + Person(founder) + Service/SoftwareApplication schema on brand pages (§11)
- [ ] T1.12 GSC + Bing Webmaster verified, sitemaps submitted
- [ ] T1.13 Onboarding authorization flow (listing-agent + GBP manager consent) — MOVED FROM TIER 2 per §19.1
- [ ] T1.14 `disco_gbp_manager` (#35): GBP claim drive for every launch coach — MOVED FROM TIER 2 per §19.1
- [ ] T1.15 `disco_listing_orchestrator` (#34) + `disco_listing_tracker` (#38) — MOVED FROM TIER 2 per §19.1
- [ ] T1.16 `disco_authority_builder` (#49-adjacent, §19.1a): outreach targets, packets, placement tracking
**Tier 1 gate:** every launch coach renders identically across all surfaces; zero drift in audit; raw-HTML fetch passes; app unindexed; AND listing coverage + GBP claim status recorded for every launch coach (DAC31).
**Tier 1 scope addition (from T0.5):** marketing-site migration off Squarespace onto the SSR/SSG stack, with 1:1 URL mapping + 301s, commerce/cart retirement confirmed, GSC + Bing re-verification, and T0.2 copy/schema live before DNS cutover.

### 17.3 TIER 2 — Coverage & onboarding (must be 100% before scaling coach count)
- [ ] T2.1 `disco_onboarding_pipeline` (#2) same-day legibility (DAC2)
- [→] T2.2 Onboarding AUTHORIZATION flow — **RELOCATED TO TIER 1 (T1.13) per §19.1**
- [→] T2.3 `disco_listing_orchestrator` + `disco_listing_tracker` — **RELOCATED TO TIER 1 (T1.15) per §19.1**
- [→] T2.4 `disco_gbp_manager` API-driven post-claim automation — **RELOCATED TO TIER 1 (T1.14) per §19.1**
- [ ] T2.5 `disco_hub_generator` (#3) supply-gated only
- [ ] T2.6 `disco_drift_auditor` (#6) continuous crawl queue
- [ ] T2.7 `disco_credential_prechecker` (#37)
- [x] T2.8 Product/pricing copy AUTHORED. C4 RESOLVED: Sovereign Circle $149/mo = Head of Household + partner (2 people); additional dependents are per-user add-ons. Canonical claim corrected to '$5/day for you and your partner'. → IMPLEMENT: publish copy + Offer schema (four tiers only; add-on pricing points to account settings, excluded from schema)
- [x] T2.9 Brand-defense copy AUTHORED. C5 RESOLVED: unverified claims ('primary-source', 'background checked') removed; retained claim = credentials verified before activation + ongoing status maintenance. → IMPLEMENT: publish
- [ ] T2.10 Public-surface privacy: EU consent banner + consent mode + form notices (§9.5)
**Tier 2 gate:** a new coach reaches full external + GBP coverage with zero post-onboarding tasks; category pages indexed.

### 17.4 TIER 3 — Measurement (must be 100% before ANY adaptive worker activates)
- [x] T3.1 Probe prompt set AUTHORED — 8 classes (added Class 7 upstream-symptom and Class 8 recruitment, omitted from first draft); 2026-08-16 pre-implementation baseline recorded. → IMPLEMENT: load + wire continuous adaptive sampling
- [ ] T3.2 Claims logging + `disco_correction_dispatcher` (#36) (§9.6)
- [ ] T3.3 `disco_referrer_attribution` (#10) `ai_search` channel
- [ ] T3.4 `disco_funnel_instrumentation` (#31) citation→click→signup→subscriber
- [ ] T3.5 `disco_index_watch` (#33) + `disco_decay_monitor` (#29)
- [ ] T3.6 `disco_competitor_watch` (#30)
- [ ] T3.7 `pattern_horizons` + `seasonal_memory` computing at 7/30/90/180/365 daily (DAC21)
- [ ] T3.8 `disco_backfill_miner` (#§16.1) historical mining + seasonal backfill complete (DAC26)
**Tier 3 gate:** every metric the adaptive layer consumes is measured, populated, and horizon-aggregated. NO Tier 4 flag may turn ON until this gate passes.

### 17.5 TIER 4 — Autonomy (all-or-nothing; partial adaptation optimizes noise)
- [ ] T4.1 `disco_performance_rotator` (#41) — calendar rotation removed (DAC20)
- [ ] T4.2 `disco_citation_learner` (#42) (DAC14)
- [ ] T4.3 `disco_content_loop` (#43) + `disco_content_scheduler` (#40) (DAC16) — publication requires human approval (§19.2 Correction 2)
- [ ] T4.12 `disco_originality_gate` (#49) BLOCKING editorial standard (DAC32)
- [ ] T4.13 `disco_volume_governor` (#50) quality-gated publication velocity (DAC34)
- [ ] T4.14 `disco_thin_content_auditor` (#51)
- [ ] T4.15 LEVER 1 (§20.1): `disco_corroboration_engine` (#52), `disco_attestation_service` (#53), `disco_confidence_scorer` (#54) — DAC37/DAC38
- [ ] T4.16 LEVER 2 (§20.2): `disco_insight_miner` (#55), `disco_gain_scorer` (#56, BLOCKING), `disco_practitioner_capture` (#57) — DAC39/DAC40
- [ ] T4.17 LEVER 3 (§20.3): `disco_value_library` (#58), `disco_value_matcher` (#59), `disco_ask_governor` (#60, BLOCKING) — DAC41
- [ ] T4.18 Lever crystallization + conflict precedence rule enforced (DAC42/DAC43)
- [ ] T4.19 `disco_verification_orchestrator` (#61) — continuous proof, human confirmation only (DAC44)
- [ ] T4.20 `disco_cac_ledger` (#63) + claim-truth register enforcement (DAC47/DAC48)
- [ ] T4.21 `disco_recruitment_engine` (#64) — closes the demand→supply loop (DAC49)
- [ ] T4.4 `disco_taxonomy_evolver` (#44) with register/ethics gates
- [ ] T4.5 `disco_experimenter` (#45) concurrent, significance-promoted, auto-rollback (DAC15)
- [ ] T4.6 `disco_allocator` (#46) incl. campaign channels (DAC17/DAC30)
- [ ] T4.7 `disco_shift_detector` (§15.3) (DAC22)
- [ ] T4.8 `disco_crystal_bridge` (#47) + cross-coach marketing crystals (DAC28)
- [ ] T4.9 `disco_demand_sensor` (#11) + `disco_supply_optimizer` (#48) (DAC7)
- [ ] T4.10 `disco_queue_manager` (#39) + one-tap Chat approvals + auto-approve-on-timeout for low-risk (DAC24)
- [x] T4.11 Autonomy config AUTHORED (v1.1) — 4 gated classes with G3 widened to cover tier INCLUSIONS, 3 standing auto-approve rules with timeouts, 8 ADAPT_FREEZE triggers, explicit safety rails. → IMPLEMENT: load into Queens governance service
**Tier 4 gate:** a full unattended cycle completes (DAC13) and a simulated engine shift is handled without human input (DAC22).

### 17.6 TIER 5 — Integration & compounding
- [ ] T5.1 `disco_agent_api` (#13) live + MCP server listed in connector registries (§10.2)
- [ ] T5.2 Credential-verification endpoint public (§10.2)
- [ ] T5.3 LN Widget on directory/product pages, feeding intake + learning (§15.5) — **BLOCKED until §19.3 crisis screening passes DAC35**
- [ ] T5.7 Public-widget crisis screening + value-first rule + conversion suspension on distress (DAC35/DAC36)
- [ ] T5.9 `disco_inline_value_renderer` (#62) — server-side value + crisis resources in initial HTML; page useful with JS disabled (DAC45/DAC46)
- [ ] T5.8 Per-step funnel attribution, citation → paid (DAC36)
- [ ] T5.4 Campaign↔discovery bidirectional bridge (§16.2) (DAC27)
- [ ] T5.5 Campaign assets published as indexed capture surfaces (§16.4) (DAC29)
- [ ] T5.6 `disco_review_dispatcher` (#12) coaching-class, jurisdiction-gated
**Tier 5 gate:** campaign and discovery learn from each other and share allocation.

### 17.7 Definition of 100% complete
The plan is COMPLETE only when: every Tier 0–5 box is checked; DAC1–DAC30 all
pass; zero flags remain OFF for incompleteness (OFF only as deliberate kill
switches); the drift audit returns zero divergence across all surfaces; a raw-
HTML fetch of every public page type contains full content and valid schema;
one full unattended adaptation cycle has completed end-to-end; and the four
gated classes correctly block and escalate under test (DAC18).
Anything less is an INCOMPLETE BUILD and must not be represented as live.


---

# PART B — TIER 0 COMPLETION RECORD

**Status doc — updated as items are confirmed. Tier 1 may not begin until all six are checked.**

---

### ✅ T0.1 — Pricing / trial model — COMPLETE (pre-existing, no build required)

**Confirmed current lineup:**
| Tier | Price | Notes |
|---|---|---|
| Trial-Threshold | $0 (7-day trial) | Card required at signup; 10K tokens |
| Inner Chamber | $49/mo | Stripe |
| Sovereign Circle | $149/mo | Stripe |
| Coach-Only | $0 | Client of an existing coach |

**Trial lifecycle (built + tested, Stripe test and live):**
Signup → 7-day trial (card required, 10K tokens) → day-4 warning banner →
day-6 warning banner → day-7 expiry → 3-day grace → day-10 lockout → upgrade.
All billing through Stripe; zero IAP.

**Add-ons:** family member add-ons, voice prepaid blocks, token packs,
coaching (single $175 / 4-pack $600 / 8-pack $1,120).

**Family structure (CONFIRMED 2026-08-16):** Sovereign Circle $149/month covers
**Head of Household + partner (first dependent) = two people**. Each additional
dependent is a per-user monthly add-on.

**⚠️ CANONICAL FIGURE CORRECTED:** $149 ÷ 30 = **$4.97/day for two people**.
The earlier "about $5 a day for a family of three" claim is NOT supported and
must be replaced everywhere it appears. Approved canonical phrasings:
- "About $5 a day for you and your partner" (exact)
- "Family coverage starting at about $5 a day" (accurate as a floor)
Canonical claim: **"about $5 a day for you and your partner."** Use it
consistently across homepage, pricing, category pages, Offer schema, llms.txt,
and LN Widget answers (§2.0 canonicalization).

**Add-on pricing deprioritized (binding):** additional family members are
mentioned in copy with a pointer to account settings for current per-member
pricing; per-dependent prices are NOT enumerated in Offer schema. Schema and
hero space carry trust signals (verification, knowsAbout, areaServed, founder
entity, FAQ), which outweigh billing granularity for citation purposes.

**Discoverability implications (feed to §12.2 pricing page + §15.5 funnel):**
- Card-required trial converts at the high end (40–60% trial→paid); the earlier
  funnel estimate was pessimistic at this stage.
- Conversion risk sits UPSTREAM: a card wall in front of AI-referred cold
  traffic. Mitigation already exists — surface the free/low-friction entry
  path prominently to cold discovery traffic, with the 7-day trial as the
  high-intent path.
- Pricing must be publicly visible and machine-extractable (not gated behind
  signup) — Offer schema on the pricing page with all four tiers.

---

### ✅ T0.2 — Brand positioning + homepage copy — COMPLETE (drafts below; apply in Squarespace)

**Positioning decision (binding for all public surfaces):**
LEAD = verified humans + AI continuity. SUPPORT = family affordability.
Order is never inverted: trust decides whether an AI engine will name you at
all; price decides whether the reader clicks.

**Canonical positioning sentence (use verbatim across surfaces — the machine-
extractable identity claim):**
> Sovereign Sanctuary pairs Little Nate — an AI companion that remembers your
> history and supports you 24/7 — with certified and licensed human
> professionals, verified before they ever work with a client. Coverage for you
> and your partner costs about $5 a day.

**Meta description (155 chars, replaces current):**
> AI companion support paired with verified certified and licensed
> professionals. 24/7 care for individuals and families — about $5 a day for you
> and your partner.

**Title tag:**
> Sovereign Sanctuary | AI Companion + Verified Licensed Professionals

**Hero copy (replaces "Sentient IP Quantum AI" framing):**
> **Support that knows your history — and professionals who are verified before
> they meet you.**
> Little Nate is an AI companion that remembers your journey and is available
> every hour of every day. When you need a human, you're connected to a coach
> or licensed professional whose credentials we verified before activation.
> Coverage for you and your partner: about $5 a day.

**Register corrections (binding — §12.3):**
| Remove from public surfaces | Replace with |
|---|---|
| "Sentient IP Quantum AI" | "AI companion built on a patented therapeutic process" |
| "healing, finally made possible" | "care that stays with you" / concrete capability statements |
| "therapy" / "treatment" as platform claims | "support", "coaching", "care" — clinical register only where a licensed professional and clinical-class relationship applies |
| Vague wellness language ("journey to wellness and resilience") | Concrete, extractable capability + price + verification claims |

Patent reference is retained (it is factual and a credibility asset) but framed
as process, not sentience.

**Organization JSON-LD (add via Squarespace code injection, homepage):**
```json
{
  "@context": "https://schema.org",
  "@type": "Organization",
  "name": "Sovereign Sanctuary",
  "url": "https://www.sovereignsanctuary.net",
  "description": "AI companion support paired with verified certified and licensed human professionals, for individuals and families.",
  "founder": {
    "@type": "Person",
    "name": "Nathaniel Nevedal",
    "sameAs": ["<LinkedIn profile URL>"]
  },
  "sameAs": ["<LinkedIn company page>", "<other org profiles>"],
  "makesOffer": [
    {"@type": "Offer", "name": "Trial-Threshold", "price": "0", "priceCurrency": "USD", "description": "7-day trial, card required"},
    {"@type": "Offer", "name": "Inner Chamber", "price": "49", "priceCurrency": "USD", "priceSpecification": {"@type": "UnitPriceSpecification", "billingDuration": 1, "billingIncrement": "MONTH"}},
    {"@type": "Offer", "name": "Sovereign Circle", "price": "149", "priceCurrency": "USD", "priceSpecification": {"@type": "UnitPriceSpecification", "billingDuration": 1, "billingIncrement": "MONTH"}},
    {"@type": "Offer", "name": "Coach-Only", "price": "0", "priceCurrency": "USD", "description": "For clients of an existing Sovereign Sanctuary coach"}
  ]
}
```
(Fill the two sameAs URLs; add SoftwareApplication + Service schema on the
product/pricing pages per §12.2.)

**Apply-to surfaces:** homepage, About, Pricing, Clinical Safety, Our Team,
LinkedIn company page, founder profile headline, LN Widget intro, newsletter
footers. Canonical sentence identical everywhere (§2.0).

### 📤 T0.3 + T0.4 — Counsel engagement (SEND TODAY; longest lead item)

**Tier 0 completion for these two = brief SENT and engagement opened.** Values
return later and populate config; they gate CLINICAL-CLASS public surfaces and
ENABLE_CLINICAL_ERASURE only. **Coaching-class surfaces proceed without them.**

#### Counsel brief (single engagement, three deliverables)

> **Subject: Legal review — mental health platform: retention, erasure, and
> professional advertising rules (US + EU)**
>
> **About us.** Sovereign Sanctuary is a mental health support platform pairing
> an AI companion with human professionals. Every professional is verified
> before account activation and falls into one of two classes: (a) **licensed
> clinical** (e.g. LMFT, LCSW, licensed counselors) and (b) **certified coach**
> (non-licensed, e.g. ICF-credentialed). Our system treats these as legally
> distinct relationship types with different vocabulary, retention, and
> advertising rules applied automatically. Clients are in both the United
> States and the European Union.
>
> **Deliverable 1 — Records retention matrix.** Minimum retention periods, per
> jurisdiction, for records arising from each relationship class: session
> notes, care/treatment plans, AI-companion conversation logs, assessments, and
> supervision records. US: states where our licensed professionals practice
> (list attached). EU: member states where we serve clients (list attached).
> We encode these as configurable values.
>
> **Deliverable 2 — Erasure, legal hold, and data-subject rights.** We
> implement erasure via crypto-shredding (per-client encryption keys destroyed
> on a valid request, rendering all copies including backups unreadable). We
> need: (a) confirmation this satisfies GDPR Art. 17 and applicable US state
> privacy laws; (b) precedence rules when a retention duty conflicts with an
> erasure request; (c) legal-hold triggers and documentation standards; (d)
> whether AI-companion conversation logs and anonymized derived data (no
> re-identifiable content) fall inside or outside erasure scope; (e) any EU
> data-residency requirement or whether SCCs suffice.
>
> **Deliverable 3 — Professional advertising and testimonial matrix.** We
> operate a public directory of our professionals, optimized to be found by
> search engines and AI assistants. Per jurisdiction and per relationship
> class, we need rules governing: client reviews and testimonials (several US
> boards restrict these for licensed therapists), superlative or comparative
> claims, credential and verification badges, specialty claims, "treatment" vs
> "coaching/support" language, cross-state and cross-border virtual service
> advertising (must advertised service area match licensure, including
> compacts?), and required disclaimers. We encode these as automated
> per-jurisdiction gates.
>
> **Also for review (attached):** our coach public-profile and listing-agent
> consent text, and client consent language covering supervising-coach
> oversight access.
>
> **Why it matters commercially:** these values compile into automated
> enforcement — our system blocks non-compliant language before publication
> rather than relying on staff discretion. We need defensible values, not
> general guidance.

**Attachments:** state/jurisdiction lists for licensed professionals; EU member
states served; D3 consent text (below); build spec §15.

### ✅ T0.5 — D1 + D3 — COMPLETE

#### D1 — Domain & hosting architecture: APPROVED (Option B)
- **Directory = subdirectory:** `sovereignsanctuary.net/coaches/{slug}`, hubs at
  `/coaches/{specialty}/{location}`, articles at `/articles/{slug}`. All
  authority compounds to the brand domain (§11.1).
- **Marketing site MIGRATES OFF SQUARESPACE onto own stack** — required for
  SSR/static generation, per-page JSON-LD at scale, programmatic hub
  generation, and the §13 render pipeline. Squarespace cannot serve these.
- **Migration requirements (add to Tier 1 scope):**
  - Framework with SSR/SSG (raw-HTML crawlability gate, DAC6)
  - 1:1 URL mapping + 301s for every existing Squarespace URL (/about,
    /our-team, /new-page→/clinical-safety, /contact, /thera-world, /pricing,
    /videos); zero 404s at cutover
  - Preserve/redirect any existing commerce (Squarespace /cart) or confirm
    retired — all billing is Stripe
  - Re-verify GSC + Bing after migration; resubmit sitemaps
  - `app.sovereignsanctuary.net` unchanged (conversion endpoint, crawler-blocked)
  - Cutover check: canonical positioning sentence + Organization JSON-LD (T0.2)
    live on the new stack before DNS switch
- **INTERIM (do not wait for migration):** apply T0.2 meta description, title,
  hero copy, and Organization JSON-LD to the current Squarespace site now via
  code injection. Brand/category capture (§12) starts immediately; migration
  unblocks the directory, not the brand layer.

#### D3 — Coach public-profile opt-in consent (versioned per build spec §15.8)

**Consent record fields:** coach_id, consent_version, granted_at, revoked_at,
scopes_granted (public_profile, listing_agent, gbp_manager, article_byline,
review_invites), ip/actor, document_ref.

**Coach-facing consent text (v1) — presented at onboarding:**

> **Public Profile & Listing Authorization**
>
> Sovereign Sanctuary can create and maintain a public profile for you so that
> clients searching online — including through AI assistants — can find you.
> This is optional and you can withdraw it at any time.
>
> **What we publish, with your approval:** your professional name, photo,
> credential type and issuing jurisdiction, verification status, specialties,
> languages, service area, session formats (in person / virtual), a
> professional biography, and articles published under your name. We publish
> your booking link — never your personal email or phone number.
>
> **What we never publish:** any client information, session content, case
> details, or anything derived from your clinical or coaching work. Client
> material never appears on any public surface.
>
> **Listing agent authorization (optional):** you may authorize Sovereign
> Sanctuary to act as your listing agent — preparing and maintaining
> consistent professional listings on external directories on your behalf, and
> acting as a manager on your Google Business Profile once you grant access.
> We only publish the professional information described above, we keep your
> details consistent across platforms, and every change we make in your name is
> logged and visible to you in Coach Command. You own your Google Business
> Profile and can remove our access at any time.
>
> **Accuracy and credentials:** your public credential badge reflects your
> verification status with us. If a credential lapses or expires, the badge and
> any clinical-register language are removed automatically, and your profile may
> be paused until verification is restored.
>
> **Reviews and testimonials:** where permitted for your credential type and
> jurisdiction, we may invite satisfied clients to leave public reviews. We
> never write, incentivize, or fabricate reviews. Testimonial rules for
> licensed professionals vary by jurisdiction and are applied automatically.
>
> **If you leave:** your public profile is removed and its address redirects to
> a general listing page. Links connecting your profile to your other
> professional presences are removed, and our access to your Google Business
> Profile is released. Articles published under your name may remain unless you
> request removal.
>
> **Withdrawing:** you can pause or withdraw this authorization at any time in
> Coach Command. Withdrawal removes your public profile and ends listing agent
> activity. Listings created on external platforms remain under your control.
>
> [ ] I authorize a public profile as described.
> [ ] I authorize Sovereign Sanctuary to act as my listing agent and Google
>     Business Profile manager.
> [ ] I authorize articles to be published under my name, subject to my review.

**Note:** counsel should review this text alongside T0.3 (advertising-rule
matrix), particularly the reviews/testimonials paragraph for licensed
clinical-class coaches.

### ✅ T0.6 — Credential registry — COMPLETE (interim structure defined)

**Requirement:** badges, register enforcement, and licensure-derived areaServed
need a credential data source. The full `coach_credentials` table ships in the
v1.5 build (§15.1).

**Interim path (unblocks Tier 1 now):** every coach is already verified before
account authorization — those existing records are the seed data.
- Structure existing verifications into the §15.1 shape: credential_class
  (licensed_clinical | certified_coach), credential_type, jurisdiction,
  identifier, verified_at, verified_by, expires_at.
- Data-entry/migration task, not a build task; can run before or alongside
  Tier 1.
- Tier 1 workers (`disco_area_deriver`, `disco_credential_propagator`,
  `disco_register_linter`) read this structure and need no change when the full
  registry ships.

**Gate:** every launch coach has a structured credential record (class,
jurisdiction, expiry) before their public profile renders. No record = no
profile.

---

### Tier 0 status summary

| Item | Status |
|---|---|
| T0.1 Pricing / trial model | ✅ Complete — pre-existing, no build |
| T0.2 Brand copy + Organization schema | ✅ Complete — apply via code injection now |
| T0.3 Advertising/testimonial matrix | 📤 Brief ready — send today; gates clinical-class only |
| T0.4 Retention / erasure values | 📤 Same brief; gates clinical-class only |
| T0.5 D1 + D3 | ✅ Complete — subdirectory + off-Squarespace approved; consent drafted |
| T0.6 Credential registry | ✅ Complete — interim structure from existing verifications |

**TIER 0 CLOSED. Tier 1 may begin.**
Coaching-class surfaces are fully unblocked. Clinical-class public surfaces
remain gated until counsel returns T0.3/T0.4 values — an automated gate, not a
build blocker.

**Remaining Tier 0 actions (execution, not decisions):**
1. Send the counsel brief with attachments.
2. Apply T0.2 copy + Organization JSON-LD to the current site (interim, today).
3. Fill the two `sameAs` URLs (LinkedIn company page, founder profile).
4. Structure existing coach verification records into the §15.1 shape.
5. Smoke test: fetch the homepage raw HTML and confirm the new meta
   description, canonical positioning sentence, and valid Organization JSON-LD
   are present.


---

# PART C — TIER 1–4 AUTHORED DELIVERABLES

**Companion to `tier-0-completion.md`. Covers T1.2, T1.10, T2.8, T2.9, T3.1, T4.11.**
**Status: AUTHORED. Remaining work = implement + smoke test.**

---

### ⚠️ CORRECTIONS APPLIED TO SUBMITTED DRAFTS (read first)

| # | Issue | Correction |
|---|---|---|
| C1 | robots.txt `Disallow: /api/` contradicts llms.txt advertising `/api/v1/public/*` — crawlers would be blocked from the agent-queryable layer | Explicit `Allow: /api/v1/public/` above the broader `/api/` disallow |
| C2 | `Disallow: /app/` on the brand domain does NOT protect `app.sovereignsanctuary.net` — a separate host needs its own robots.txt | Separate app-host robots.txt added (full disallow) |
| C3 | llms.txt advertises the MCP descriptor + public API endpoints that do not exist yet (Tier 5). Advertising dead endpoints damages agent trust | Endpoints commented out until T5.1/T5.2 pass; llms.txt is regenerated by `disco_canonical_renderer`, not hand-maintained |
| C4 | **PRICING CLAIM CONFLICT (G3 gated class):** copy states Sovereign Circle $149 includes "complete family access for up to three members." Prior billing build has family as a paid ADD-ON (Family Sanctuary) on top of a tier | ⛔ HOLD — publishing an unverified inclusion claim is a G3 violation and a billing dispute risk. Admin must confirm which is true before this copy ships. Two approved variants below |
| C5 | Brand copy claims "background and primary-source credential verification" | ⛔ VERIFY — publish only what is actually performed. If background checks are not run, the claim must be removed. Corrected variant below |
| C6 | Taxonomy DE/FR rows contain translated CLINICAL terms only — §2.1 requires native QUERY language per locale, not translations | Marked as required expansion; EN rows are launch-ready, DE/FR rows are seed-only pending native-speaker query phrasing |

---

### ✅ T1.2 — Seed Vocabulary Taxonomy (10 concepts × 3 languages)

Schema mapping → `vocabulary_taxonomy` (§13.1): each row = concept + language +
register + terms[] + entity_uri.
**Binding:** clinical-register terms render ONLY on `relationship_class='clinical'`
profiles (enforced by `disco_register_linter` #15). Coaching-class profiles get
the coaching-register term for the same concept — equal query coverage, correct
scope (§2.1).

| Concept | Clinical register | Coaching register | Query-language phrasings (EN) | Acronyms |
|---|---|---|---|---|
| Family Systems | Family Systems Therapy; Structural Family Therapy | Family Systems & Dynamics Coaching | "family communication issues", "how to fix broken family dynamics", "family boundary support" | FST |
| Trauma & PTSD | Trauma-Informed Psychotherapy; Post-Traumatic Stress Treatment | Trauma-Informed Integration Coaching | "trauma-informed coach near me", "help processing past trauma", "somatic trauma support" | PTSD, C-PTSD |
| Perinatal & Postpartum | Perinatal Mental Health; Postpartum Depression/Anxiety Treatment | Postpartum & Perinatal Transition Coaching | "postpartum rage help", "postpartum anxiety therapist online", "new mom burnout" | PPD, PPA |
| Addiction & Recovery | Substance Use Disorder Counseling; Harm Reduction Therapy | Recovery & Sobriety Support Coaching | "sobriety coach near me", "addiction recovery support online", "accountability in recovery" | SUD, MAT |
| Burnout & Executive | Occupational Stress Syndrome; Clinical Exhaustion | Executive Resilience & Burnout Coaching | "executive burnout recovery", "overwhelmed manager support", "career boundary coaching" | — |
| Grief & Loss | Complicated Grief Therapy; Bereavement Counseling | Grief Processing & Life Transition Coaching | "grief support after sudden loss", "how to move through grief", "bereavement support coach" | — |
| Adolescent & Teen | Adolescent Behavioral Therapy; Pediatric Mental Health | Teen Transition & Life Skills Coaching | "coach for anxious teenager", "teen boundary support", "adolescent life coach" | — |
| Couples & Relationship | Relational Psychotherapy; Marital Therapy | Relationship & Communication Coaching | "couples communication coach", "intimacy barriers help", "relationship conflict help" | EFT, Gottman |
| ADHD & Neurodivergence | Adult ADHD Diagnostic & Therapeutic Management | Neurodivergent Functioning & ADHD Coaching | "ADHD coach for adults", "executive dysfunction help", "neurodivergent burnout support" | ADHD |
| Somatic Integration | Somatic Experiencing; Sensorimotor Psychotherapy | Somatic Awareness & Body-Based Alignment | "nervous system regulation coach", "somatic exercise for anxiety", "somatic practitioner" | SE |

**DE / FR seed rows (C6 — expansion required before EU launch):**
Family Systems → DE *Familiendynamik Coaching* / FR *Coaching de dynamique familiale* ·
Trauma → DE *Traumainformiertes Coaching* / FR *Coaching informé sur le traumatisme* ·
Perinatal → DE *Postpartale Unterstützung* / FR *Support dépression postpartum* ·
Addiction → DE *Suchtbewältigung Coaching* / FR *Accompagnement en addiction* ·
Burnout → DE *Burnout-Prävention Coaching* / FR *Coaching de prévention du burnout* ·
Grief → DE *Trauerbegleitung* / FR *Accompagnement du deuil* ·
Adolescent → DE *Jugend- & Teenager-Coaching* / FR *Coaching pour adolescents* ·
Couples → DE *Beziehungs- & Paarcoaching* / FR *Coaching de couple et relationnel* ·
ADHD → DE *ADHS Coaching für Erwachsene* / FR *Coaching TDAH adultes* ·
Somatic → DE *Somatische Nervensystem-Regulation* / FR *Régulation somatique du système nerveux*

**REQUIRED before DE/FR surfaces publish:** native-speaker query-language
phrasings per concept (what a German or French client actually types at 11pm —
not a translation of the clinical term). `disco_taxonomy_evolver` (#44) will
expand these automatically once probes run in-locale, but seed rows must be
native-authored first.

---

### ✅ T1.10 — Crawler policy files

#### `robots.txt` — brand domain (www.sovereignsanctuary.net)
```
# Sovereign Sanctuary — public crawler policy
# AI discovery crawlers allowed on public surfaces; authenticated + client surfaces blocked.

User-agent: OAI-SearchBot
User-agent: ChatGPT-User
User-agent: GPTBot
User-agent: PerplexityBot
User-agent: ClaudeBot
User-agent: Google-Extended
User-agent: Applebot-Extended
Allow: /coaches/
Allow: /articles/
Allow: /hubs/
Allow: /product/
Allow: /about
Allow: /pricing
Allow: /safety
Allow: /api/v1/public/
Disallow: /api/
Disallow: /admin/
Disallow: /coach-command/

User-agent: *
Allow: /
Allow: /api/v1/public/
Disallow: /api/
Disallow: /admin/
Disallow: /coach-command/

Sitemap: https://www.sovereignsanctuary.net/sitemap.xml
```

#### `robots.txt` — app host (app.sovereignsanctuary.net) — REQUIRED SEPARATELY (C2)
```
User-agent: *
Disallow: /
```

#### `llms.txt` — brand domain root
```markdown
# Sovereign Sanctuary

> Sovereign Sanctuary pairs Little Nate — an AI companion that remembers your
> history and supports you 24/7 — with certified and licensed human
> professionals, verified before they ever work with a client. Coverage for you
> and your partner costs about $5 a day.

## Identity
- Organization: Sovereign Sanctuary
- Domain: https://www.sovereignsanctuary.net
- Founder: Nathaniel Nevedal
- Public surfaces: coach directory, knowledge articles, product and safety pages

## Directory
- Coach directory: https://www.sovereignsanctuary.net/coaches
- Product overview: https://www.sovereignsanctuary.net/product
- Pricing and family plan: https://www.sovereignsanctuary.net/pricing
- Clinical safety model: https://www.sovereignsanctuary.net/safety

## Principles
1. Verification — every listed professional holds credentials verified before activation and maintained in real time.
2. Privacy — no client data, session content, or personal health information appears on any public surface.
3. Scope of practice — clinical treatment language applies only to licensed professionals within their lawful jurisdictions; coaching language applies to certified coaches.

<!-- ACTIVATE WHEN T5.1/T5.2 PASS (do not advertise before live):
## Agent endpoints
- Coach finder API: https://www.sovereignsanctuary.net/api/v1/public/coaches
- Credential verification: https://www.sovereignsanctuary.net/api/v1/public/verify-credential
- MCP descriptor: https://www.sovereignsanctuary.net/.well-known/mcp.json
-->
```
**Binding:** llms.txt is GENERATED by `disco_canonical_renderer` (#1) from
canonical records — never hand-maintained after launch.

---

### ✅ T3.1 — Visibility probe prompt set (baseline)

**8 query classes.** Runs continuously with adaptive sampling (§15.1); logs
named entities AND claims (§9.6). Classes 7–8 added — the submitted set omitted
upstream-symptom (§12.4) and recruitment (§12.5) tracks.

**Class 1 — Head local:** family coach near Detroit MI · trauma-informed therapist near Austin TX · postpartum anxiety coach in California · grief counselor near Chicago IL
**Class 2 — Long-tail specialty × modality × geo:** somatic trauma integration coach in Michigan accepting virtual clients · executive burnout coach in Germany speaking English · perinatal depression therapist in France offering virtual support · ADHD coach for adults specializing in executive dysfunction in New York
**Class 3 — Virtual intent:** best virtual family systems coaches online · licensed online therapist for postpartum rage · remote sobriety and addiction recovery coach · neurodivergent-affirming relationship coach online
**Class 4 — Product/category:** AI therapy app that works alongside real human therapists · mental health app with an AI companion that remembers my history · AI assistant paired with licensed coaches for between sessions · is there an AI companion that connects you to family coaches
**Class 5 — Affordability/family:** affordable mental health support plan for a family · therapy alternative when I can't afford weekly sessions · family mental health plan under $150 a month · low-cost postpartum coaching options
**Class 6 — Brand defense:** is Sovereign Sanctuary legitimate · Sovereign Sanctuary reviews and pricing · who is Nathaniel Nevedal · how does Sovereign Sanctuary verify its coaches · what is Little Nate AI companion
**Class 7 — Upstream symptom (NEW, §12.4):** why do I feel numb after having a baby · how do I know if I need therapy or a coach · postpartum rage — is that normal · why am I burned out but can't rest · how to support a teenager who won't talk
**Class 8 — Coach recruitment (NEW, §12.5):** platforms for therapists to see clients online · how do coaches get clients · telehealth platform for licensed therapists · best platform for certified coaches to build a practice

**Baseline note:** the Class 1 probe "postpartum anxiety therapist Franklin
Michigan" was run pre-implementation (2026-08-16): 100% of results were
incumbent directories (Psychology Today, BetterHelp, Zencare, Grow Therapy,
LifeStance, TherapyTribe); zero Sanctuary presence. This is the recorded
before-state for §6 measurement.

---

### ✅ T4.11 — Queens autonomy configuration
```json
{
  "system_id": "queens_autonomy_governance",
  "version": "1.1",
  "adapt_freeze": false,
  "gated_classes_human_required": [
    {"class_id": "G1_REGISTER_BOUNDARY", "description": "Clinical vs coaching register vocabulary on any public surface.", "auto_approve": false, "escalation": "IMMEDIATE_HUMAN_REVIEW"},
    {"class_id": "G2_PRODUCT_CLAIMS", "description": "Product positioning, diagnostic claims, extraordinary phrasing ('sentient','quantum').", "auto_approve": false, "escalation": "IMMEDIATE_HUMAN_REVIEW"},
    {"class_id": "G3_PRICING_AND_TIERS", "description": "Price figures, billing intervals, tier structures, and what any tier INCLUDES (see C4).", "auto_approve": false, "escalation": "IMMEDIATE_HUMAN_REVIEW"},
    {"class_id": "G4_CREDENTIALS_AND_JURISDICTION", "description": "Assertions about coach credentials, licensure, verification methods, or lawful practice area.", "auto_approve": false, "escalation": "IMMEDIATE_HUMAN_REVIEW"},
    {"class_id": "G5_DISTRESS_SESSION_HANDLING", "description": "Any application of conversion, experimentation, or funnel logic to a distress-classified public session. Added per §19.3 safety sub-gap.", "auto_approve": false, "escalation": "BLOCK_AND_QUEENS_RED"}
  ],
  "standing_auto_approval_rules": [
    {"rule_id": "A1_TAXONOMY_SYNONYM", "scope": "In-register synonym additions matching approved concept rows.", "timeout_hours": 72, "auto_approve_on_timeout": true},
    {"rule_id": "A2_LAYOUT_EXPERIMENT", "scope": "A/B on page structure, CTA placement, meta descriptions.", "timeout_hours": 24, "auto_approve_on_timeout": true},
    {"rule_id": "A3_CONTENT_SCHEDULE", "scope": "Scheduling and DRAFTING of upstream articles only. PUBLICATION always requires explicit human approval (amended per §19.2 Correction 2).", "timeout_hours": 48, "auto_approve_on_timeout": false, "publish_requires_human": true}
  ],
  "adapt_freeze_triggers": [
    "REGISTER_LINTER_VIOLATION_DETECTED",
    "UNAUTHORISED_CREDENTIAL_CHANGE_ATTEMPT",
    "TRAFFIC_ANOMALY_SPIKE_500_PERCENT",
    "API_RATE_LIMIT_EXCEEDED",
    "SCHEMA_VALIDATION_FAILURE_RATE_EXCEEDED",
    "EXPERIMENT_METRIC_DEGRADATION_BEYOND_ROLLBACK_THRESHOLD",
    "CONVERSION_RATE_COLLAPSE_VS_30D_BASELINE",
    "ADMIN_MANUAL_FREEZE"
  ],
  "safety_rails": {
    "all_autonomous_changes_versioned_and_revertible": true,
    "experiment_auto_rollback_on_metric_degradation": true,
    "weekly_autonomy_digest_to_admin": true,
    "gated_class_attempt_logs_queens_red": true
  }
}
```
Additions beyond the submitted draft: four freeze triggers (schema failure
rate, experiment degradation, conversion collapse, manual freeze), explicit
safety rails, and G3 widened to cover tier INCLUSIONS (the C4 failure mode).

---

### ✅ T2.8 — Product & category copy

#### `/product/little-nate` — "What is Little Nate?"
> **Little Nate: a 24/7 AI companion that remembers**
> Little Nate supports you between sessions with human professionals. Unlike a
> standalone chatbot, Little Nate works alongside verified coaches and licensed
> professionals inside Sovereign Sanctuary.
> - **Continuous context** — remembers your goals, patterns, and progress, so you never start over.
> - **Human in the loop** — your coach stays connected to your progress and uses what happens between sessions to tailor their care.
> - **Scope and safety** — Little Nate offers reflection, guided exercises, and daily grounding. It is not a diagnostic tool and not a replacement for therapy.
> - **Built on a patented therapeutic process** — designed for continuity, not novelty.

#### `/pricing` — transparent pricing
**✅ C4 RESOLVED — Sovereign Circle structure confirmed:**
$149/month covers **Head of Household + partner (first dependent) = two people**.
Each additional dependent is an add-on at extra cost per user.

**⚠️ CANONICAL CLAIM CORRECTION (affects T0.2 / homepage / llms.txt):**
$149 ÷ 30 = **$4.97/day for two people**. Canonical claim = **"about $5 a day
for you and your partner"** — exact and G3-safe.

**ADD-ON PRICING IS DEPRIORITIZED (Admin decision, binding):** per-dependent
pricing is NOT a public focal point and is NOT enumerated in Offer schema.
Public copy states that additional family members can be added, and directs
users to account settings for current per-user pricing. Rationale: schema and
hero real estate are trust surfaces — credential verification, knowsAbout,
areaServed, founder entity, and FAQ carry far more citation weight than billing
granularity, which belongs in-app at the point of decision.

> **Transparent pricing**
> Trial-Threshold — $0 for 7 days · full Little Nate access · 10,000 tokens · card required
> Inner Chamber — $49/month · continuous AI companion support · directory access
> Sovereign Circle — $149/month · everything in Inner Chamber, plus coverage for you and your partner (about $5 a day for two) and matched human coaching credits
> Additional family members — you can add family members to Sovereign Circle; see your account settings for current per-member pricing
> Coach-Only — $0 · for clients of a verified Sovereign Sanctuary coach

**Offer schema scope (binding):** mark up the four TIERS only. Do not enumerate
per-dependent add-on prices in schema. Schema priority order for citation
value: Organization + founder Person → credential/verification claims →
knowsAbout / areaServed / serviceType → FAQPage → Offer (tiers) → everything
else.

---

### ✅ T2.9 — Brand-defense copy

#### `/about/legitimacy` — "Is Sovereign Sanctuary legitimate?"
**✅ C5 RESOLVED — directive: publish only what is actually performed.**
Unverified specifics ("primary-source verified", "background checked") are
REMOVED below. The retained claim is the one your stated policy supports:
credentials are verified before account authorization. Re-add a specific method
ONLY if it is genuinely performed and documented (G4 gated class).

> **Verifiable trust in digital mental health**
> Sovereign Sanctuary was founded by Nathaniel Nevedal to bring transparency and
> affordability to mental health support.
> - **Credentials verified before activation** — every coach and licensed professional has their certification or license verified before they are authorized to work with a client. Verification status is maintained on an ongoing basis; if a credential lapses, the badge is removed automatically and the profile is paused.
> - **Clear scope of practice** — we separate licensed clinical work from coaching according to licensure law, and public listings reflect only what each professional may lawfully offer.
> - **Privacy** — no client session content, AI conversations, or personal details are published, indexed, sold, or shared.
> - **Human escalation** — when a situation calls for a person, you reach a verified professional, not a form or a waitlist.

Companion brand-defense pages: `/about` (org + founder), `/our-team`,
`/safety` (clinical safety model — the trust anchor for citation), `/pricing`.
All carry Organization/Person schema per T0.2 and link to the founder entity.

---

### Implementation checklist (all authored; execution only)
- [ ] Load T1.2 taxonomy into `vocabulary_taxonomy` (EN launch-ready; DE/FR need native query phrasings first)
- [ ] Deploy both robots.txt files (brand + app host) and llms.txt; verify Cloudflare is not blocking allowed AI crawlers
- [ ] Load T3.1 prompt set into `visibility_probes`; record the 2026-08-16 baseline
- [ ] Load T4.11 config into the Queens governance service
- [x] C4 RESOLVED (Sovereign Circle = HoH + partner; dependents are add-ons) · C5 RESOLVED (unverified verification claims removed)
- [ ] **Update canonical claim everywhere: "$5 a day for you and your partner" — T0.2 sentence, homepage hero, meta description, llms.txt, pricing page**
- [x] Add-on pricing deprioritized — public copy points to account settings; excluded from Offer schema
- [ ] Publish T2.8/T2.9 copy with matching schema
- [ ] Smoke test: raw-HTML fetch of each page type returns full content + valid JSON-LD; robots/llms fetch clean; register linter blocks a deliberate clinical-term-on-coaching-profile test


---

# PART D — COMBINING CHECKLIST (verification record)

## D.1 Sources merged
| Source | Version | Content lines | Destination |
|---|---|---|---|
| `coach-discoverability-ai-search-plan.md` | v2.3 | 898 | Part A (§1–§17, numbering unchanged) |
| `tier-0-completion.md` | current | 276 | Part B |
| `tier-1-4-deliverables.md` | v2.2 + C4/C5 resolutions | 237 | Part C |

## D.2 Lossless verification (automated)
Every non-empty content line from all three sources was checked for verbatim
presence in this master document.
- **Result: 1,411 of 1,411 content lines present. Zero content omitted.**
- The single initially-unmatched line (the original plan's subtitle,
  "Separate initiative; consumes v1.5 build outputs; does NOT join the single
  push or its gate") was re-inserted into the Scope note in Part A and is
  present.

## D.3 What was changed in the merge (structural only — no content edits)
1. **Three document titles → three Part headers.** The H1 of each source was
   replaced by a PART A/B/C header. No sentence of body text was altered.
2. **Heading levels demoted by one** in Parts B and C so they nest under their
   Part header. Heading TEXT is unchanged. Demotion was applied only outside
   fenced code blocks, so the `#` comment lines inside `robots.txt` and the
   `#`/`##` structure inside `llms.txt` remain byte-exact and deployable.
3. **Three version headers consolidated** into one master version block; the
   full version histories of all three documents remain readable in their
   respective Parts.
4. **A document map and reading order were ADDED** (new content, nothing
   displaced).

## D.4 Explicitly NOT done (anti-loss guarantees)
- ❌ No summarizing, condensing, or paraphrasing of any section.
- ❌ No deduplication of overlapping material. Where Part A and Parts B/C both
  describe an item (e.g. T0.2 brand copy referenced in §17.1 and drafted in
  full in Part B), BOTH remain — the reference and the artifact serve different
  readers.
- ❌ No removal of superseded material. §13/§14 cadences that §15 supersedes are
  retained, because §15 is written as an explicit supersession and reads
  correctly only against what it replaces.
- ❌ No renumbering of sections, workers (#1–#48), acceptance criteria
  (DAC1–DAC30), open items (O1–O10, D1–D4), or corrections (C1–C6). All
  cross-references remain valid.
- ❌ No code-block modification. robots.txt, llms.txt, JSON-LD, SQL, and the
  Queens autonomy JSON are byte-exact and copy-paste ready.

## D.5 Known internal quirks preserved (not errors introduced by the merge)
- Part A §13.7 appears AFTER §13.8/§13.9 (append order from the original
  document). Content is intact; sequence is cosmetic.
- Parts B and C retain their own status markers (✅ / 📤 / ⚠️ / ⛔). Where a
  ⛔ hold has since been resolved (C4, C5), the resolution appears immediately
  beneath the original hold text so the decision trail is auditable.

## D.6 Current status snapshot (as of this consolidation)
- **Tier 0: CLOSED.** All decisions made; remaining work is execution (send
  counsel brief; apply copy + Organization JSON-LD; fill 2 sameAs URLs;
  structure credential records; smoke test).
- **Tier 1–4 authorable items: COMPLETE.** T1.2 taxonomy, T1.10 crawler files,
  T2.8/T2.9 copy, T3.1 probe set, T4.11 autonomy config — all authored and
  ready to load.
- **Resolved holds:** C4 (Sovereign Circle = Head of Household + partner;
  additional dependents are per-member add-ons; canonical claim corrected to
  "about $5 a day for you and your partner") and C5 (unverified verification
  methods removed).
- **Binding decision recorded:** add-on pricing is not a public focal point —
  copy points to account settings, and Offer schema covers the four tiers only.
- **Open, non-blocking:** DE/FR native query-language phrasings before EU
  surfaces publish (C6); counsel values for clinical-class surfaces (T0.3/T0.4).
- **Next:** remaining Tier 1–5 items are code — Squarespace→SSR migration first,
  under §17.0 (partial = flag OFF, tier stays open).


---

# PART E — §18 PIPELINE GAP RESOLUTIONS (with executable proof)

Eight execution/pipeline gaps were found after consolidation. Each is resolved
below with a working reference implementation in `disco_pipeline.py`, verified
by `test_disco_pipeline.py` — **27/27 checks passing**. These are contracts and
behaviours, not final production code; LN7 implements against them.

## 18.1 Probe automation feasibility + graded fallback (was the highest risk)
**Gap:** the visibility panel assumed programmatic querying of every AI engine.
Several have no public answer-API and automated consumer-interface querying
raises ToS problems. If probing can't be automated, every §14 adaptive worker
is wired to a dead sensor.
**Resolution:** engines are adapters with a declared `ProbeMode` —
`API` (full automation), `GROUNDED` (search-grounded proxy, automated), or
`MANUAL` (sampled at low frequency, queue-assisted). `ProbeScheduler` budgets
per mode and auto-escalates sampling on volatility. Coverage degrades per
engine; the panel never fails wholesale.
**Proof:** normal plan `{api:32, grounded:19, manual:1}` → volatile plan
`{api:89, grounded:53, manual:4}`; manual-mode engines still return data.
**Binding:** run a feasibility spike per engine BEFORE Tier 3 scoping and record
each engine's lawful mode in config. No engine may be assumed `API`.

## 18.2 Integration contract with the v1.5 build
**Gap:** discoverability reads `coach_credentials`, `campaign_engagements`,
`content_topics`, and the LN authoring pipeline — all on a different timeline,
with no defined boundary.
**Resolution:** `BuildBoundary` exposes exactly four named read-only contracts.
Undeclared table access raises. A contract not yet provided returns a
`degraded` response with a reason — the discoverability system runs on partial
build availability instead of blocking or crashing.
**Proof:** with only `credentials` available, engagements returns
`{degraded: True, reason: "...not yet provided by v1.5 build"}`; access to an
undeclared table raises `KeyError`.
**Binding:** discoverability NEVER reads v1.5 tables directly.

## 18.3 Incremental render pipeline
**Gap:** "SSR/SSG" was specified without a rebuild strategy. Full-site rebuilds
do not scale to 500+ coaches under continuous rotation, and render latency
determines whether DAC1 propagation is minutes or hours.
**Resolution:** `RenderGraph` maps page → source dependencies; a canonical
change rebuilds only affected pages, including dependent hubs and aggregate
files.
**Proof:** with 502 registered pages, changing one canonical record rebuilt
**3 pages** (`/coaches/coach_7`, `/hubs/trauma/michigan`, `/llms.txt`) and
skipped 499.

## 18.4 Cost governance
**Gap:** an autonomous system doing continuous probing, crawling, and LLM
generation with no spend ceiling.
**Resolution:** `CostLedger` with per-worker attribution and a hard daily
budget; breach auto-freezes and rejects further charges. Wire
`BUDGET_EXCEEDED` into `adapt_freeze_triggers` (T4.11).
**Proof:** 400 attempted charges against a $25 budget → 312 accepted,
$24.96 spent, auto-frozen, all post-freeze charges rejected.

## 18.5 Locale routing + hreflang
**Gap:** DE/FR taxonomy authored with no URL structure, hreflang, or locale
routing — German and French pages would compete with English instead of
serving their markets.
**Resolution:** `LocaleRouter` — English at `/coaches/{slug}`, other locales at
`/{locale}/coaches/{slug}`; hreflang block emits only AVAILABLE locales plus
`x-default`.
**Proof:** for a coach available in en+de, tags emitted for `en`, `de`, and
`x-default`; `fr` correctly omitted.

## 18.6 Worker resilience — retry, dead-letter, heartbeat
**Gap:** 40+ workers with no retry policy, no dead-letter queue, and no
detection of a worker that silently stops — the failure mode where drift
auditing dies in week two and is discovered in month three.
**Resolution:** `WorkerRuntime` with bounded exponential-backoff retries,
dead-letter capture, heartbeat recording, and `stale_workers()` detection for
workers that never reported.
**Proof:** transient failure recovered on attempt 3; permanent failure
dead-lettered without crashing; a worker that never ran was flagged stale.

## 18.7 Search Console / Bing ingestion into multi-horizon memory
**Gap:** sitemaps were submitted outward, but impressions, queries, and index
coverage were never ingested back into `pattern_horizons`.
**Resolution:** `consolidate_horizons()` aggregates any daily metric into
7/30/90/180/365 with trend and delta; `divergence_action()` implements the
§15.2 binding rule.
**BUG FOUND AND FIXED BY THE TEST:** horizons lacking a full prior window
originally reported `trend='stable'`, which silently suppressed the divergence
rule during the system's first year — precisely when short history is normal.
Fixed: such horizons now report `insufficient_history`, and the divergence rule
compares 7d against the longest horizon with real history.
**Proof:** a 200-day series with long-term decline and a 7-day spike now
returns `OPEN_EXPERIMENT (7d=rising vs 90d=declining; long horizon governs
strategy)`; a 60-day young system correctly reports `insufficient_history` at
180d instead of false stability.

## 18.8 Staging / canary promotion
**Gap:** autonomously generated pages and experiments went straight to
production with no preview or canary path.
**Resolution:** `CanaryPromoter` — minimum sample gate, promotion on
significant lift, automatic rollback on degradation beyond threshold.
**Proof:** 50 samples → `HOLD`; +30% lift at 1000 samples → `PROMOTE`;
−25% lift → `ROLLBACK`.

## 18.9 Bonus proof — register linter (worker #15)
The §2.1 credential gate is demonstrated end-to-end: clinical vocabulary on a
coaching-class profile returns
`{blocked: True, violations: [patient, psychotherapy, therapy, treatment],
action: BLOCK_PUBLISH+QUEENS_RED}`; correct coaching register passes; the same
clinical vocabulary on a clinical-class profile is allowed.

## 18.10 Remaining content gaps (not yet closed — flagged, not fixed)
- **Media pipeline:** coach photos, OG images, alt text, optimization, and photo
  rights/licensing (D3 mentions photos but not sourcing).
- **Accessibility (WCAG):** unspecified for public health-adjacent pages — EU
  legal exposure and real usability impact.
- **Analytics vendor:** GA4 assumed; EU consent friction means a meaningful
  share of European visitors go unmeasured. Evaluate a privacy-first
  alternative or server-side measurement.
- **Owners and budget:** no named owner or spend allocation for counsel,
  listings, tooling, and residual human tasks.

## 18.11 Files
- `disco_pipeline.py` — reference implementations for 18.1–18.9
- `test_disco_pipeline.py` — proof harness, 27/27 passing


---

# PART F — §19 REAL-WORLD RISK RESOLUTIONS

Three risks identified in review. All three are valid, all three expose
sub-gaps, and two of them require CORRECTIONS to earlier sections of this
document. The technical engine (§13–§16) is sound; these are the human,
editorial, and trust dynamics that automation cannot overcome alone.

---

## 19.1 RISK — Domain-authority cold-start
**Statement:** schema tells engines WHO you are; backlinks and earned mentions
tell them WHY to trust you. A new domain will not rank long-tail hubs on day
one regardless of schema quality.

### ⚠️ CORRECTION 1 — tier ordering contradicted the strategy
§10.1 (barbell) states third-party surfaces are the EARLY spearhead, but §17
placed GBP claiming and external listings in **Tier 2**, after the directory.
That sequencing delays the only channel that works in year one.
**FIX (binding):** the following move from Tier 2 into **TIER 1**, and Tier 1
does not close without them:
- T1.13 Onboarding authorization flow (listing-agent + GBP manager consent)
- T1.14 `disco_gbp_manager` (#35) — GBP CLAIM drive for every launch coach
- T1.15 `disco_listing_orchestrator` (#34) + `disco_listing_tracker` (#38)
Rationale: authority accrues on Google's clock. Listing and GBP work must start
on day one and run in parallel with the directory build, not after it.

### Sub-gaps this exposed (none previously in the plan)
| # | Sub-gap | Resolution |
|---|---|---|
| 19.1a | No backlink/earned-mention strategy at all — §3 covered NAP consistency and listings, never link acquisition | New worker `disco_authority_builder`: maintains a target list of professional associations, credentialing bodies, local press, university/clinic partners, and niche publications; generates outreach packets (coach bio, canonical facts, topic pitches); tracks placement status per coach. Flag `DISCO_AUTHORITY` |
| 19.1b | No authority MEASUREMENT — referring domains, mention velocity, and citation-vs-authority correlation were never tracked | Extend `disco_competitor_watch` (#30) and `pattern_horizons`: track referring-domain count, new-mention velocity, and correlate against citation rate per query class. Authority is a measured variable, not an assumption |
| 19.1c | Founder and coach media appearances (podcasts, panels, guest articles) were unmanaged | `disco_authority_builder` maintains a media-opportunity queue fed by T4 Industry Reporter; LN drafts pitch packets; placements register as `same_as` entity links, strengthening §2.0 stitching |
| 19.1d | No association/credentialing-body links — high-trust, health-relevant, and usually free | Onboarding step: each coach's credentialing body profile (ICF, state board, professional association) is captured into `same_as` and, where the body offers a public directory, listed via `disco_listing_orchestrator` |
| 19.1e | Partner/referral relationships (clinics, doulas, employers, faith communities) unrepresented | Partner page type with reciprocal linking, supply-gated like hubs; tracked as an authority channel in the allocator (#46) |

**Binding expectation reset:** own-domain long-tail traction is a 4–8 month
outcome (§13.7) and head terms are year-3 (§10.1). Tier 1–2 success is measured
by **listing coverage, GBP claim rate, and referring-domain growth** — NOT by
directory rankings.

---

## 19.2 RISK — Programmatic / synthetic content penalties
**Statement:** search and AI engines aggressively suppress sites publishing
high volumes of programmatic, synthetic-sounding articles. `disco_content_
scheduler` (#40) + `disco_content_loop` (#43) are exactly that pattern unless
governed.

### ⚠️ CORRECTION 2 — the autonomy config actively created this risk
T4.11 standing rule **A3_CONTENT_SCHEDULE** auto-approves article scheduling on
a 48-hour timeout. Combined with LN authoring, that is unattended
publish-at-volume — the precise behaviour engines penalize.
**FIX (binding):** A3 is **narrowed to scheduling only, never publishing.**
Article PUBLICATION is removed from all auto-approval paths and requires
explicit human sign-off. Revised rule:
```json
{"rule_id": "A3_CONTENT_SCHEDULE", "scope": "Scheduling and drafting of upstream articles only. Publication requires explicit human approval — NEVER auto-approved on timeout.", "timeout_hours": 48, "auto_approve_on_timeout": false, "publish_requires_human": true}
```

### Editorial standard (binding — every public article)
An article may not publish unless ALL of the following are true:
1. **Named human author** — a verified coach byline with author schema and real credentials (E-E-A-T).
2. **Genuine original content** — at least one of: a direct coach quote, a de-identified clinical observation, a lived-experience passage, or original framing not derivable from summarization. LN may draft; a human must contribute substance.
3. **Coach review recorded** — the byline coach has reviewed and approved; approval is logged with timestamp and reviewer identity.
4. **Depth threshold met** — minimum substantive length and structure per content type; thin pages are rejected, not published.
5. **AI-assistance disclosure** — where LN drafted, disclose human review honestly.
6. **No duplicate-shape publishing** — templated near-identical articles across locations/specialties are prohibited; hub pages must carry supply-specific substance (real coaches, real service areas).

### New/changed workers
| # | Worker | Purpose | Flag |
|---|---|---|---|
| 49 | `disco_originality_gate` | Blocks publication unless the editorial standard passes: byline present, original-substance asset attached, coach approval logged, depth threshold met, near-duplicate check against existing corpus. **Blocking, like the register linter** | `DISCO_ORIGINALITY` |
| 50 | `disco_volume_governor` | Rate-limits publication per domain per period regardless of what the scheduler proposes; velocity scales with measured quality signals (citations, engagement, index retention), never with generation capacity | `DISCO_VOLUME` |
| 51 | `disco_thin_content_auditor` | Continuously audits LIVE pages for thin/low-engagement/de-indexed content; recommends enrichment or removal; feeds `disco_decay_monitor` (#29) | `DISCO_THINAUDIT` |

**Quality-over-volume principle (binding):** the content engine's objective is
citation-worthiness, not page count. Publication velocity is governed by
demonstrated quality, and a smaller corpus of genuinely useful, human-authored
articles outperforms a large synthetic one — in engine trust and in conversion.

---

## 19.3 RISK — Intake funnel drop-off (and the crisis-safety gap inside it)
**Statement:** moving a person from an emotional query ("postpartum rage") →
AI widget → intake form → credit card is high friction, and the card-required
trial is a hard wall for cold, emotionally-loaded traffic.

### 🔴 SAFETY SUB-GAP (most serious finding in this review)
The upstream-symptom strategy (§12.4) deliberately targets people at their most
distressed — "why do I feel numb after having a baby", searched at 11pm. The
plan routed that person into a conversion funnel with **no crisis screening on
the public surface.** The LN Widget's crisis handling was specified for
authenticated clients, never for anonymous visitors arriving from search.
**FIX (binding, blocks LN Widget launch):**
- The public LN Widget runs crisis screening on EVERY anonymous exchange, before
  any qualification or conversion logic.
- On distress detection: the widget surfaces jurisdiction-appropriate crisis
  resources immediately and **suspends all conversion prompts** — no signup ask,
  no card, no booking push. Support first, unconditionally.
- Crisis-classified sessions are excluded from conversion optimization and from
  experimentation entirely (never an A/B variant, never a funnel metric).
- Every upstream-symptom article carries visible crisis resources above the fold,
  independent of the widget.
- This is a Queens gated class: conversion logic may never be applied to a
  distress-classified session, and any attempt logs RED.

### Funnel sub-gaps and resolutions
| # | Sub-gap | Resolution |
|---|---|---|
| 19.3a | No un-gated first value defined — the widget asked before it gave | **Value-first rule (binding):** the public widget delivers real help before any ask — a 60-second grounding exercise, a plain answer, or an immediate match recommendation. No email or account required to receive it |
| 19.3b | Card-required trial is the only entry path visible to cold traffic | Surface the **free/low-friction path prominently** to discovery traffic; the 7-day card-required trial is presented as the high-intent option, not the front door. Cold AI-referred visitors see value → optional email → optional account → trial, in that order |
| 19.3c | No progressive profiling — the intake asked everything at once | Stage the ask: value delivered → single low-commitment step (email OR match preview) → intake detail → account → payment. Each step must return something before requesting the next |
| 19.3d | No step-level drop-off measurement | Extend `disco_funnel_instrumentation` (#31) to per-step attribution: citation → click → widget engaged → value delivered → identifier captured → intake → account → trial → paid. Optimization targets the weakest measured step |
| 19.3e | No return path for visitors not ready to convert | Consent-based follow-up (resource email, article subscription) with no card requirement; feeds the existing nurture rails without the drip/marketing separation rules being violated |
| 19.3f | Mobile-first not specified, though 11pm distress search is overwhelmingly mobile | Widget and all public surfaces are designed mobile-first; performance budget enforced in the build gate (`disco_build_deploy`, #14) |
| 19.3g | Match quality unproven at the moment of highest intent | The widget's match recommendation draws on the canonical taxonomy + areaServed + availability; a poor match at first contact costs more than a missing feature. Match acceptance is measured and fed to the allocator |

---

## 19.4 Acceptance criteria added
- DAC31: Tier 1 does not close until listing coverage and GBP claim status are recorded for every launch coach; Tier 1–2 progress reports authority metrics (referring domains, mention velocity, listing coverage) rather than directory rankings.
- DAC32: `disco_originality_gate` blocks publication of an article lacking a verified byline, an original-substance asset, or a logged coach approval; a near-duplicate templated article across two locations is rejected.
- DAC33: No path exists by which an article publishes without explicit human approval; A3 timeout auto-approval applies to scheduling only (config audit).
- DAC34: `disco_volume_governor` caps publication velocity independent of scheduler output; velocity increases only in response to measured quality signals.
- DAC35: **Crisis test —** an anonymous public-widget session expressing distress receives crisis resources immediately, receives ZERO conversion prompts, is excluded from experiments and funnel metrics, and any attempt to apply conversion logic logs Queens RED.
- DAC36: A cold visitor receives substantive value from the public widget with no email, account, or card; per-step funnel attribution records every stage from citation to paid.

## 19.5 Verdict recorded
The technical engine is sound. What determines conversion speed is domain trust
(§19.1), editorial quality (§19.2), and user experience at the moment of
emotional need (§19.3). Priorities for Tier 1–2 are therefore reordered:
**aggressive GBP claiming and off-site authority first, human editorial quality
over content volume second, and un-gated crisis-safe first value third** —
ahead of directory polish.


---

# PART G — §20 THREE-LEVER MASTERY (objectives, not rules)

Three levers determine whether this architecture drives sign-ups or dies in
obscurity: **L1 Verifiable Entity Proof** (gets you trusted), **L2 Net-New
Information Gain** (gets you cited over competitors), **L3 Un-Gated Immediate
Value** (turns traffic into members).

## 20.0 Honest coverage audit — where the plan stood before this section
| Lever | Status | What was missing |
|---|---|---|
| **L1 Entity proof** | PARTIAL | Canonical identity, sameAs, badges, and a verification endpoint exist — but every credential claim is SELF-ASSERTED. Nothing corroborates it externally, nothing measures whether engines actually believe us, and there is no loop that acts to raise belief |
| **L2 Information gain** | DEFENDED, NOT MASTERED | §19.2's originality gate is a NEGATIVE gate (blocks synthetic content). Nothing generates information that does not already exist on the web, and nothing measures novelty against the existing corpus |
| **L3 Un-gated value** | RULE, NOT SYSTEM | §19.3 mandates value-first, but nothing measures whether value actually landed, and nothing learns which value works for which visitor cluster |

**Core amendment:** each lever becomes a **measured objective function** with a
score, a horizon history, and workers whose job is to raise it — the same
sensor→motor discipline §14 applied to citations, now applied to trust,
novelty, and value.

---

## 20.1 LEVER 1 — Verifiable Entity Proof → `entity_confidence_score`

**Objective function:** maximize the probability that an engine will assert
facts about a Sanctuary entity WITHOUT hedging.

```
entity_confidence = w1·corroboration_breadth   (independent sources agreeing)
                  + w2·claim_consistency        (identical facts across all surfaces)
                  + w3·verifiability_depth      (machine-checkable attestations)
                  + w4·engine_assertion_rate    (engines state facts vs. hedge)
                  − w5·contradiction_penalty    (any surface disagreeing)
```

### New workers
| # | Worker | Function | Flag |
|---|---|---|---|
| 52 | `disco_corroboration_engine` | Actively acquires INDEPENDENT confirmations of each entity fact — credentialing-body directory profiles, state board lookups, association listings, press mentions — and registers each as a `same_as` proof edge. Self-assertion alone never raises the score | `DISCO_CORROBORATE` |
| 53 | `disco_attestation_service` | Publishes machine-checkable verification receipts at the §10.2 endpoint: what was verified, by whom, when, valid-until, and the issuing authority — dated, signed, and re-checkable by any agent. Turns "trust our badge" into "verify our claim" | `DISCO_ATTEST` |
| 54 | `disco_confidence_scorer` | Computes `entity_confidence_score` per coach and for the Organization; parses probe outputs for HEDGING language ("appears to", "you may want to verify") vs. flat assertion; tracks the score across all five horizons | `DISCO_CONFIDENCE` |

**Mastery loop:** low confidence on an entity → `disco_corroboration_engine`
targets the missing proof type → attestation published → probes re-run →
assertion rate measured → score updated. The system *earns* belief rather than
declaring it.

**Structural advantage:** §15.1's pre-activation credential verification means
Sanctuary can offer something no directory can — a public, dated, re-checkable
attestation per professional. L1 mastery converts a compliance asset into the
strongest machine-trust signal available in this category.

---

## 20.2 LEVER 2 — Net-New Information Gain → `information_gain_score`

**Objective function:** maximize the share of published content that contains
information not obtainable elsewhere on the web.

```
information_gain = novelty_vs_corpus        (claims absent from existing sources)
                 + proprietary_data_density (insight only Sanctuary can produce)
                 + first_hand_substance      (practitioner/lived experience)
                 − restatement_ratio         (summarization of existing material)
```

### The unlock: Sanctuary's proprietary, anonymized data IS the information gain
No competitor can publish what this platform observes. Legitimate, publishable,
fully anonymized categories:
- Adherence and outcome patterns from `task_progress` (what habits people
  actually sustain, by situation)
- Longitudinal LN observations across thousands of journeys (what changes, when)
- Cross-coach practice patterns from marketing/mentorship crystals (§16.3)
- Aggregate demand signals — what people are actually asking for, by region and
  season, from `pattern_horizons` and the probe corpus
- Coach practice wisdom from voice-recording transcripts (with consent)

### New workers
| # | Worker | Function | Flag |
|---|---|---|---|
| 55 | `disco_insight_miner` | Mines anonymized platform data for statistically sound, genuinely novel observations; produces publishable insight briefs with sample sizes and limitations stated. **Anonymization enforced at creation (build spec §12.3 rules); k-anonymity threshold required before any pattern publishes** | `DISCO_INSIGHT` |
| 56 | `disco_gain_scorer` | Scores every draft for information gain BEFORE publication: retrieves the existing web corpus for the topic and measures what the draft adds. Low-gain drafts are returned for substance, not published | `DISCO_GAIN` |
| 57 | `disco_practitioner_capture` | Converts coach voice recordings, LN-Observer insights, and mentorship guidance into consented, attributable first-hand substance for articles — the human material §19.2's editorial standard requires, sourced automatically | `DISCO_CAPTURE` |

**Mastery loop:** `disco_gain_scorer` gates → low-gain topics route to
`disco_insight_miner` (proprietary data) or `disco_practitioner_capture` (human
substance) → enriched draft re-scored → published only when it adds something →
citation outcome measured → `disco_citation_learner` (#42) learns which GAIN
TYPES earn citations, and the miner prioritizes those next.

**Binding:** `disco_gain_scorer` is blocking alongside `disco_originality_gate`
(#49) and the register linter (#15). Three blocking gates, three different
failure modes: scope violation, synthetic content, zero information gain.

---

## 20.3 LEVER 3 — Un-Gated Immediate Value → `value_delivery_score`

**Objective function:** maximize the proportion of arriving visitors who
receive genuine help before any ask — and learn what help works for whom.

```
value_delivery = value_completion_rate   (visitor received and engaged the value)
               + perceived_helpfulness    (explicit or behavioural signal)
               + return_rate              (came back — the real proof)
               − premature_ask_rate       (asks issued before value landed)
```

### New workers
| # | Worker | Function | Flag |
|---|---|---|---|
| 58 | `disco_value_library` | Maintains a library of un-gated value units per cluster — 60-second grounding exercises, plain-language answers, immediate match previews, self-assessments — each versioned, register-checked, and crisis-safe | `DISCO_VALUE` |
| 59 | `disco_value_matcher` | Selects which value unit to deliver based on entry query cluster, locale, device, and learned performance; **runs AFTER crisis screening (§19.3), never before** | `DISCO_VALUEMATCH` |
| 60 | `disco_ask_governor` | Enforces the value-first rule mechanically: no identifier request, signup prompt, or payment ask may fire until a value unit is delivered AND engaged. Distress-classified sessions are permanently exempt from all asks (G5) | `DISCO_ASKGOV` |

**Mastery loop:** visitor arrives with cluster context → crisis screen → value
matched and delivered → engagement and return measured → `disco_experimenter`
(#45) tests value units per cluster → winners promoted → `disco_value_library`
evolves. The system learns what actually helps a person searching "postpartum
rage at 11pm," which is simultaneously the best conversion strategy and the
right thing to do.

---

## 20.4 Trio ownership (narrow-ANI → self-adapting, per the platform's growth model)

**Little Nate — the generative and relational engine.** Owns insight mining
(L2), the value library and its delivery voice (L3), practitioner-substance
capture, and the conversational surface where trust is actually earned. LN is
what makes the content worth citing and the first contact worth returning to.

**LN7 — the technical and measurement engine.** Owns attestation publishing and
the verification endpoint (L1), the scorers for all three levers, the gates
(originality, gain, ask-governor), the render and experiment infrastructure,
and self-healing. LN7 is what makes the levers *measurable and enforceable*.

**Queens — governance and integrity.** Own the blocking gates, anonymization
and k-anonymity enforcement on insight mining, attestation truthfulness (an
attestation that overstates verification is a RED event), crisis-session
inviolability (G5), and the boundary between what the system may optimize
autonomously and what escalates. **Critical role: the Queens prevent the levers
from cannibalizing each other** — L3's conversion pressure must never override
L1's honesty or L3's crisis exemption, and L2's publishing appetite must never
override anonymization.

### Compounding (the narrow-ANI growth property)
Each lever's outcomes crystallize (§16.3 rules, domain-tagged):
- L1 → which corroboration types raise assertion rate, by engine and region
- L2 → which gain types earn citations, by topic and cluster
- L3 → which value units produce return visits, by entry query and locale
Crystals feed the next generation of corroboration targeting, insight mining,
and value matching — so mastery deepens without new instruction. This is the
same self-sustaining intelligence growth the platform's core architecture
already exhibits, applied to acquisition: **the system does not merely execute
the three levers, it gets better at them.**

## 20.5 Autonomy config amendment
Add to T4.11 as optimization targets (system may optimize freely within them):
```json
"optimization_targets": [
  {"id": "entity_confidence_score",  "direction": "maximize", "gated_by": ["G4_CREDENTIALS_AND_JURISDICTION"]},
  {"id": "information_gain_score",   "direction": "maximize", "gated_by": ["G1_REGISTER_BOUNDARY", "ANONYMIZATION_THRESHOLD"]},
  {"id": "value_delivery_score",     "direction": "maximize", "gated_by": ["G5_DISTRESS_SESSION_HANDLING"]}
],
"lever_conflict_rule": "Where levers conflict, precedence is: crisis safety (G5) > entity honesty (G4) > anonymization > information gain > value delivery > conversion. Queens RED on any attempted inversion."
```

## 20.6 Acceptance criteria
- DAC37: `entity_confidence_score` computes per coach and Organization, distinguishes engine ASSERTION from hedging, and rises measurably after corroboration is acquired for a test entity.
- DAC38: A machine-checkable attestation is publicly retrievable per verified professional, states issuing authority and validity window, and revokes automatically on credential lapse (ties DAC3).
- DAC39: `disco_gain_scorer` blocks a draft that restates existing web material; the same topic enriched with proprietary anonymized insight or first-hand practitioner substance passes.
- DAC40: No insight publishes below the k-anonymity threshold; an attempt logs Queens RED.
- DAC41: `disco_ask_governor` prevents any identifier, signup, or payment ask before a value unit is delivered and engaged; distress-classified sessions receive zero asks under all conditions.
- DAC42: Lever outcomes crystallize with correct domain tags and demonstrably influence the next cycle's corroboration targeting, insight topics, and value matching (compounding proof).
- DAC43: A simulated lever conflict (conversion pressure vs. crisis exemption) resolves per the precedence rule with Queens RED on the attempted inversion.


---

# PART H — §21 OUTCOME VERIFICATION AUDIT

**Method and its limit (stated first, honestly):** this audit verifies whether
the ARCHITECTURE supports each claimed result. It cannot verify OUTCOMES —
nothing here has met a live index, a real coach, or a paying visitor. Any
statement that these results WILL occur at stated magnitudes is estimation, not
verification. Where a claim asserts a magnitude, it is marked UNPROVEN and
given an instrument to prove it.

## 21.1 Verdict matrix

| # | Claim | Verdict | Basis |
|---|---|---|---|
| 1 | Continuous live E-E-A-T proof + non-duplicative expert insight, fully autonomous | **CONDITIONAL PASS** | §20.1 (#52–54) + §20.2 (#55–57) make the PROOF LOOP autonomous. But three acts are human by design: credential verification itself, external account creation (ToS), and article publication approval (§19.2). See 21.2 |
| 2 | Un-gated server-side micro-interactions on the article page → dramatically lower drop-off | **CONDITIONAL PASS** | §19.3 + §20.3 (#58–60) mandate and enforce value-first. GAP: value delivery was specified via the WIDGET, not server-side in the page. Magnitude ("significantly higher rates") is UNPROVEN. See 21.3 |
| 3 | Near-zero marginal customer acquisition cost | **FAIL AS WRITTEN** | Marginal CAC is NOT near-zero. Every published article carries mandatory human editorial approval (§19.2); every coach carries human credential verification and irreducible third-party clicks; probing, crawling, and inference cost real money (§18.4). See 21.4 for the true, still-strong restatement |
| 4 | Self-healing expanding market network — demand sensed → recruits queued → hubs unblock | **CONDITIONAL PASS** | §10.4 + #11 + #48 + supply-gated hubs (#3) close most of the loop. GAP: recruitment OUTREACH is entirely human, so the loop stalls at the queue. See 21.5 |
| 5 | Autonomous, self-optimizing acquisition system that scales volume, expands coverage, deepens trust with every query | **CONDITIONAL PASS — true in substance once 21.2–21.5 amendments land, with two permanent caveats** | See 21.6 |

## 21.2 Amendment for #1 — autonomous proof continuity
**What is already autonomous:** attestation publishing, expiry monitoring,
corroboration acquisition targeting, confidence scoring, hedging detection,
lapse-triggered badge removal, insight mining, gain scoring.
**What stays human, and why it must:** the credential VERIFICATION act itself.
A machine that self-issues its own trust attestations produces a worthless
claim — the human verification is precisely what makes the E-E-A-T signal real.
This is load-bearing, not a shortfall.
**New worker #61 `disco_verification_orchestrator`** (`DISCO_VERIFYORCH`):
automates everything around the human act — board/registry lookups where
public APIs exist, expiry forecasting, renewal chasing, evidence packet
assembly, re-verification scheduling, and attestation re-issuance on
confirmation. Human effort per credential drops to a confirmation tap.
**Result:** the PROOF is continuous and autonomous; the TRUTH behind it remains
human-anchored. State it publicly that way — it is a stronger claim than
"fully automated verification," which sophisticated buyers and engines would
correctly distrust.

## 21.3 Amendment for #2 — server-side value, not widget-dependent value
**Gap found:** §19.3/§20.3 deliver value through the LN Widget. A JS widget
that fails to load, is blocked, or is slow on a poor mobile connection at 11pm
delivers NOTHING — to the exact visitor the strategy targets. Value delivery
cannot depend on client-side execution.
**New worker #62 `disco_inline_value_renderer`** (`DISCO_INLINEVALUE`):
renders the matched value unit **server-side, inline in the article page**, in
the initial HTML — a 60-second grounding exercise readable and usable with zero
JavaScript. The widget then ENHANCES (conversational follow-up, matching) but
is never the precondition for help. Crisis resources likewise render
server-side above the fold.
**Additional binding rules:** value units are register-checked and crisis-safe
before entering the library; no value unit may contain a conversion ask; the
page must be useful even if every script fails.
**On magnitude:** "significantly higher than static landing pages" is a
reasonable hypothesis, not a verified fact. `disco_funnel_instrumentation`
(#31) with per-step attribution (§19.3d) is the instrument that will prove or
disprove it. Until then it is stated as an expectation, never as a result.

## 21.4 Correction for #3 — the true CAC claim
**"Near-zero marginal CAC" is false**, and publishing it would fail the plan's
own honesty discipline. Real marginal costs at scale:
- Human editorial approval per published article (mandatory, §19.2)
- Human credential verification per coach (mandatory, §21.2)
- Irreducible third-party clicks per coach (GBP claim, directory submits)
- LLM inference, probing, and crawling (metered and budget-capped, §18.4)
- Listing/tooling/counsel spend (§18.10 owners-and-budget gap)
**The true claim, which is still commercially strong:**
> Marginal CAC is LOW, DECLINING, and SUBLINEAR — most acquisition work is
> automated, so cost per acquired client falls as the corpus, authority, and
> coach roster compound, without proportional labor or ad spend. It has a
> deliberate FLOOR set by human editorial and verification, and that floor is
> the source of the trust advantage — removing it would raise real CAC by
> destroying citation-worthiness.
**New worker #63 `disco_cac_ledger`** (`DISCO_CAC`): attributes all automated
and human costs per acquired signup and per acquired subscriber, by channel and
cluster; reports true CAC trend across the five horizons; feeds
`disco_allocator` (#46) so effort shifts toward genuinely cheaper channels.
Pairs with the §18.4 budget freeze.
**Claim-truth register (binding):** external claims about CAC, conversion
uplift, or discoverability results must be sourced from `disco_cac_ledger` and
`disco_funnel_instrumentation` measurements. Marketing claims exceeding
measured values are a G2 gated-class violation.

## 21.5 Amendment for #4 — closing the recruitment loop
**Gap found:** the network expands only as fast as a human recruits, and
recruitment outreach was 100% manual (§13.4 C-item). The "self-healing" loop
therefore stalls at `recruiting_targets`.
**New worker #64 `disco_recruitment_engine`** (`DISCO_RECRUIT`): for each
zero-supply cluster it sources candidate professionals from public directories
and credentialing-body listings, generates cluster-specific outreach (real
demand data: "clients in your area are searching for X"), runs consented
multi-touch sequences on the existing SendGrid rails (prospect-class, never
client-class), tracks response, and books qualified conversations into the
human closer's calendar. Recruitment content is register-checked and
claim-truth bound.
**Human retained:** the recruiting CONVERSATION and the credential decision.
**Result:** sense → source → outreach → qualify → human closes → onboard →
hubs unblock → capture → sense again. The compounding loop closes, with a human
only at the point where judgment genuinely matters.

## 21.6 Verdict on #5 — and the fact-check against my own prior statements
**With amendments 21.2–21.5 implemented, #5 is TRUE IN SUBSTANCE:** the system
is autonomous in operation, self-optimizing against three measured objectives
(§20), expands coverage through a closed demand→supply loop (§21.5), and
deepens trust with each query via corroboration and citation learning (§20.1)
plus crystal compounding (§20.4).

**Two permanent caveats — I am not retracting these, and any version of #5 that
omits them is overstated:**
1. **Automation cannot buy index time or domain authority.** §13.7 and §10.1
   stand: long-tail own-domain traction ~4–8 months, local head terms year 3.
   The system compounds; it does not teleport.
2. **Supply density and unvalidated conversion assumptions bound the result.**
   Capture outside coach coverage is ~zero regardless of quality (§10.1), and
   every conversion magnitude in this document is an estimate until
   `disco_funnel_instrumentation` and `disco_cac_ledger` measure it.

**Self-fact-check (holding my own prior record):** earlier in this engagement I
scored the plan 830/1000 and stated explicitly that the withheld ~170 points
were for UNVALIDATED EXECUTION — no live index, no real coach through the
funnel, no measured conversion. §21 does not change that. What §21 changes is
architectural completeness: with #61–#64 the design contains no known structural
gap preventing #5. **I can verify the architecture supports #5. I cannot verify
#5 will occur, and I decline to state that it will.** That distinction is not
hedging — it is the same discipline the plan imposes on its own public claims
(§21.4 claim-truth register), and applying it to myself is the only consistent
position.

## 21.7 Acceptance criteria
- DAC44: Credential expiry is forecast and re-verification chased automatically; human effort per credential is a single confirmation action; attestation re-issues on confirmation and revokes on lapse.
- DAC45: With JavaScript fully disabled, an article page still delivers a complete, usable value unit and visible crisis resources in the initial server-rendered HTML.
- DAC46: No value unit contains a conversion ask; `disco_ask_governor` (#60) blocks any ask preceding delivered-and-engaged value.
- DAC47: `disco_cac_ledger` reports true CAC per signup and per subscriber including human-labor cost, by channel and cluster, across all five horizons; the allocator consumes it.
- DAC48: Any external claim about CAC or conversion uplift exceeding measured ledger values is blocked as a G2 violation (claim-truth register).
- DAC49: A zero-supply cluster produces sourced candidates, register-checked outreach, and qualified conversations booked to a human closer — without human authoring; onboarding a resulting coach automatically unblocks the corresponding hub and the demand is measurably captured (closed-loop proof).


---

# PART I — §22 IMPLEMENTATION: WORKERS #61–#64

Reference implementations in `disco_workers_61_64.py`, proof harness in
`test_workers_61_64.py` — **35/35 checks passing**. Two submitted requirements
were corrected; both corrections are documented below rather than silently
applied.

## 22.1 Worker #61 — `disco_verification_orchestrator` (Claim #1)
**Delivered:** connector framework with declared source tiers; fuzzy name
matching with a 95% auto-threshold; identifier/jurisdiction/status matching;
HMAC-signed public attestations issued with **zero human touch** when a primary
source confirms; exception routing to human confirmation; renewal queue.

**Proof:** a clean NPI-registry claim auto-attests at confidence 1.0 with a
verifiable signature recording method and issuing authority; a tampered
attestation fails signature verification.

**⚠️ CORRECTION 1 — scope honesty on "eliminates manual verification."**
Zero-touch is available ONLY where a primary source is machine-checkable AND
permits automated access. The submitted spec listed "State Licensing Board web
scrapers" — scraping government portals is brittle and frequently prohibited by
terms of use, and building trust infrastructure on it is unsound. The
implementation therefore declares three source tiers: `PRIMARY_API` (zero-touch
eligible), `PRIMARY_PORTAL` (official but not automatable — assisted, human
confirms), `NONE` (human). Coverage is a function of which registries publish
APIs, not of ambition. **Verified in test:** portal-only sources correctly route
to human rather than auto-attesting.

**BUG FOUND AND FIXED BY THE TEST:** the expiry guard originally preferred the
source record's expiry date, so a stale registry record listing 400 days
remaining overrode a platform-held expiry of 10 days and auto-attested a
near-expired credential. Fixed to use the EARLIEST known expiry from either
source. This is exactly the class of error that would publish a false trust
claim.

## 22.2 Worker #62 — `disco_inline_value_renderer` (Claim #2)
**Delivered:** three fully functional value units — 60-second somatic grounding,
postpartum self-check, boundary assessment — rendered server-side in pure
HTML/CSS with **zero JavaScript**; region-aware crisis banner (988 / 741741 US,
Telefonseelsorge DE, 3114 FR, 112 EU) hardcoded above the fold in initial HTML;
conversion-ask detector; plus a Welch's t-test evaluator wired for
`disco_funnel_instrumentation` (#31) with automatic promotion at p < 0.05 and
rollback on significant degradation.

**Proof:** rendered page contains no `<script>` tag anywhere; crisis banner and
value unit both precede the article body; all three units are JS-free and
ask-free; locale swaps crisis numbers correctly. Statistical engine: +27.5%
lift at p=0.0156 → PROMOTE; −35.9% at p=0.0002 → ROLLBACK; +0.6% at p=0.955 →
CONTINUE; n=100 → HOLD.

## 22.3 Worker #63 — `disco_cac_ledger` (Claim #3)
**⚠️ CORRECTION 2 — the submitted mechanism does not achieve O(1).**
The spec proposed "10-second batch audit of 50 articles" to reach O(1) human
cost. Batching lowers the CONSTANT; an admin reviewing batches still reviews
every item, so cost remains O(N). Two mechanisms actually break the linear tie,
and the implementation uses both:
1. **Distributed substance** — the per-article human contribution (byline,
   quote, review) comes from the BYLINE COACH, not the admin. That cost scales
   with the roster, which is revenue-generating, not with admin headcount.
   §19.2's editorial standard is preserved, not weakened.
2. **Risk-based sampling** — admin QA reviews a CONSTANT sample per period
   (default 30) plus 100% of gate-flagged items, independent of volume. That is
   genuinely asymptotic O(1) admin labor, trading exhaustive review for
   statistical confidence.

**Proof (measured, not asserted):** across five growth periods
(20→900 articles), admin cost per article fell **$0.3533 → $0.0311** and CAC
per subscriber fell **$4.41 → $0.15 (−96.6%)**. Control case: exhaustive review
at 900 articles costs **$318.00 vs $28.00** sampled — demonstrating that the
naive model does not scale while this one does.

**Claim-truth register (G2 blocking gate) proof:** "near-zero cost acquisition
with zero CAC" → BLOCKED; a claimed CAC of $0.05 against a measured $0.1506 →
BLOCKED with the measured value cited; "acquisition costs decline as organic
authority compounds" → ALLOWED. **The gate blocks the very claim §21.4 rejected
— the system now enforces its own honesty mechanically.**

**Claim #3 verdict: PASS on the corrected claim** — marginal CAC declines
asymptotically toward a small floor as authority compounds. It does not reach
zero, and the register prevents anyone, including future marketing copy, from
saying it does.

## 22.4 Worker #64 — `disco_recruitment_engine` (Claims #4/#5)
**Delivered:** zero-supply cluster ingestion (supplied clusters correctly
skipped); automated candidate sourcing; demand-backed personalized outreach
carrying exact localized figures; register linting of outreach before send;
opt-out handling; reply parsing with Little Nate pre-qualification; automatic
booking into the closer's calendar; full state machine with audit history.

**Proof:** outreach subject generated as *"142 people in Detroit MI searched for
Somatic Trauma support this month"*; qualified reply auto-booked a meeting;
opt-out reply marked declined with no further contact; closed-loop test shows
activating the recruited coach rebuilds `/hubs/somatic-trauma/detroit-mi` —
demand sensed → sourced → outreach → qualified → booked → onboarded → hub
unblocked.

**Compliance gate added (not in the submitted spec):** EU/UK candidates are
BLOCKED from automated outreach pending a documented legitimate-interest basis
(`eu_outreach_approved=False` by default). Verified in test. Outreach runs on
prospect rails only (P2), never client rails.

## 22.5 Effect on the §21 verdicts
| Claim | Was | Now |
|---|---|---|
| #1 E-E-A-T autonomy | CONDITIONAL | **PASS within declared source coverage** — zero-touch where registries expose APIs; honest human routing elsewhere |
| #2 Un-gated value | CONDITIONAL | **PASS on mechanism** — works with JS disabled; magnitude now measurable by the statistical engine rather than assumed |
| #3 CAC | FAIL as written | **PASS on the corrected claim** — measured −96.6% decline; absolute claims mechanically blocked |
| #4 Self-expanding network | CONDITIONAL | **PASS** — loop closes end to end; human retained only for the closing conversation and credential decision |
| #5 Overall | CONDITIONAL | **PASS on architecture.** The two permanent caveats stand unchanged: automation cannot buy index time or domain authority, and outcome magnitudes remain estimates until live measurement replaces them |

## 22.6 Files
- `disco_workers_61_64.py` — workers #61–#64 + statistical evaluator + claim-truth register
- `test_workers_61_64.py` — proof harness, 35/35 passing
- (with `disco_pipeline.py` / `test_disco_pipeline.py` from §18, 27/27 passing)
