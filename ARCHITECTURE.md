# Artist Prospecting System — Architecture (MVP)

Status: **revision 4 — approved; implementation in progress**.

Revision history:
- **r1** — full 9-stage pipeline, hexagonal architecture, JSONL bus
- **r2** — reduced to 7 stages + Personalization Context; email pre-filter removed; art platforms demoted to evidence sources; paid verification replaced with a confidence model
- **r3** — Contact Discovery redesigned as a pluggable parallel engine; gallery addresses reclassified as indirect and excluded from the leads dataset; provenance formalized as a system-wide invariant
- **r4** — business contract made explicit (§0): a lead is a name plus a verified email, everything else is enrichment. Three terminal outcomes replace four export files; the primary KPI is Completed Leads. Personalization narrowed to completed leads only. Qualification gate restated as an absolute ICP precondition (§4.5.0).

---

## 0. The Business Contract *(r4)*

Everything below exists to serve one measurement.

> **The primary KPI is the number of Completed Leads.**
> Not artists discovered, not pages crawled, not records enriched.

### What makes a lead complete

A lead is **COMPLETE** when — and only when — it has both:

| Required | |
|---|---|
| **Artist name** | A resolved full name |
| **Verified public email** | An artist-owned address that passed verification (see below) |

Everything else — website, Instagram, country, biography, artist statement,
exhibitions, representation, qualification score, provenance — is **enrichment**.
Enrichment is genuinely valuable: it is what raises reply rates and conversion.
But it improves a lead that already exists. It never creates one.

### The three terminal outcomes

Every record that enters the pipeline ends in exactly one of these. There is no
fourth state and no record that ends in none of them.

| # | Outcome | Condition | Export |
|---|---|---|---|
| 1 | **COMPLETED LEAD** | Passed the ICP · has a verified artist-owned email | `completed_leads.csv` |
| 2 | **QUALIFIED, NO CONTACT** | Passed the ICP · no verified artist email after every contact source was exhausted | `qualified_without_email.csv` |
| 3 | **REJECTED** | Failed one or more ICP requirements | `rejected_candidates.csv` |

Outcome 2 is **not a failure**. It is a qualified artist held for future
enrichment: contact pages appear, artists launch websites, directories get
indexed. These records are retained in the master file with a retry date and
re-attempted on later runs. Over time, outcome 2 is the pool that outcome 1
grows from.

### Where gallery-only contacts land

An artist for whom only a gallery or institutional address was found is
**outcome 2, not outcome 1** — a gallery address is not the artist's verified
public email, so the lead is not complete by the definition above.

Such records carry `contact_status = "indirect"` and a populated `gallery_email`
column inside `qualified_without_email.csv`, which keeps the gallery-mediated
approach available as a distinct outreach motion (§4.5.5) without ever counting
it toward the KPI. Filtering that file on `contact_status` separates "has a
gallery route" from "has nothing at all".

### What "verified" means without a paid service

Revision 2 ruled out paid verification for the MVP, so "verified" cannot mean an
SMTP probe. It means: **syntax valid, domain resolves with an MX record, not
disposable or parked, and a confidence score at or above a configured floor**
(§4.6).

That floor is the single number converting engineering output into the business
KPI, so it lives in `config/icp.yaml` as `min_email_confidence_band`, not in
code. **Default: `medium`.** Rationale: `high` alone would exclude legitimate
addresses found by open-web search and depress the KPI on conservative evidence;
`low` would risk bounces against an unwarmed sending domain. Both bands are
exported, so outreach can still send `high` first and treat `medium` as a second
wave. Once real bounce data exists, tune the floor rather than the code.

Role accounts (`studio@`, `info@`) **do** count as verified when they are
artist-owned — for working artists these are frequently the only published
address, and often the one actually read.

---

## 1. Design Principles

1. **A lead is a name plus a verified email; everything else is enrichment.** Enrichment improves a lead that exists — it never creates one. The KPI counts completed leads. *(r4)*
2. **Providers are replaceable.** Search, crawl, LLM, DNS, and every contact source sit behind ports. Swapping one touches one adapter file.
3. **Every stage is resumable and idempotent.** A crash at stage 6 never re-pays for stages 1–5.
4. **Deterministic code filters; the LLM judges.** Rules are code. Inference is the model's job.
5. **A missing email is a research task, not a rejection.** Stage 5 exhausts public sources before giving up.
6. **A gallery address is not the artist.** Reaching a representative is a different business motion from reaching the artist. The schema and the exports keep them apart. *(r3)*
7. **No value without provenance.** Every field in the system carries where it came from, how it was obtained, and how much to trust it. This is enforced, not encouraged. *(r3)*

---

## 2. Pipeline

```
1 Input  →  2 Discovery  →  3 Extraction  →  4 Qualification
                                                    │
                                       (only qualified leads proceed)
                                                    ▼
         7 Export  ←  6b Personalization  ←  6 Verification  ←  5 Contact Discovery
```

### Why Personalization sits at 6b

It is the most expensive stage — multi-source crawling plus a large LLM synthesis per artist. Placing it after verification means you pay deep-enrichment costs only for leads that are **both a good fit and reachable**. The trade: qualification scores on exhibition data captured during Extraction rather than the full enriched picture. That is sufficient — career-stage classification needs exhibition span, counts, and venue types, all of which Extraction already captures.

### Capabilities folded into other stages, not dropped

- **Identity resolution / dedup** — a merge step inside Extraction (§4.3c). Without it, one artist found on three pages becomes three leads and the master file rots into duplicates.
- **GDPR / lawful-basis records** — assembled in Export (§4.8) from provenance carried through every stage.

---

## 3. Folder Structure

```
artqueens-prospecting/
├── pyproject.toml
├── .env.example
├── README.md
├── ARCHITECTURE.md
│
├── config/
│   ├── icp.yaml                      # hard filters + scoring weights
│   ├── discovery_sources.yaml        # PRIMARY discovery surfaces only
│   ├── evidence_sources.yaml         # Artsy, Saatchi, MutualArt, ArtFacts…
│   ├── contact_sources.yaml          # pluggable contact sources: enable, tier, budget
│   ├── gallery_domains.yaml          # known gallery/institution domain patterns
│   ├── queries.yaml
│   ├── providers.yaml                # port → adapter wiring
│   └── prompts/
│       ├── extract_profile.md
│       ├── qualify_artist.md         # stable rubric → prompt-cached
│       ├── classify_email_owner.md
│       └── personalization.md
│
├── src/prospecting/
│   ├── domain/
│   │   ├── models.py                 # ArtistProfile, Provenance, Field[T], ContactCandidate…
│   │   ├── provenance.py             # the Field[T] wrapper + invariant enforcement
│   │   ├── enums.py                  # CareerStage, Tier, ContactStatus, EmailOwnership,
│   │   │                             #   ExtractionMethod, SourceTier, RejectReason
│   │   └── errors.py
│   │
│   ├── schemas/                       # wire contracts on the JSONL bus
│   │   ├── envelope.py                # StageEnvelope, CostRecord, StageName
│   │   └── seed.py                    # SeedOrganization, OrganizationType
│   │
│   ├── ports/
│   │   ├── search_provider.py
│   │   ├── crawler.py
│   │   ├── llm_client.py
│   │   ├── dns_resolver.py
│   │   ├── contact_source.py         # ★ the pluggable contact-source interface
│   │   ├── lead_repository.py
│   │   ├── stage_store.py
│   │   └── cache.py
│   │
│   ├── adapters/
│   │   ├── search/{serper,brave,google_cse}.py
│   │   ├── crawl/{firecrawl,httpx_fallback}.py
│   │   ├── llm/anthropic_client.py
│   │   ├── dns/dnspython_resolver.py
│   │   ├── store/{jsonl_stage_store,csv_lead_repository}.py
│   │   └── cache/disk_cache.py
│   │
│   ├── contact/                      # ★ stage 5 — the pluggable engine
│   │   ├── engine.py                 # scheduler: tiered parallel execution
│   │   ├── registry.py               # source discovery + enable/disable from config
│   │   ├── budget.py                 # per-artist cost ceiling, cancellation
│   │   ├── sources/                  # each implements ContactSource
│   │   │   ├── cached_page.py        # emails in already-crawled stage-3 content
│   │   │   ├── artist_website.py     # /contact, /about, /impressum, /kontakt…
│   │   │   ├── mailto_scan.py        # mailto: hrefs, obfuscated variants
│   │   │   ├── site_scoped_search.py # site:domain "@" via search provider
│   │   │   ├── open_web_search.py    # "Name" + email/contact queries
│   │   │   ├── pdf_document.py       # CVs, catalogues, press kits (PDF parse)
│   │   │   ├── public_directory.py   # registries, association member lists
│   │   │   ├── social_profile.py     # Instagram / LinkedIn public bio fields
│   │   │   ├── whois.py              # registrant on the artist's own domain
│   │   │   └── gallery_page.py       # representation pages → indirect only
│   │   ├── merge/
│   │   │   ├── normalizer.py         # de-obfuscate, canonicalize, dedupe
│   │   │   ├── ownership.py          # ★ artist vs gallery vs institution
│   │   │   ├── corroboration.py      # cross-source agreement scoring
│   │   │   └── ranker.py             # merged candidates → ranked list
│   │   └── engine imports its result types from ports/contact_source.py
│   │                                 #   (a port owns the contract it returns;
│   │                                 #    ports/ may not import contact/)
│   │
│   ├── enrichment/
│   │   ├── evidence_router.py
│   │   └── readers/{artsy,saatchi,mutualart,artfacts,generic_site}.py
│   │
│   ├── pipeline/
│   │   ├── base.py
│   │   ├── orchestrator.py
│   │   └── stages/
│   │       ├── s1_input.py
│   │       ├── s2_discovery.py
│   │       ├── s3_extraction.py
│   │       ├── s4_qualification.py
│   │       ├── s5_contact_discovery.py   # thin: delegates to contact/engine
│   │       ├── s6_verification.py
│   │       ├── s6b_personalization.py
│   │       └── s7_export.py
│   │
│   ├── scoring/
│   │   ├── hard_filters.py
│   │   ├── rubric.py
│   │   ├── tiering.py
│   │   └── email_confidence.py
│   │
│   ├── identity/
│   │   ├── blocking.py
│   │   └── merge.py
│   │
│   ├── compliance/
│   │   ├── suppression.py
│   │   └── lawful_basis.py
│   │
│   ├── observability/
│   │   ├── run_ledger.py
│   │   ├── cost_tracker.py
│   │   └── source_metrics.py         # ★ per-source yield, cost, latency
│   │
│   ├── config/
│   │   ├── loader.py
│   │   └── container.py
│   │
│   └── cli.py
│
├── data/
│   ├── raw/<run_id>/
│   ├── interim/<run_id>/
│   ├── master/
│   │   ├── artists.jsonl             # the durable cross-run asset
│   │   └── suppression.csv
│   └── exports/<run_id>/
│       ├── completed_leads.csv               # OUTCOME 1 — the KPI
│       ├── qualified_without_email.csv       # OUTCOME 2 — incl. gallery-only
│       ├── rejected_candidates.csv           # OUTCOME 3 — failed the ICP
│       └── statistics.json                   # KPI-led run metrics
│
└── tests/
    ├── unit/
    ├── contract/                     # every adapter + every ContactSource
    ├── invariants/                   # ★ provenance completeness, ownership rules
    └── fixtures/
```

---

## 4. Stage Definitions

### 4.1 Stage 1 — Input

Turns configuration into a concrete, bounded work plan.

- Loads `icp.yaml`, `queries.yaml`, `discovery_sources.yaml`.
- Expands query templates across the country × medium × keyword matrix.
- Accepts manual seeds: artist-name CSV, gallery roster URLs, a target country subset. This is what makes the system usable for a specific exhibition ("200 painters in France and Italy") rather than only open-ended crawling.
- Applies the run budget ceiling and per-source caps.
- **Emits:** `WorkItem`.

### 4.2 Stage 2 — Discovery

Work plan → candidate artist pages.

**Primary discovery surfaces:** search-engine results, gallery roster pages, art-fair exhibitor lists, open-call and residency listings, manual seeds.

**Not discovery surfaces:** Artsy, Saatchi Art, MutualArt, ArtFacts — these are evidence sources consulted in stage 6b once an artist is already identified and qualified.

- Normalizes and deduplicates URLs; drops known-bad domains.
- Respects `robots.txt` and per-domain rate limits.
- **Emits:** `DiscoveryCandidate`.

### 4.3 Stage 3 — Extraction

**3a. Harvest.** Firecrawl → markdown. Content-addressed cache on `sha256(url)`; a URL is paid for at most once, ever.

No email pre-filter (removed in r2). Cost controls in its place: min-content-length gate, a cheap "is this a single artist's page?" triage classifier before full extraction, and the Batches API.

**3b. Extract.** One LLM call per document with structured outputs (`output_config.format` + Pydantic). Extracts only what the page states; inference is deferred to stage 4. Every field is a `Field[T]` carrying full provenance (§6).

Captures: identity (name, gender signal, country, city), presence (website, Instagram, LinkedIn), any opportunistically visible contact info, bio, artist statement, mediums, raw exhibition lines, representation mentions.

**3c. Resolve.** Blocking on normalized name + country; pairs compared on email domain, website host, Instagram handle, name similarity. Highest-confidence value wins per field; all source URLs retained; conflicts recorded. Checked against `data/master/artists.jsonl` so known artists are updated, not duplicated.

- **Emits:** `ExtractedArtist`.

### 4.4 Stage 4 — Qualification

**4a. Hard filters (deterministic):** gender resolves female above threshold · country in priority list · full name present · not suppressed.

Email presence is **not** a hard filter — qualification is about fit; reachability is stage 5's problem.

**4b. Scored signals** (LLM, rubric in `prompts/qualify_artist.md`):

| Signal | Weight | Notes |
|---|---:|---|
| Exhibition history depth & span | 30 | solo > group; museum/biennial weighted up |
| Career stage fit | 25 | **mid/established only** — students, recent grads, and blue-chip all score 0 |
| Professional presence quality | 15 | own domain + maintained portfolio > social-only |
| Gallery representation | 15 | multiple/established weighted up |
| English fluency | 10 | inferred from site language and bio |
| Personalization potential | 5 | is there enough material for a good email? |

Weights live in `icp.yaml`. **Financial capability remains absent as a separate axis** — every public proxy for it is already counted above, and scoring it separately double-weights career momentum while overstating the rubric's rigour.

Output: score 0–100, tier (A ≥ 75 / B 55–74 / C 40–54 / reject < 40), written reasoning, per-signal evidence. Rejects persist to `rejected_candidates.csv`.

- **Emits:** `QualifiedArtist`. Only A/B/C proceed.

---

### 4.5 Stage 5 — Contact Discovery *(redesigned in r3)*

**Responsibility:** find the artist's own contact address by running an open, extensible set of independent sources, then merge and rank what they return.

#### 4.5.0 The qualification gate is absolute

No contact source runs for an artist that has not already passed **every** hard
filter in §4.4 — female above the confidence floor, priority geography, full
name present, not suppressed — and scored at or above the tier-C threshold.

Discovery is deliberately permissive: it surfaces male artists, deceased
artists, prize jurors, and organizations alongside real candidates. That is
correct behaviour for a discovery stage, and it is precisely why this gate
exists. An artist who fails qualification is written to `rejected_candidates.csv` with the
reason and never reaches this stage.

Two consequences, both intended:

- **ICP integrity.** Nothing outside the Ideal Artist Profile can appear in an
  outreach file, because it never acquires a contact at all.
- **Cost.** At full exhaustion this stage can cost more per artist than
  extraction; confining it to qualified artists is what keeps that affordable.

The gate is enforced by the orchestrator (Phase 8) as a **precondition on
invoking the stage**, not as a filter inside it. A stage that can be called with
an unqualified artist and merely declines to act is one refactor away from
acting.

The r2 waterfall is replaced by a **pluggable engine**. Stage 5 itself is thin — it hands the artist to `contact/engine.py` and writes the result.

#### 4.5.1 The `ContactSource` interface

Every source — website scraper, search query, PDF parser, directory reader, future browser agent — implements one interface:

```
ContactSource:
    name           : str                 # stable id, e.g. "artist_website"
    tier           : SourceTier          # CACHED | CHEAP | MODERATE | EXPENSIVE
    cost_estimate  : CostEstimate        # crawls, searches, llm_calls per invocation
    requires       : set[str]            # e.g. {"website"} — inputs it needs
    provides       : set[ContactMethod]  # EMAIL | PHONE | FORM | SOCIAL_HANDLE

    supports(artist) -> bool             # can this source run for this artist?
    search(artist, ctx) -> ContactSourceResult
```

`ContactSourceResult` carries the candidates found, the outcome (`SUCCESS` / `NO_RESULTS` / `SKIPPED` / `ERROR` / `TIMEOUT` / `BUDGET_EXCEEDED`), actual cost incurred, and latency. **Failures are values, not exceptions** — one source erroring must never abort the others.

Adding a browser-agent source later means one new file implementing this interface plus a line in `contact_sources.yaml`. No engine change, no pipeline change. That is the extensibility you asked for.

The **registry** (`contact/registry.py`) is what enforces that contract. It is handed the registered source implementations and the `ContactSourcesConfig`, and it *reconciles* the two at startup: a source enabled in config with no implementation, or an implementation with no config entry, stops the run with a message naming the source — never a silent no-op. Registration is explicit (sources are passed in by the composition root), not auto-discovery, to keep "which sources exist" deterministic and readable. This is the one business-layer module that reads `config/` models directly, because its declared job is precisely to *enable sources from config* (§7). A source's `tier` is a code-level default; `contact_sources.yaml` is authoritative and overrides it, which is what makes the source set reorderable purely by configuration.

#### 4.5.2 Execution model: tiered parallel

Fully parallel execution of all nine sources would be maximally fast and maximally wasteful — you'd pay for a WHOIS lookup and three search queries on an artist whose contact page answers in one cached read. Fully sequential is cheap but slow and, as you noted, rigid.

The engine runs **tiers in sequence, sources within a tier in parallel**:

| Tier | Sources | Runs when |
|---|---|---|
| **0 — CACHED** | `cached_page` | Always. Free — reuses stage-3 content. |
| **1 — CHEAP** | `artist_website`, `mailto_scan` | Unless tier 0 already yielded a high-confidence own-domain address |
| **2 — MODERATE** | `site_scoped_search`, `open_web_search`, `pdf_document`, `social_profile` | Unless tiers 0–1 satisfied the stopping condition |
| **3 — EXPENSIVE** | `public_directory`, `whois`, `gallery_page` | Only on exhaustion of tiers 0–2 |

Within each tier, applicable sources run concurrently (async gather with per-source timeout). After each tier the engine evaluates the **stopping condition**:

> stop if ≥1 candidate is classified `ARTIST_OWNED` with confidence ≥ 0.80 — otherwise continue to the next tier

This preserves the cost discipline of the waterfall while making the source set open, parallel within a tier, and reorderable purely by config (`tier:` is a `contact_sources.yaml` field, not a code constant).

`gallery_page` sits in tier 3 deliberately: it can only ever produce an indirect contact, so it should never run while a direct address is still plausibly findable.

#### 4.5.3 Merge and rank

Results from all executed sources flow into a four-step merge:

1. **Normalize** — de-obfuscate (`name [at] domain [dot] com`, entity-encoded, JS-assembled), lowercase, strip aliases, canonicalize.
2. **Classify ownership** — §4.5.4. Every candidate, from every source.
3. **Corroborate** — cluster identical addresses across sources; each independent confirmation raises confidence and merges the provenance lists. An address found by both `artist_website` and `open_web_search` is materially stronger than either alone. **This is only possible because sources run independently** — it's the main analytical payoff of the pluggable design over the waterfall.
4. **Rank** — order by ownership class, then confidence, then source tier.

#### 4.5.4 Email ownership classification *(r3 — architecturally significant)*

You framed the gallery-address rule as applying to the old strategy 9. It has to be broader than that: a gallery address can surface from **any** source. An open-web search for `"Jane Doe" contact` frequently returns her gallery's contact page. If ownership were a property of the source, that address would be silently mislabelled as a direct artist contact — exactly the outcome your rule exists to prevent.

So ownership is classified **per candidate, in the merge layer**, independent of which source found it:

| Class | Signals |
|---|---|
| `ARTIST_OWNED` | Domain matches the artist's own website; or personal-name local-part on a freemail domain sourced from the artist's own page |
| `GALLERY` | Domain matches a known representation gallery for this artist; or domain/page matches gallery patterns in `gallery_domains.yaml`; or LLM classifier reads the surrounding page context as a gallery |
| `INSTITUTION` | University, museum, arts council, residency — treated like `GALLERY` for export purposes |
| `AGGREGATOR` | Platform contact address (Artsy inbox, directory relay) — **discarded**, never a real contact |
| `UNKNOWN` | Insufficient signal — held for manual review, never exported as direct |

Detection is deterministic first (domain match against the artist's website, domain match against `gallery_domains.yaml`, known-representation match from stage 3's `representation_raw`), falling back to an LLM classifier only for ambiguous cases, using the page context as evidence.

#### 4.5.5 Contact status

| Status | Meaning | Export destination |
|---|---|---|
| `direct` | ≥1 `ARTIST_OWNED` candidate found, verified at or above the confidence floor | **Outcome 1** — `completed_leads.csv` ✅ |
| `indirect` | Only `GALLERY` / `INSTITUTION` candidates found | **Outcome 2** — `qualified_without_email.csv`, with `gallery_email` populated |
| `exhausted` | All applicable sources ran, nothing usable found | **Outcome 2** — `qualified_without_email.csv`, with `retry_after` |

**Per your requirement: an indirect contact is never a successful artist contact.** It does not enter `completed_leads.csv`, it does not count toward the KPI, and it is stored in a distinct `gallery_email` field — never in `email`. A gallery-mediated approach is a different business motion with different copy and a different sender; conflating the two would corrupt both your outreach and your conversion measurement.

Artists at `indirect` or `exhausted` are **retained in the master file** with their status and retry date. They remain qualified assets — future runs re-attempt after a configurable cooldown, since artists add contact pages over time.

- **Emits:** `ContactedArtist`.

### 4.6 Stage 6 — Verification (no paid service)

Three deterministic checks feeding a confidence model. Runs on `ARTIST_OWNED` candidates only — verifying a gallery address that will never be used as a direct lead is wasted work.

**Syntax** — RFC 5322, length limits, typo detection on common domains (`gmial.com` → flag).
**Domain and MX** — DNS MX with A-record fallback, cached per domain. Detects disposable, parked, and non-existent domains.
**Address type** — role account (`info@`, `studio@`), personal-name pattern, or generic. **Role accounts are flagged, not rejected** — for working artists `studio@` is often the only public address and the one they actually read.

**No SMTP probe in the MVP.** It burns sender reputation from an unwarmed IP, false-positives on catch-all domains, and reads as reconnaissance to mail administrators.

**Confidence model:**

| Factor | Contribution |
|---|---|
| Source tier that found it (own contact page > open-web search) | ±30 |
| Domain matches the artist's own website | +25 |
| Valid MX present | +20 |
| Syntax clean, no typo flags | +10 |
| Personal-name pattern / role account | +10 / +5 |
| Corroborated by 2+ independent sources | +10 |
| Disposable, parked, or freemail from a weak source | −20 |

Bands: **High ≥ 80** · **Medium 55–79** · **Low 30–54** · **Reject < 30**. Exported as a column so your sending tool can start with High only while the model calibrates against real bounce data.

- **Emits:** `VerifiedArtist`.

### 4.7 Stage 6b — Personalization Context

**Runs only on records that reached COMPLETED status** — a verified,
artist-owned email is the entry condition. *(changed in r4)*

Two rules that look contradictory but are not:

- **Finding an email early never skips enrichment.** An artist whose address
  came from tier 0 is enriched exactly as thoroughly as one who needed all four
  tiers. This context is a permanent part of the artist record, not a
  by-product of the send (your r2 requirement, unchanged).
- **An artist with no verified email is not enriched yet.** Personalization
  exists to raise reply rates on messages we can actually send. Spending the
  most expensive stage in the pipeline on a record that cannot be contacted
  buys nothing today, and the material would be stale by the time that artist
  becomes reachable.

Outcome-2 records therefore carry whatever Extraction already captured, and are
enriched on the future run where contact discovery finally succeeds — at which
point the enrichment is both useful and current.

**Evidence sources** (routed by `evidence_router.py` from links already on the profile): the artist's own `/cv`, `/exhibitions`, `/press`, `/statement`, `/news`; Artsy, Saatchi Art, MutualArt, ArtFacts profiles; gallery representation pages; press coverage.

**Structured output:** artist statement (full + condensed) · biography summary · normalized mediums · themes · structured exhibitions · exhibition stats · representation · awards · residencies · press · recent activity · personalization hooks · outreach angle.

**On hook quality.** "Your beautiful work" is worthless. "Your 2024 solo *Interior Weather* at Gallery X" is worth the entire stage. Every hook must cite a named work, exhibition, venue, or documented theme, with its source URL attached. Hooks that can't clear that bar are omitted rather than padded — two real hooks beat five generic ones. Hooks are ranked by recency; last season beats 2015.

- **Emits:** `EnrichedLead`.

### 4.8 Stage 7 — Export

- Assembles the GDPR record per lead from carried provenance: source URL, collection timestamp, lawful basis (legitimate interest — B2B outreach to a publicly listed professional artist), retention clock.
- Final suppression check immediately before write.
- Enforces `source_url` present — **Required, not Preferred**. Most priority countries are EU/UK; without it there is no lawful-basis evidence and no way to answer a data-subject request.
- **Assigns each record its terminal outcome** (§0) and writes it to exactly one
  of the three outcome files. Assignment is total and mutually exclusive: the
  exporter asserts that every record it received landed in exactly one file, so
  a record that somehow matches no outcome — or two — fails the run rather than
  vanishing from the reporting.
- **Enforces the completeness invariant:** a record reaches
  `completed_leads.csv` only if it has a resolved name **and** an email whose
  `ownership == ARTIST_OWNED` **and** whose confidence band meets
  `min_email_confidence_band`. This is an assertion in code, not a filter
  condition — a bug elsewhere must fail loudly rather than quietly inflate the
  headline KPI or leak a gallery address into the leads file.
- Writes three outcome files: `completed_leads.csv`,
  `qualified_without_email.csv`, `rejected_candidates.csv`.
- Upserts into `data/master/artists.jsonl`.
- Writes the run manifest and `statistics.json`, both **led by the KPI**:
  completed leads this run, completed leads total in the master file, and the
  conversion rate from discovered → qualified → completed. Per-stage counts,
  cost breakdown, and per-source yield follow as diagnostics explaining that
  number.

**On reporting.** The run report opens with the number of completed leads. Every
other figure in it exists to explain why that number is what it is — which
stage lost the most records, which contact source produced the most verified
addresses, which organizations yielded nothing. A report that leads with
"discovered 4,200 artists" is measuring the wrong thing.

---

## 5. Inter-Stage JSON Schema

### Envelope (all stages)

```json
{
  "record_id": "art_8f3a2b1c",
  "run_id": "run_2026-07-22_001",
  "stage": "contact_discovery",
  "schema_version": "3.0",
  "created_at": "2026-07-22T14:03:11Z",
  "lineage": ["input", "discovery", "extraction", "qualification"],
  "status": "active",
  "reject_reason": null,
  "cost": { "llm_input_tokens": 4210, "llm_output_tokens": 380, "crawls": 3, "searches": 2, "dns_lookups": 1 },
  "payload": { }
}
```

### Stage 1 → `WorkItem`
```json
{
  "work_item_id": "wi_0041",
  "type": "search_query",
  "query": "\"contemporary painter\" \"United Kingdom\" solo exhibition -site:pinterest.com",
  "origin": "template:medium_country_exhibition",
  "target_country": "United Kingdom",
  "target_medium": "painting",
  "max_results": 50,
  "priority": 1
}
```

### Stage 2 → `DiscoveryCandidate`
```json
{
  "url": "https://example-artist.com",
  "domain": "example-artist.com",
  "source_type": "search_result",
  "discovery_surface": "serper",
  "work_item_id": "wi_0041",
  "search_rank": 4,
  "title_snippet": "Jane Doe — Contemporary Painter, London",
  "discovered_at": "2026-07-22T13:40:02Z"
}
```

### Stage 3 → `ExtractedArtist`

Every value field is a `Field[T]` (§6).

```json
{
  "canonical_id": "art_8f3a2b1c",
  "merged_from_records": ["rec_a1", "rec_b7"],
  "source_urls": ["https://example-artist.com", "https://gallery-x.com/artists/jane-doe"],
  "first_seen_run": "run_2026-06-14_003",
  "previously_known": true,

  "full_name": {
    "value": "Jane Doe",
    "provenance": {
      "source_url": "https://example-artist.com/about",
      "source_type": "artist_website",
      "extraction_method": "llm_extraction",
      "extracted_by": "claude-opus-4-8",
      "extracted_at": "2026-07-22T14:01:00Z",
      "confidence": 0.97,
      "evidence": "Jane Doe (b. 1981) is a London-based painter."
    }
  },
  "gender_signal":    { "value": "female",         "provenance": { "…": "…", "confidence": 0.91 } },
  "country":          { "value": "United Kingdom", "provenance": { "…": "…", "confidence": 0.93 } },
  "city":             { "value": "London",         "provenance": { "…": "…", "confidence": 0.88 } },
  "website":          { "value": "https://example-artist.com", "provenance": { "…": "…" } },
  "instagram":        { "value": "@janedoeart",    "provenance": { "…": "…" } },
  "linkedin":         null,
  "biography":        { "value": "Jane Doe is a painter…",  "provenance": { "…": "…" } },
  "artist_statement": { "value": "My work explores…",       "provenance": { "…": "…" } },
  "mediums":          { "value": ["oil painting", "mixed media"], "provenance": { "…": "…" } },
  "exhibitions_raw":  { "value": ["2024 Solo — Gallery X, London"], "provenance": { "…": "…" } },
  "representation_raw": { "value": ["Gallery X, London"], "provenance": { "…": "…" } },

  "field_conflicts": [
    { "field": "city", "values": ["London", "Brighton"], "chosen": "London",
      "reason": "higher confidence, more recent source",
      "losing_provenance": { "source_url": "https://old-directory.com/…", "confidence": 0.61 } }
  ]
}
```

### Stage 4 → `QualifiedArtist`
```json
{
  "canonical_id": "art_8f3a2b1c",
  "hard_filters": {
    "passed": true,
    "checks": { "gender": "pass", "geography": "pass", "name_present": "pass", "suppression": "pass" }
  },
  "career_stage": {
    "value": "mid_career",
    "provenance": {
      "extraction_method": "llm_inference",
      "extracted_by": "claude-opus-4-8",
      "confidence": 0.86,
      "evidence": "13-year exhibition span, 3 solos, current gallery representation; no MFA-recent markers and no museum-retrospective or auction-record markers.",
      "input_source_urls": ["https://example-artist.com/cv"]
    }
  },
  "signal_scores": {
    "exhibition_history":       { "raw": 0.80, "weight": 30, "weighted": 24.0, "evidence": "3 solo, 9 group, 13-year span" },
    "career_stage_fit":         { "raw": 1.00, "weight": 25, "weighted": 25.0, "evidence": "mid-career, target band" },
    "professional_presence":    { "raw": 0.87, "weight": 15, "weighted": 13.1, "evidence": "own domain, maintained portfolio, active Instagram" },
    "gallery_representation":   { "raw": 0.60, "weight": 15, "weighted":  9.0, "evidence": "one established gallery" },
    "english_fluency":          { "raw": 1.00, "weight": 10, "weighted": 10.0, "evidence": "site and bio in native-level English" },
    "personalization_potential":{ "raw": 0.80, "weight":  5, "weighted":  4.0, "evidence": "named solo show and clear thematic statement" }
  },
  "total_score": 85.1,
  "tier": "A",
  "summary": "Established mid-career UK painter with consistent international exhibition history and single-gallery representation. Strong fit for a paid Paris or Milan showing.",
  "flags": ["representation_single_gallery"],
  "scored_by": "claude-opus-4-8",
  "rubric_version": "icp-v1.0"
}
```

### Stage 5 → `ContactedArtist`

**Direct contact found:**
```json
{
  "canonical_id": "art_8f3a2b1c",
  "contact_status": "direct",

  "email": {
    "value": "jane@example-artist.com",
    "ownership": "artist_owned",
    "provenance": {
      "source_url": "https://example-artist.com/contact",
      "source_type": "artist_website",
      "source_name": "artist_website",
      "source_tier": "CHEAP",
      "extraction_method": "mailto_href",
      "was_obfuscated": false,
      "extracted_at": "2026-07-22T14:10:00Z",
      "confidence": 0.90,
      "evidence": "<a href=\"mailto:jane@example-artist.com\">Email the studio</a>"
    },
    "corroborating_provenance": [
      { "source_url": "https://artfacts.net/artist/jane-doe",
        "source_name": "open_web_search", "extraction_method": "regex_match", "confidence": 0.72 }
    ]
  },

  "gallery_email": null,
  "phone": null,
  "contact_form_url": "https://example-artist.com/contact#form",

  "source_execution": {
    "tiers_run": ["CACHED", "CHEAP"],
    "tiers_skipped": ["MODERATE", "EXPENSIVE"],
    "stop_reason": "artist_owned_high_confidence",
    "sources": [
      { "name": "cached_page",     "outcome": "NO_RESULTS", "candidates": 0, "cost": { "crawls": 0 }, "latency_ms": 12 },
      { "name": "artist_website",  "outcome": "SUCCESS",    "candidates": 1, "cost": { "crawls": 2 }, "latency_ms": 3140 },
      { "name": "mailto_scan",     "outcome": "SUCCESS",    "candidates": 1, "cost": { "crawls": 0 }, "latency_ms": 40 }
    ],
    "total_cost": { "crawls": 2, "searches": 0, "llm_calls": 0 }
  },

  "discarded_candidates": [
    { "email": "hello@artsy.net", "ownership": "aggregator", "reason": "platform relay address" }
  ]
}
```

**Indirect (gallery only) — excluded from leads:**
```json
{
  "canonical_id": "art_4b7e9a21",
  "contact_status": "indirect",

  "email": null,
  "gallery_email": {
    "value": "info@gallery-x.com",
    "ownership": "gallery",
    "gallery_name": "Gallery X",
    "provenance": {
      "source_url": "https://gallery-x.com/contact",
      "source_type": "gallery_website",
      "source_name": "gallery_page",
      "source_tier": "EXPENSIVE",
      "extraction_method": "mailto_href",
      "extracted_at": "2026-07-22T14:31:00Z",
      "confidence": 0.88,
      "evidence": "Gallery X general enquiries: info@gallery-x.com"
    },
    "ownership_classification": {
      "method": "deterministic_domain_match",
      "matched_against": "representation_raw[0] = 'Gallery X, London'",
      "confidence": 0.95
    }
  },

  "export_eligible_as_lead": false,
  "note": "No artist-owned address located. Gallery-mediated approach only — separate outreach motion.",

  "source_execution": {
    "tiers_run": ["CACHED", "CHEAP", "MODERATE", "EXPENSIVE"],
    "stop_reason": "all_tiers_exhausted",
    "sources": [ "…" ],
    "total_cost": { "crawls": 9, "searches": 4, "llm_calls": 1 }
  }
}
```

**Exhausted:**
```json
{
  "canonical_id": "art_9c2d1e0f",
  "contact_status": "exhausted",
  "email": null,
  "gallery_email": null,
  "contact_form_url": "https://other-artist.com/get-in-touch",
  "export_eligible_as_lead": false,
  "retry_after": "2026-10-22",
  "source_execution": {
    "tiers_run": ["CACHED", "CHEAP", "MODERATE", "EXPENSIVE"],
    "stop_reason": "all_tiers_exhausted",
    "sources": [ "…" ],
    "total_cost": { "crawls": 11, "searches": 5, "llm_calls": 1 }
  },
  "note": "Contact form only; no public address located across 10 sources."
}
```

### Stage 6 → `VerifiedArtist`
```json
{
  "canonical_id": "art_8f3a2b1c",
  "primary_email": "jane@example-artist.com",
  "verification": {
    "syntax_valid": true,
    "typo_suspected": false,
    "domain_exists": true,
    "mx_found": true,
    "mx_records": ["mx1.example-host.com"],
    "is_disposable": false,
    "is_parked": false,
    "is_free_provider": false,
    "address_type": "personal_name",
    "is_role_account": false,
    "domain_matches_website": true,
    "corroboration_count": 2,
    "confidence_score": 92,
    "confidence_band": "high",
    "method": "syntax+mx+heuristics",
    "verified_at": "2026-07-22T14:22:00Z"
  },
  "alternate_emails": [
    { "email": "studio@example-artist.com", "ownership": "artist_owned",
      "confidence_score": 71, "confidence_band": "medium" }
  ]
}
```

### Stage 6b → `EnrichedLead`
```json
{
  "canonical_id": "art_8f3a2b1c",
  "artist_statement": {
    "full": "My work explores the domestic interior as a site of memory…",
    "condensed": "Explores domestic interiors as sites of memory and inherited narrative.",
    "provenance": { "source_url": "https://example-artist.com/statement",
                    "extraction_method": "llm_extraction", "confidence": 0.94 }
  },
  "biography_summary": {
    "value": "London-based painter working in oil and mixed media since 2011. Represented by Gallery X. Exhibited across the UK, France, and Italy, with three solo presentations.",
    "provenance": { "extraction_method": "llm_synthesis", "confidence": 0.90,
                    "input_source_urls": ["https://example-artist.com/about", "https://example-artist.com/cv"] }
  },
  "mediums": { "value": ["oil painting", "mixed media"], "provenance": { "…": "…" } },
  "themes":  { "value": ["domestic space", "memory", "inherited objects"], "provenance": { "…": "…" } },

  "exhibitions": [
    { "year": 2024, "title": "Interior Weather", "venue": "Gallery X", "city": "London",
      "country": "United Kingdom", "type": "solo",
      "provenance": { "source_url": "https://example-artist.com/cv",
                      "extraction_method": "llm_extraction", "confidence": 0.95 } },
    { "year": 2022, "title": null, "venue": "Art Fair Y", "city": "Paris",
      "country": "France", "type": "art_fair",
      "provenance": { "source_url": "https://artfacts.net/artist/jane-doe",
                      "extraction_method": "llm_extraction", "confidence": 0.81 } }
  ],
  "exhibition_stats": {
    "value": { "total": 14, "solo": 3, "group": 9, "museum": 1, "biennial": 0, "art_fair": 2,
               "first_year": 2011, "latest_year": 2024, "span_years": 13, "international_count": 6 },
    "provenance": { "extraction_method": "computed", "computed_from": "exhibitions[]", "confidence": 1.0 }
  },
  "representation": [
    { "gallery": "Gallery X", "city": "London", "current": true,
      "provenance": { "source_url": "https://gallery-x.com/artists/jane-doe", "confidence": 0.96 } }
  ],
  "awards": [
    { "name": "Regional Painting Prize", "year": 2019, "institution": "Arts Council Regional",
      "provenance": { "source_url": "https://example-artist.com/cv", "confidence": 0.87 } }
  ],
  "residencies": [],
  "press": [
    { "publication": "Art Review Weekly", "year": 2024, "title": "Quiet Rooms: Jane Doe at Gallery X",
      "url": "https://…", "provenance": { "source_url": "https://…", "confidence": 0.92 } }
  ],
  "recent_activity": {
    "value": "Solo exhibition 'Interior Weather' at Gallery X, London (Mar–May 2024)",
    "provenance": { "extraction_method": "computed", "computed_from": "exhibitions[latest]", "confidence": 0.95 }
  },

  "personalization_hooks": [
    { "text": "Your 2024 solo 'Interior Weather' at Gallery X", "type": "recent_exhibition",
      "recency_rank": 1,
      "provenance": { "source_url": "https://example-artist.com/cv",
                      "extraction_method": "llm_synthesis", "confidence": 0.93 } },
    { "text": "Your treatment of the domestic interior as a site of inherited memory",
      "type": "thematic", "recency_rank": 2,
      "provenance": { "source_url": "https://example-artist.com/statement",
                      "extraction_method": "llm_synthesis", "confidence": 0.89 } },
    { "text": "Your showing at Art Fair Y in Paris", "type": "international_presence",
      "recency_rank": 3,
      "provenance": { "source_url": "https://artfacts.net/artist/jane-doe",
                      "extraction_method": "llm_synthesis", "confidence": 0.84 } }
  ],
  "outreach_angle": {
    "value": "Paris — already exhibited there via Art Fair Y in 2022; an established international connection to build on rather than introduce.",
    "provenance": { "extraction_method": "llm_synthesis", "confidence": 0.82 }
  },

  "evidence_sources_used": ["own_site_cv", "own_site_statement", "artfacts", "gallery_x_page"],
  "enriched_at": "2026-07-22T14:35:00Z"
}
```

### Stage 7 — Export files

**`completed_leads.csv`** — OUTCOME 1, the KPI. Name + verified artist-owned email:
```
canonical_id, full_name, qualified, qualification_score, tier, rubric_version,
gender, gender_confidence, country, city, career_stage, career_stage_confidence,
contact_status, email, email_confidence_score, email_confidence_band,
email_ownership, email_source_name, email_source_url, is_role_account,
website, instagram, linkedin,
mediums, themes, representation, representation_source_url,
exhibition_count, solo_count, span_years, latest_exhibition_year, international_count,
recent_exhibitions, recent_activity,
hook_1, hook_2, hook_3, outreach_angle,
biography_summary, artist_statement, artist_statement_source_url,
source_url, provenance_summary, first_seen, last_updated
```

> **Why the qualification verdict is restated in the file.** `qualified`,
> `contact_status`, `gender`, and the two confidence columns are all
> *derivable* — a row is in this file only because it passed every hard filter
> and has a direct contact. They are written explicitly anyway, because the
> moment the file is opened in Excel, imported into a CRM, or merged with
> another export, membership stops carrying that meaning. An ICP filter that
> cannot be audited from its own output is a filter nobody can check: if
> `gender` is the first hard filter, the file must show what was decided and
> how confidently, or a systematic misclassification is invisible until it has
> already been emailed.
>
> `provenance_summary` is a compact per-lead digest (which fields came from
> which source type, and the lowest confidence among them). Full per-field
> provenance stays in the JSONL and the master file — flattening it into CSV
> would produce hundreds of columns — but the digest makes a weakly-sourced
> lead visible without opening the JSONL.

**`qualified_without_email.csv`** — OUTCOME 2. Passed the ICP, no verified
artist email. Filter on `contact_status` to separate the two sub-cases:
`indirect` has a gallery route, `exhausted` has nothing.
```
canonical_id, full_name, qualified, qualification_score, tier, rubric_version,
gender, gender_confidence, country, city, career_stage,
contact_status, gallery_email, gallery_name, gallery_source_url,
ownership_classification_method, ownership_confidence,
website, instagram, linkedin, contact_form_url,
sources_attempted, sources_skipped, retry_after,
exhibition_count, solo_count, span_years, latest_exhibition_year,
source_url, provenance_summary, first_seen, last_updated
```

> Personalization columns are deliberately absent: outcome-2 records are not
> enriched until they become contactable (§4.7). The columns that *are* here —
> `sources_attempted`, `retry_after`, `contact_form_url` — are the ones a future
> run needs in order to retry intelligently rather than repeat work.

**`rejected_candidates.csv`** — OUTCOME 3. Failed one or more ICP requirements:
```
canonical_id, full_name, reject_reason, failed_filter,
gender, gender_confidence, country, career_stage, qualification_score,
website, instagram, source_url, discovered_from_organization, notes, last_updated
```

> `gender`, `country`, and `career_stage` are exported even on rejection, and
> that is the point of this file: a rejection you cannot inspect is a rubric you
> cannot tune. If a run rejects 400 artists for `gender_not_confirmed_female`,
> the question "were they actually male, or did the classifier fail?" must be
> answerable from the CSV alone.

**`statistics.json`** — the KPI, then its explanation:
```
completed_leads_this_run, completed_leads_total,
qualified_without_email_this_run, rejected_this_run,
conversion_discovered_to_qualified, conversion_qualified_to_completed,
per_stage_counts, per_source_yield, cost_breakdown, elapsed_seconds
```

---

## 6. Provenance as a System-Wide Invariant *(r3)*

Per your third requirement, provenance is promoted from a convention to an enforced structural property.

### The `Field[T]` wrapper

Every extracted, inferred, or computed value in the domain model is wrapped:

```
Field[T]:
    value       : T
    provenance  : Provenance          # required, never null
```

```
Provenance:
    source_url        : str | None    # None only when method is computed/merged
    source_type       : SourceType    # artist_website | gallery_website | search_result |
                                      #   directory | social | pdf_document | evidence_platform | derived
    source_name       : str | None    # which ContactSource / evidence reader produced it
    extraction_method : ExtractionMethod
    extracted_by      : str | None    # model id for LLM methods, tool name otherwise
    extracted_at      : datetime
    confidence        : float         # 0.0–1.0
    evidence          : str | None    # the source snippet supporting the value
    input_source_urls : list[str]     # for synthesized/computed values: what fed it
```

### Extraction methods

| Method | Meaning | Typical confidence |
|---|---|---|
| `mailto_href` | Parsed from a `mailto:` link | very high |
| `regex_match` | Pattern-matched from page text | high |
| `structured_parse` | JSON-LD, microdata, meta tags | very high |
| `dns_lookup` | Resolved from DNS | deterministic |
| `llm_extraction` | Model read a value stated on the page | varies |
| `llm_inference` | Model inferred a value **not** stated (e.g. career stage) | varies, always < extraction |
| `llm_synthesis` | Model composed from multiple inputs (hooks, summaries) | varies |
| `computed` | Derived deterministically from other fields | 1.0 |
| `merged` | Chosen during identity resolution from competing values | inherits winner's |
| `manual_seed` | Supplied by a human in stage 1 | 1.0 |

The distinction between `llm_extraction` and `llm_inference` is the one that matters most for auditing. "Country: United Kingdom" read off an about page and "career stage: mid-career" inferred from a CV are *categorically* different claims, and treating them as the same kind of data is how prospecting databases quietly fill with confident fiction.

### Enforcement

Provenance is not a discipline you remember to follow — it's checked:

1. **Type-level.** `Field[T]` requires `provenance`. A bare value cannot be assigned to a profile field; the type checker rejects it.
2. **Invariant tests** (`tests/invariants/`) walk every stage output fixture and assert: every `Field` has non-null provenance; `source_url` is present unless the method is `computed`/`merged`/`manual_seed`; `confidence` ∈ [0,1]; `evidence` is present for all `llm_extraction` fields.
3. **Export gate.** Stage 7 refuses to write a record with incomplete provenance on any exported field. It fails the record loudly rather than emitting an untraceable lead.

### What this buys

- **GDPR.** Every field answers "where did you get this?" without a manual investigation.
- **Debugging.** A wrong country is traceable to the exact page and snippet that produced it in one lookup.
- **Rubric calibration.** You can measure which sources and methods produce values that survive human review, and reweight accordingly.
- **Trust decay.** A 2024-sourced field and a 2026-sourced field are distinguishable, so the master file can age gracefully instead of silently going stale.

---

## 7. Module Responsibilities

| Module | Single responsibility | Explicitly does NOT |
|---|---|---|
| `domain/models` | Define the system's vocabulary | Touch I/O, network, or vendors |
| `domain/provenance` | The `Field[T]` wrapper and its invariants | Know what fields exist |
| `ports/*` | Declare capability contracts | Contain logic |
| `ports/contact_source` | The one interface every contact source implements | Know about any source |
| `adapters/search/*` | Query → candidate URLs via one provider | Judge quality |
| `adapters/crawl/*` | URL → text, cached and rate-limited | Parse meaning |
| `adapters/llm/*` | Wrap the SDK: retries, structured outputs, caching, token accounting | Own prompts or business rules |
| `adapters/dns/*` | Domain → MX/A records, cached | Decide deliverability |
| `contact/engine` | Schedule tiers, run sources in parallel, evaluate stopping condition | Implement any source |
| `contact/registry` | Discover and enable sources from config | Execute them |
| `contact/budget` | Per-artist cost ceiling and cancellation | Decide source order |
| `contact/sources/*` | One contact-discovery method | Know about other sources or ranking |
| `contact/merge/normalizer` | De-obfuscate, canonicalize, dedupe | Classify or score |
| `contact/merge/ownership` | Artist vs gallery vs institution vs aggregator | Rank or export |
| `contact/merge/corroboration` | Cross-source agreement scoring | Classify ownership |
| `contact/merge/ranker` | Merged candidates → ordered list | Perform lookups |
| `enrichment/evidence_router` | Decide which platforms to consult per artist | Read them |
| `enrichment/readers/*` | Read one evidence platform | Synthesize hooks |
| `pipeline/orchestrator` | Sequence stages, resume, enforce budget | Contain stage logic |
| `pipeline/checkpoint` | Track completed/failed records durably so a stage resumes mid-way | Decide retry policy or stage order |
| `pipeline/stages/*` | One transformation, one input shape, one output shape | Reach into another stage |
| `scoring/*` | Filters, rubric, tiering, email confidence | Perform lookups |
| `identity/*` | Blocking, matching, merge conflict resolution | Extract or score |
| `compliance/*` | Lawful-basis records, suppression | Judge lead quality |
| `observability/source_metrics` | Per-source yield, cost, latency | Alter records or ordering |
| `config/container` | Wire adapters to ports from config | Contain business logic |

---

## 8. SOLID in Practice

**Single Responsibility.** Stages communicate only through files, so the classic `process_artist()` god-function is structurally impossible. Inside stage 5 the split is sharper still: the engine schedules, sources search, the merge layer normalizes → classifies → corroborates → ranks. A source has no idea ranking exists; the ranker has no idea HTTP exists.

**Open/Closed.** This is the requirement your first change targets, and it's now the load-bearing property of stage 5. Adding a browser-agent contact source is: one file implementing `ContactSource`, one entry in `contact_sources.yaml`. No engine change, no pipeline change, no merge change — the new source's results flow through normalization, ownership classification, corroboration, and ranking automatically because it returns the same `ContactCandidate` type as everything else. Source *ordering* is likewise config (`tier:`), not code.

**Liskov Substitution.** Every `ContactSource` returns `ContactSourceResult` and signals failure as a value, never an exception — so one source timing out cannot abort the parallel group. Every `SearchProvider` returns `list[SearchHit]` — the raw hits a search engine yields (url, title, snippet, rank, engine); lifting a hit into a `DiscoveryCandidate` (an artist identity with provenance) is discovery-stage work, not something duplicated inside every provider adapter. Vendor quirks stay inside adapters. Contract tests run one shared suite against every implementation of a port, including every contact source.

**Interface Segregation.** Narrow ports. Stage 6 depends only on `DnsResolver`. A contact source that reads cached content depends on `Cache` alone — not on `Crawler`, `SearchProvider`, or `LLMClient`.

**Dependency Inversion.** `pipeline/` and `contact/engine.py` import only from `ports/` and `domain/`. Concrete adapters and sources are injected at startup by `config/container.py`. The whole pipeline — engine included — is unit-testable with fake sources and zero network calls. Adding paid verification later is one adapter plus a config line.

---

## 9. Key Technical Decisions

**JSONL between stages, CSV only at export.** CSV can't hold nested provenance or exhibition arrays without lossy flattening — and with r3's provenance-on-every-field requirement, that gap widens considerably. Moving to SQLite later is one adapter.

**Content-addressed crawl cache.** A URL is fetched at most once, ever, across runs. Tier 0 of the contact engine reuses stage-3 pages for free.

**Structured outputs everywhere the LLM produces data.** `output_config.format` with a Pydantic schema — schema-valid by construction. No regex, no JSON repair, no retry-on-malformed loop.

**Prompt caching on the qualification rubric and the personalization prompt.** Both are large, byte-stable prefixes reused across every lead; a `cache_control` breakpoint after each cuts input cost on stages 4 and 6b substantially. Requires the prefix to stay genuinely frozen — no timestamps or per-lead interpolation before the breakpoint.

**Batches API for stages 3, 4, and 6b.** Latency is irrelevant for all three; 50% cost reduction is not.

**Tiered parallelism over full parallelism in stage 5.** Running all ten sources concurrently would be fastest and most wasteful. Tiers keep the cost discipline of the waterfall while making the source set open, concurrent within a tier, and reorderable by config alone.

**Ownership classification in the merge layer, not per source.** See §4.5.4 — this is the correction that makes your gallery rule actually hold.

**Model: `claude-opus-4-8` with adaptive thinking for judgment stages.** Career-stage classification, celebrity-tier detection, and ambiguous ownership calls are the highest-leverage, highest-error-rate decisions in the system. A cost-tiered variant (Haiku 4.5 for page triage, Opus for qualification, ownership, and personalization) is a `providers.yaml` change, not a rewrite. Default to Opus, measure, then split if the numbers justify it.

**Nothing qualified is ever discarded.** `rejected_candidates.csv` tunes the rubric; `qualified_without_email.csv` plus master-file status mean a qualified-but-unreachable artist is retried on a later run rather than lost. Outcome 2 is the pool outcome 1 grows from.

**Per-source metrics from run one.** `observability/source_metrics.py` records yield, cost, and latency per source per run. Without it you cannot know whether `whois` earns its tier — and the pluggable design is only as good as your ability to prune it.

---

## 10. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| **Confidence floor set too low to hit a KPI target** | Bounces damage the sending domain, which costs more than the leads gained | `min_email_confidence_band` is config, not code, and every change to it is visible in the run report alongside the KPI it moves; bounces feed back into suppression so the tradeoff becomes measurable rather than theoretical |
| **Gallery address leaks into the leads file** | Violates the core rule; corrupts conversion metrics | Ownership classified per candidate in the merge layer (not per source); `contact_status != "direct"` structurally barred from `completed_leads.csv` by assertion; invariant test asserts no `GALLERY`/`INSTITUTION`/`UNKNOWN` record ever appears there |
| **Ownership misclassification (artist domain hosted by gallery)** | Real artist contact dropped to indirect | Deterministic checks first (own-website domain match, `gallery_domains.yaml`, known representation); LLM fallback with page context; `UNKNOWN` routes to review rather than silently choosing |
| **Parallel sources multiply cost per artist** | Budget | Tiered execution with a stopping condition after each tier; per-artist budget ceiling in `contact/budget.py` with cancellation; expensive sources gated to tier 3 |
| **One slow source stalls a tier** | Throughput | Per-source timeout; outcomes are values not exceptions; the tier proceeds with whatever returned |
| **Provenance overhead balloons record size** | Storage, token cost | `evidence` snippets capped in length; provenance omitted from the LLM's *input* context (it's output metadata, not input); master file compacted periodically |
| **Cost from removing the email pre-filter** | Every crawled page reaches an LLM | Min-content-length gate; cheap single-artist-page triage; Batches API; prompt caching; per-run budget ceiling |
| **Career-stage misclassification** | Core filter fails | Structured exhibition stats as input rather than raw prose; explicit reasoning + confidence on every call; confidence floor routes borderline to review; human spot-check per run |
| **Celebrity tier not detected** | Insulting outreach to a blue-chip artist | Explicit negative signals in the rubric (retrospectives, auction records, major-institution collections) as hard downgrades |
| **Gender inference errors** | Wrong-audience contact, ICP violation | Require explicit textual evidence (pronouns, gendered self-description); never infer from name alone; confidence floor with review queue |
| **No-paid-verification bounce rate** | Sender reputation | Confidence bands exported; send High first; feed bounces back into suppression so the model calibrates against real outcomes |
| **GDPR exposure across the EU/UK block** | Legal | Provenance on every field; `source_url` required at export; lawful-basis record; suppression at write time; retention clock; opt-outs honoured globally |
| **Aggressive contact discovery reads as intrusive** | Reputational | Public sources only — no gated content, no address guessing or permutation, no SMTP probing, WHOIS only on the artist's own domain |
| **Schema drift** | Silent master-file corruption | `schema_version` on every envelope; migration required for version bumps |

---

## 11. Remaining Open Questions

Neither blocks implementation; both are config-level and can be settled during build.

1. **Volume and budget.** Target qualified leads per month, and a per-run spend ceiling. Sizes query expansion and the per-artist contact budget.
2. **Human review queue.** Is there a review step for borderline leads (tier C, low-confidence career stage, `UNKNOWN` ownership, Low-band emails), or does everything flow straight to CSV? Currently the design routes these to flagged columns rather than a separate queue.

---

## 12. Implementation Sequence

1. `domain/` (including `Field[T]` + provenance) + `ports/` + contract and invariant tests — the skeleton everything conforms to
2. `config/` loader + DI container
3. Stages 1–3 with a fake LLM adapter, validated against frozen fixtures
4. Real Anthropic adapter; validate extraction on ~50 hand-checked pages
5. Stage 4 + rubric calibration against a manually scored gold set
6. `contact/engine` + registry + budget, with two trivial sources — prove the plugin contract before writing nine implementations
7. Merge layer: normalizer → **ownership** → corroboration → ranker. Ownership gets its own labelled test set, since the gallery rule depends on it
8. Remaining contact sources, one at a time, measuring yield per source from the first run
9. Stages 6, 6b, 7 — including the export ownership assertion
10. Orchestrator resume, budget caps, run ledger
11. CLI and operational docs

Steps 6–7 before step 8 is deliberate: build the contract and the merge layer against two stub sources first. If the plugin interface is wrong, you want to discover that after writing two sources, not ten.
