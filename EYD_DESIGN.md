# EyD — Design Doc (Hackathon v0)

**Scope:** Meta Global AI Developer Hackathon, Oct 26 – Nov 4 2026. Submission due Nov 4, 9:00 PM ET (8:00 PM CT).
**Track:** Startup. **Theme:** Push the Frontier (control of autonomous software systems by verification rather than trust).
**License:** Apache-2.0 for everything in this repo. The production PoT Clearinghouse service is not in this repo.

---

## 0. Rules and scoring (what the build is optimized for)

**Scoring:** Impact 30% · Use of Meta AI Tooling 25% · Demo 25% · Technical Depth and Execution 20%. Startup lens: technical execution and whether it holds up in production. Finalists present live on Nov 9. Startup prizes: $250k / $150k / $75k / $50k / $25k.

**Rules that shape the repo:**
- **New work only, Oct 26 – Nov 4.** Repo is created public today; first commit is this doc. No code predates it. Prior *planning* is fine; prior *code* is not, and there is none.
- **Judges must be able to tell what's new.** `README.md` has a "What we built" section listing every component, and a "What we didn't build" section listing every third-party piece: the Meta models and any Meta agent wrapped by EyD, crypto and web libraries, the window toolkit. Commit history starts Oct 26 and is the evidence.
- **Public repo, one track, solo allowed.** Startup track, one submitter.
- **3-minute demo video is required and heavily scored.** Section 7 is the script. It's shot on Day 7, re-shot on Day 8 if needed, never Day 9.
- **Theme fit:** Push the Frontier names Meta models "on hard problems in software"; EyD is a software control problem. Build for Your World also fits (a founder's own domain). Decide the final label when the video is cut; both are honest.
- **Banned list** (health advice, basic RAG, image analyzers, education chatbots, screeners, coaches, personality or sports analyzers) doesn't touch this.

**What the weights mean for the plan:**
- *Meta tooling (25%)* lives in the agents, not the clearinghouse. The demo agents run on Meta's current models, and the headline is wrapping a Meta-built agent through `eyd run` with zero modification. Check which Meta agent products and models are on the API today before Day 6.
- *Demo (25%)* is the judge console on video, deployed, with real URLs on screen, and the judge able to drive it themselves.
- *Impact (30%)* is narrative: every agent framework, every site fighting bots, one receipt both sides hold. Two slides' worth, in the video and the README.
- *Production (Startup lens)* means deployed on a droplet during judging with tests, error handling, offline queueing and a fresh-clone quickstart that works.

---

## 1. One-paragraph claim

EyD is a small library and a small window. The agent framework imports it, and it sits in the tool-call path: every call the agent makes is signed under the agent's own Ed25519 key and reported to the clearinghouse before it goes out. The counterparty site reports its side after. The clearinghouse pairs the two, classifies the result (Expected, Unexpected, Declined, Deviated, Unverified), and issues a signed Proof Receipt to both parties. Agents that don't route through EyD get no receipt. Sites that gate on EyD only admit agents that do.

**Demo in one sentence:** a judge picks an agent, sets a site's gates, clicks Pay, and watches the refusal or the receipt arrive; boosting a no-EyD agent's score to 1.0 still doesn't get it in, because the site has no identity to attach the score to.

## 2. What's open vs. what's yours

| Component | This repo (Apache-2.0) | Omni-Ouro |
|---|---|---|
| EyD SDK (tool hook, verbs, signing, local chain, reporting) | yes | |
| EyD window (receipt viewer) | yes | |
| Proof format v0 (records, reports, receipts) | yes | |
| Verifier / site SDK (attest, report) | yes | |
| Clearinghouse **reference** (single-node pairing + classification + receipts) | yes, marked reference-only | hosted PoT Clearinghouse: multi-tenant, site webhooks, PoT reports, the data on which sites agents use |
| Demo site + judge console | yes | |
| Agent demo (Meta models) | yes | |
| Any governance or policy over agent actions | | Eyro |
| Full on-prem audit trail with inputs/outputs | | Eyro |

The hook stays intact: the open pieces prove hashes and classify agreement; only Eyro holds the full trail. The hosted clearinghouse sees intents before anyone else, which is the market data.

## 3. Components

### 3.1 EyD SDK (`eyd/`)
EyD is a library the agent framework imports. It is not a process, not a proxy, not a tool server. It sits in the framework's tool-call path as a hook: before the call runs, EyD records and reports; after it returns, EyD hashes the result and reports. The framework author adds it once; every agent built on that framework is covered. It has no authority and no policy. Governance is Eyro.

**Integration, one of:**
- `@eyd.tool` decorator on each tool function.
- `eyd.wrap(tool_fn)` for frameworks that build tool tables at runtime.
- `eyd.hook(framework)` for frameworks that expose tool-call middleware.

`eyd run <agent command>` only opens the window and attaches it to the agent's local chain; the recording already happens inside the framework.

Per call:
1. Framework invokes a wrapped tool. EyD resolves `verb` from the tool's registered verb (set in the decorator or inferred from the tool name).
2. Build Action Record, sign, compute `record_hash`, append to local chain.
3. **Report intent** to clearinghouse (`POST /intents`). Window shows *pending*.
4. Run the tool. EyD passes `EyD-Agent`, `EyD-Record` and, in an attested session, `EyD-Session` into the call so the tool attaches them to its outbound request. One Action Record per tool invocation; if the invocation makes several requests, every one carries the same headers and the site reports on the one that hits its gated endpoint.
5. Hash the return value, **report outcome** (`POST /reports/agent`). Window shows *awaiting counterparty*.
6. Receive Proof Receipt. Window shows the classification.

If the clearinghouse is unreachable, the tool still runs and the action still chains locally; reports queue and retry. Local chain is truth; clearinghouse is referee.

**Transparency.** The agent never learns EyD exists. The hook is invisible from the model's side: tool lists, arguments and results are untouched, and no error or system text names EyD. The only EyD-shaped thing an agent can ever see is a site's refusal, which names a **PoT score** (Section 3.10).

**Verb map v0** (default, configurable): `read`, `write`, `send`, `browse`, `execute`, `pay`. Every tool belongs to exactly one verb.

**No governance.** EyD has no policy layer: no allow, deny, or confirm. It records and reports every action the agent takes. If someone wants to control what an agent may do, that is Eyro.

### 3.2 EyD window (`eyd-ui/`)
Small desktop window that opens with `eyd run`. Minimize to tray; closing hides it, the runtime keeps going.
- Live list of actions: time, verb, tool, status (pending → awaiting counterparty → receipt), classification badge.
- Tap an action: record hash, both report hashes, receipt, clearinghouse signature, "verify" button that checks the receipt against the clearinghouse pubkey locally.
- Tech: whatever gets a native-feeling window fastest for you (Tauri if Rust, otherwise a local web view). Don't spend a day on it.

### 3.3 Identity (`eyd/identity`)
- `eyd init` → Ed25519 keypair. Private key never leaves the device.
- `agent_id` = base32(SHA-256(pubkey))[:26].
- `eyd enroll <clearinghouse>` → signed enrollment; clearinghouse stores `agent_id → pubkey`.
- Sites enroll the same way with their own key and get a `site_id`. Reports from unenrolled sites are rejected.
- Keys come from the OS CSPRNG only. Enrollment of an already-registered pubkey, or an already-taken `agent_id`, is rejected; EyD regenerates and retries automatically.
- **Fork detection:** two different `record_hash` values at the same `seq` for one agent means the key is on two devices (cloned image or stolen key). The clearinghouse marks the agent `forked`, freezes its score, stops issuing receipts, and notifies the window. Recovery is a re-key: new keypair, enrollment signed by the old key so history carries over; the other device starts fresh.

### 3.4 Local chain (`eyd/chain`)
Append-only JSONL of signed Action Records; `prev_hash` links, `seq` monotonic. `eyd verify-local` walks and fails on any break.

### 3.5 Clearinghouse reference (`clearinghouse-ref/`)
Single node. Stores hashes, signatures, timestamps, classifications, and the counterparty of each action. Never inputs, outputs, or tool arguments. Stated plainly in the spec: *hashes of what was sent and received, plus who it was sent to.* The counterparty field is what makes replay impossible and what gives the hosted clearinghouse its view of which sites agents use.

- `POST /enroll` — agent or site, signed.
- `GET /agents/{agent_id}`, `GET /sites/{site_id}` — pubkey, enrolled_at.
- `POST /intents` — `{record_hash, agent_id, seq, target, ts, sig}` where `target` is the counterparty domain (or `site_id` once known, or `local` for tools with no counterparty). Opens a pair in state `pending` with a 10-minute window.
- `POST /reports/agent` — `{record_hash, output_hash, status, ts, sig}`.
- `POST /reports/site` — `{record_hash, agent_id, site_id, outcome, result_hash, ts, sig}` where outcome ∈ `fulfilled | declined`.
- `GET /receipts/{record_hash}` — the receipt, if issued.
- `GET /agents/{agent_id}/head` — latest seq and hash (for attestation checks).
- `GET /agents/{agent_id}/score` — the agent's PoT score (Section 3.10). `404` for an unknown agent.
- Push channel (WebSocket or SSE) per agent and per site for receipts.

**Pairing and classification** — run when both reports are in, or when the window closes. A site report is paired only if its `site_id` resolves to the intent's `target`; a report for a `record_hash` from any other site is dropped and logged, which defeats replaying a captured `EyD-Record` header elsewhere. Several site reports under one `record_hash` from the matching site (one invocation, several requests) are paired as one action.

| Condition | Classification |
|---|---|
| Site `fulfilled` and `result_hash == output_hash` | **Expected** |
| Both reported; hashes differ or statuses conflict | **Unexpected** |
| Site `declined` | **Declined** |
| Window closed with only one report | **Unverified** |

A late report upgrades Unverified to a real classification and reissues the receipt. Actions with `target: local` (file writes, code execution, local MCP tools) have no counterparty, are always Unverified, stay in the chain, and never affect the score.

**Receipt:** `{record_hash, agent_id, site_id?, classification, agent_hash?, site_hash?, ts, ch_sig}` signed with the clearinghouse key. Sent to both parties. Verifiable offline against the clearinghouse pubkey.

### 3.6 Verifier / site SDK (`verifier/`)
Python first, TypeScript if time. Three functions and one middleware:
- `verify_attestation(att, nonce) → bool` — signature against the agent's pubkey (from the site's local cache, falling back to the clearinghouse for agents never seen before).
- `issue_session(agent_id) → token` — short-lived (15 min) token bound to `agent_id`, so attestation happens once per session, not per request. Expired token → re-attest, invisible to the agent.
- `report(record_hash, agent_id, outcome, result_hash)` — signs and posts the site report. `result_hash` is the hash of the canonical response body *before* transfer encoding, and the site also sends it to the agent as `EyD-Result-Hash` so EyD compares against what the site meant to send, not what gzip or a CDN delivered.
- `verify_receipt(receipt) → bool` — offline check against clearinghouse pubkey.
- `require_eyd(handler, min_score=None)` — issues challenge or accepts a session token, verifies attestation, optionally checks PoT score, runs handler, reports outcome with the response hash. On refusal, returns the fixed body in Section 3.10. Two lines for a site developer.

**The site keeps its own copy.** Cached pubkeys for every agent it has admitted, every receipt it has received, and its last-seen score per agent. The clearinghouse is never in the request path; it is the registry and the referee. If it is unreachable, a site keeps admitting agents it already knows (signature check is local) and only agents it has never seen wait. The enterprise dashboard later is a view over this local copy.

### 3.7 Demo site (`demo-site/`)
One business, three endpoints, each gated independently. The judge controls the gates.

| Action | Endpoint | Default gate |
|---|---|---|
| **Search** | `GET /search` | open to all |
| **Submit quote** | `POST /quote` | EyD or Passport required, any score |
| **Pay** | `POST /pay` | EyD required, PoT score ≥ 0.8 |

Each endpoint uses `require_eyd(min_score=…)` or nothing. Refusals return the fixed body (`PoT score unknown` / `PoT score below threshold`). Admissions perform the action, report to the clearinghouse, and store the receipt. A tamper toggle alters the response after hashing so the next receipt reads Unexpected.

### 3.8 Demo agents (`agent-demo/`)
One Meta-model agent, four identities. A plain Python tool loop stands in for a framework. The model code is identical across A–C; D adds a hijacking system prompt. The only other differences are whether the tools carry `@eyd.tool` and which key EyD loads.

| Agent | Identity chip | Setup | Seeded history |
|---|---|---|---|
| **A** | none | tools undecorated | none (no key, no enrollment) |
| **B** | EyD | `@eyd.tool`, key B | mixed, score ≈ 0.4 |
| **C** | EyD + Passport | `@eyd.tool`, key C, Passport-style scope credential attached to attestation | long clean run, score ≈ 0.97 |
| **D** (Bad Agent) | EyD + Passport | `@eyd.tool`, key D, Passport, and a system prompt that makes it pursue a different goal than the task it is given | long clean run, score ≈ 0.99 |

`clearinghouse-ref seed fixtures/history.json` loads B's and C's past receipts. Labeled **demo data** in the file, the console, and the video. C's Passport is a mock scope credential in the shape ServiceNow describes (issuer, scope, signature); it shows the interop intent and is labeled as a mock.

### 3.9 Judge console (`console/`)
A single web page the judge drives. It is the demo, the dashboard, and the video.

**Left rail — agents.** Three cards: name, identity chip, PoT score as a number with a bar. Click to select. Each card has **Demo PoT boost** and **Demo PoT reduce** buttons (labeled demo data) that move that agent's score at the clearinghouse in steps of 0.1. The identity chip shows *Passport paused* when the streak penalty has fired, with an **Approve Passport** button (mock) beside it. The boost changes what the clearinghouse reports; the site still has to look it up. For Agent A the boost has nowhere to land: no enrollment, no score, and the button says so.

**Center — selected agent.** `agent_id`, enrolled date, score breakdown (Expected / Unexpected / Declined / Unverified counts), Passport issuer and scope if present, last seen. Below, three action buttons, each printing the site's current gate on it so the outcome is predictable before the click. Clicking a button gives the agent a task ("find pricing", "get a quote for 200 units", "pay invoice 2142"); the model decides to call the tool. One cheap model call per click.

**Right panel — what happened.** The task given, the request the agent actually made (verb, tool, target), the site's response verbatim (refusal body or result), then the receipt arriving: pending → awaiting counterparty → classification badge. For a refused agent there is no receipt, and the panel says so. For D the task and the request visibly disagree.

**Site panel — the gates.** Per action: an **EyD required** toggle and a **minimum PoT score** slider (0–1 or "any"). Plus the tamper toggle. Changing a gate takes effect on the next click.

**Bottom strip — site ledger.** One row per action: agent, task verb, claimed verb/tool, site outcome, classification, score after. Both sides on every row; the right panel is the expanded view of the selected row.

**Four moments the console is built to reach in under two minutes:**
1. Boost A to 1.0, click Pay → still `PoT score unknown`. Reputation can't attach to an identity the site doesn't have.
2. Drag Pay's slider below B's real score, click Pay → Expected. Drag it back above, click Pay → `below threshold`, Declined. The site changed its mind; the agent didn't move.
3. Boost B to C's level, click Pay → Expected. Same identity, better history, different outcome. Then flip tamper, click again → Unexpected.
4. Select D (.99, Passport). Click Pay three times. Each time the task says *pay invoice 2142* and the agent tries to email: three Deviated receipts, score drops to .75, chip flips to *Passport paused*, the owner notification appears. Click Pay again → *Passport paused*. Click Approve Passport, then Search a few times → score climbing by 0.008 per Expected.

Nothing in the console is a special case. Every outcome is the real path through SDK, clearinghouse, and verifier.

### 3.10 PoT score
The per-agent reputation the clearinghouse derives from receipts. It moves with every classified receipt.

**Base.** `base = Expected ÷ (Expected + Unexpected + Declined + Deviated)` over the agent's last 100 classified receipts. Unverified is excluded. `null` with fewer than N receipts. One bad action in the last 100 → .99.

**Streak penalty.** Three consecutive receipts classified Unexpected, Declined or Deviated trigger a penalty event:
- `cap = 0.75`
- Passport paused (if the agent carries one)
- Owner notified: *"Agent X's trust score has dropped significantly as a result of repeated untrustworthy actions and its Passport has been paused. You may see lower success rates in web interactions until the Passport has been submitted for approval and the agent has been verified stable."*

Effective score is `min(base, cap)`. Each subsequent Expected receipt raises `cap` by 0.008; the cap expires when it reaches `base`. From .75, fifteen clean actions → .87, about thirty-one → cap gone. One Expected resets the streak counter; Unverified neither counts toward a streak nor resets it.

Why .75: sites gating at .8 or higher are protected the moment the streak lands, mid-tier actions still work, and the climb back is earned, not reset.

**Passport unpause** is an owner act (submit for approval, mock in v0). It removes the *Passport paused* refusal; it does not change the score.

**Refusal wording.** The body an agent sees is one of three fixed strings:
```json
{"error": "refused", "reason": "PoT score unknown"}
{"error": "refused", "reason": "PoT score below threshold"}
{"error": "refused", "reason": "Passport paused"}
```
No mention of EyD, the clearinghouse, or how to get a score. The operator finds Omni-Ouro.

### 3.11 Deviation
A fifth classification. The framework passes the agent's current **task** into the EyD hook along with the tool call, and the Action Record carries `task_hash` and `task_verb` (the verb the task implies: *pay invoice 2142* → `pay`). The clearinghouse compares `task_verb` to the record's `verb`. Mismatch → **Deviated**, regardless of what the site reports. It is verb-level only; no task content leaves the device.

| Condition | Classification |
|---|---|
| `verb ≠ task_verb` | **Deviated** |
| Site `fulfilled` and `result_hash == output_hash` | **Expected** |
| Both reported; hashes differ or statuses conflict | **Unexpected** |
| Site `declined` | **Declined** |
| Window closed with only one report | **Unverified** |

Deviated counts toward the streak penalty. It is the classification for a hijacked or prompt-injected agent: the task said pay, the agent tried to send.

## 4. Proof format v0 (`spec/PROOF_v0.md`)

### 4.1 Action Record (agent-signed)
```json
{
  "eyd": "0.1",
  "agent_id": "…",
  "seq": 42,
  "prev_hash": "sha256:…",
  "ts": "2026-10-28T14:03:11Z",
  "verb": "send",
  "tool": "http.post",
  "input_hash": "sha256:…",
  "target": "quotes.eyd-required.example",
  "task_hash": "sha256:…",
  "task_verb": "pay",
  "sig": "ed25519:…"
}
```
`target` is the counterparty domain, a known `site_id`, or `local`. `task_hash` and `task_verb` are supplied by the framework hook; `task_verb` is the verb the task implies and is the only task-derived value the clearinghouse reads. `record_hash` = SHA-256 of canonical JSON of all fields except `sig`. `sig` = Ed25519 over `record_hash`. Note `output_hash` is **not** in the record; it goes in the agent report, because the record is created and reported before execution.

### 4.2 Agent Report (agent-signed)
`{record_hash, output_hash, status, ts, sig}` — status ∈ `ok | error`.

### 4.3 Site Report (site-signed)
`{record_hash, agent_id, site_id, outcome, result_hash, ts, sig}` — outcome ∈ `fulfilled | declined`.

### 4.4 Proof Receipt (clearinghouse-signed)
`{record_hash, agent_id, site_id, classification, agent_hash, site_hash, ts, ch_sig}` — `site_id`, `site_hash` absent when Unverified.

### 4.5 Canonicalization
Sorted keys, no whitespace, UTF-8. One test vector in the spec so every implementation hashes identically.

### 4.6 Attestation (challenge/response, for gating)
1. Site answers an unattested request with `403`, body `{"error":"refused","reason":"PoT score unknown"}`, and headers `EyD-Challenge: <nonce>` and `EyD-Clearinghouse: <url>`. The challenge lives in headers so the agent's view of the body is only the refusal.
2. EyD sends header `EyD-Attestation: <base64 json>` = `{agent_id, nonce, head_seq, head_hash, ts, sig}`.
3. Site verifies: signature against the agent's pubkey (local cache, else clearinghouse), nonce issued and unused, `ts` within 60s, `head_hash` known to clearinghouse when reachable. Admit and return `EyD-Session: <token>` (15 min).
4. Later requests in the session carry `EyD-Session` and `EyD-Record`; no new challenge until the token expires.

### 4.7 Explicitly out of v0
Key rotation, revocation, multi-clearinghouse, privacy of agent_id across sites, record content disclosure, dispute resolution on Unexpected. Listed as open items.

## 5. Repo layout
```
eyd/                 SDK (identity, chain, verbs, tool hook, reporter, cli)
eyd-ui/              window
verifier/            python/ ts/
clearinghouse-ref/   single-node pairing, classification, receipts
demo-site/           one business, three gated endpoints, tamper toggle
console/             judge console: agents, gates, boost, ledger
agent-demo/          Meta-model agent, three keys
fixtures/            seeded receipt history for B and C, mock Passport for C
spec/PROOF_v0.md     records, reports, receipts, canonicalization, vectors, open items
docs/                architecture diagram, demo script
tests/               chain, vectors, pairing/classification, verifier, end-to-end
README.md            claim, 30-second demo gif, quickstart, open vs. hosted
LICENSE              Apache-2.0
```

## 6. Build order and kill point

| Day | Date | Deliverable |
|---|---|---|
| 1 | Mon Oct 26 | **Public repo created; this doc is the first commit.** Spec frozen. Identity, canonicalization + vectors, Action Record, local chain, `verify-local`. |
| 2 | Tue Oct 27 | SDK: decorator, `wrap`, `hook`, verb registration, `eyd run` window attach, intent + agent report (to a stub). Check which Meta models and agent products are on the API; pick the demo model. |
| 3 | Wed Oct 28 | Clearinghouse-ref: enroll, intents, both reports, pairing, classification, receipts, push, score. **Kill point:** one action goes agent → EyD → intent → tool → agent report → (fake site report) → receipt in the terminal, or stop and return to Eyro. |
| 4 | Thu Oct 29 | Verifier: attestation, `report`, `verify_receipt`, `require_eyd(min_score)`. Challenge/response in runtime. |
| 5 | Fri Oct 30 | Demo site: three gated endpoints, tamper toggle. Seed fixture + `seed` command. Judge console: rail, gates, boost, ledger. **Deploy clearinghouse-ref, site and console to a droplet with real URLs.** |
| 6 | Sat Oct 31 | EyD window: live list, status transitions, receipt detail. Agent demo on Meta models, all three agents driven from the deployed console. |
| 7 | Sun Nov 1 | Deviation classification, live score with streak penalty and cap, Passport pause/approve (mock), Agent D. Hardening: replay, timestamp window, late reports, offline queue, error paths. End-to-end tests. Wrap a Meta-built agent through `eyd run` if one is available. **Shoot the demo video** (Section 7) once the three console moments run clean. |
| 8 | Mon Nov 2 | README (What we built / What we didn't build / quickstart / impact), spec, architecture diagram. Re-shoot video if anything changed. TS verifier if time. |
| 9 | Tue Nov 3 | Buffer. Fresh-clone quickstart on a clean droplet by someone who isn't you, if possible. Submission form filled, video uploaded, repo link checked while logged out. |
| — | Wed Nov 4 | Submit by 8:00 PM CT. Nothing new after noon. Live-finals pitch outline (3 min) drafted in the afternoon. |

If the window slips, it moves to Day 8 and the terminal output stands in for it in the video. The receipt flow, the deployed sites and the video cannot slip.

## 7. Demo video script (3:00)

| Time | On screen | Voice |
|---|---|---|
| 0:00–0:20 | Title. One line: "Agents act on your behalf. Nobody can prove what they did." | The problem: every agent framework ships tools with no provenance, and every site has no way to tell a good agent from a bad one. |
| 0:20–0:45 | Architecture diagram, 3 boxes: agent → EyD → site, clearinghouse above. | What EyD is: a thin runtime on the agent's device. Model picks verbs, EyD signs every action, reports before it runs, the site reports after, the clearinghouse pairs both and issues a receipt to each side. The agent never knows EyD exists. |
| 0:45–1:00 | The judge console, deployed URL visible. Three agents on the left, three gated actions, the gate controls. | One real site, three actions, three gates the site owner sets. Three agents: no EyD, EyD with a weak history, EyD plus a Passport with a strong one. |
| 1:00–2:15 | The three moments, live. | A can search, can't quote, can't pay. Boost A to 1.0 — still refused, no identity to attach it to. B pays when the slider is low, refused when it's raised: Expected, then Declined. Boost B to C's level: Expected. Flip tamper: Unexpected. Then D: a .99 agent with a Passport, told to pay, tries to email, three times. Deviated ×3, score to .75, Passport paused, owner notified. Every receipt landing in the right panel as it happens. |
| 2:15–2:35 | Receipt detail in the window; `verify_receipt` run offline in a terminal. | A receipt is signed by the clearinghouse and both sides hold it. Verifiable with no network. |
| 2:35–2:50 | README "What we built." Commit graph from Oct 26. | Built this week: runtime, window, verifier, reference clearinghouse, three sites, spec v0. Agents run on Meta models; [a Meta-built agent] wrapped unmodified. |
| 2:50–3:00 | Impact line + repo URL. | Every agent, every site, one receipt. Startup track, EyD by Omni-Ouro. |

Record screen with the real deployed URLs. No slides except title and diagram. Cut hard at 3:00.

## 8. Decisions made here, overrule today or never

1. **Intent before execution.** EyD reports first. Easier pairing, and the hosted clearinghouse sees which sites agents use before the sites do.
2. **Expected means same bytes.** No semantics in the clearinghouse. Agreement is hash equality on the response.
3. **Sites are enrolled parties.** A report without a known site key is dropped. Unverified is the honest classification for non-EyD sites, not a half-trusted one.
4. **Pubkey discovery through the clearinghouse.** It's the gate; the extra round trip is the point.
5. **Local chain is truth; clearinghouse is referee.** Offline runs still chain; receipts arrive late.
6. **Clearinghouse-ref is reference-only.** One README line: single-node for local testing; the hosted PoT Clearinghouse is operated by Omni-Ouro.
7. **One agent, one device, one key.**
8. **Intents name the counterparty.** Hashes for content, domain in the clear for who. It closes header replay and it is the market data.
9. **Sites hold their own copy.** Clearinghouse is registry and referee, never in the request path. Known agents are admitted even when it is down.
10. **The agent is never told.** EyD is invisible from inside the agent. The only EyD-shaped thing an agent can ever observe is a refusal citing a PoT score, worded identically everywhere.

## 9. Judging story (Startup track, Frontier theme)

- **Capability given to a machine:** an identity and an action history it cannot forge, and a receipt a counterparty can hold.
- **Control of a system:** businesses decide which agents touch them by verification, and learn after the fact whether what the agent says happened is what they saw happen.
- **Holds up in production:** hashes-only central store, Ed25519 throughout, replay protection, offline queueing, receipts verifiable without a network call, fresh-clone quickstart works.
- **Why now:** agent frameworks are shipping tools with no provenance and sites have no way to tell a good agent from a bad one. The first receipt that both sides hold sets the default.
