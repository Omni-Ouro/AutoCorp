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
- *Demo (25%)* is the 3×3 matrix on video, deployed, with real URLs on screen.
- *Impact (30%)* is narrative: every agent framework, every site fighting bots, one receipt both sides hold. Two slides' worth, in the video and the README.
- *Production (Startup lens)* means deployed on a droplet during judging with tests, error handling, offline queueing and a fresh-clone quickstart that works.

---

## 1. One-paragraph claim

EyD is a thin runtime and a small window. Whatever agent you already use is run through it. The model picks verbs; EyD executes the tool, signs a record of the action under the agent's own Ed25519 key, and reports it to the clearinghouse before the call goes out. The counterparty site reports its side after. The clearinghouse pairs the two, classifies the result (Expected, Unexpected, Declined, Unverified), and issues a signed Proof Receipt to both parties. Agents that don't route through EyD get no receipt. Sites that gate on EyD only admit agents that do.

**Demo in one sentence:** an agent on Meta models tries a gated site bare and is refused; through EyD it's admitted, acts, and both sides get a receipt that says Expected; the site tampers with its response and the receipt says Unexpected; the agent hits a non-EyD site and the window shows Unverified.

## 2. What's open vs. what's yours

| Component | This repo (Apache-2.0) | Omni-Ouro |
|---|---|---|
| EyD runtime (verbs, dispatch, signing, local chain, reporting) | yes | |
| EyD window (receipt viewer) | yes | |
| Proof format v0 (records, reports, receipts) | yes | |
| Verifier / site SDK (attest, report) | yes | |
| Clearinghouse **reference** (single-node pairing + classification + receipts) | yes, marked reference-only | hosted PoT Clearinghouse: multi-tenant, site webhooks, PoT reports, the data on which sites agents use |
| Demo sites (three companies) | yes | |
| Agent demo (Meta models) | yes | |
| Any governance or policy over agent actions | | Eyro |
| Full on-prem audit trail with inputs/outputs | | Eyro |

The hook stays intact: the open pieces prove hashes and classify agreement; only Eyro holds the full trail. The hosted clearinghouse sees intents before anyone else, which is the market data.

## 3. Components

### 3.1 EyD runtime (`eyd/`)
Local process. Two ways in:
- **Launcher mode:** `eyd run <agent command>` — starts the agent with EyD as its tool endpoint and opens the window.
- **Proxy mode:** EyD exposes an MCP server; the agent's framework points at it. EyD forwards to the real MCP servers and HTTP tools behind it.

Per call:
1. Resolve `verb.tool`.
2. Build Action Record, sign, compute `record_hash`, append to local chain.
3. **Report intent** to clearinghouse (`POST /intents`). Window shows the action as *pending*.
4. Execute the tool with headers `EyD-Agent: <agent_id>`, `EyD-Record: <record_hash>` and, inside an attested session, `EyD-Session: <token>`. One Action Record per tool invocation; if the invocation makes several HTTP requests (redirects, pagination, retries), every one carries the same headers and the site reports on whichever hits its gated endpoint.
5. Hash the response, **report outcome** (`POST /reports/agent`). Window shows *awaiting counterparty*.
6. Receive Proof Receipt (push over a persistent connection, or poll). Window shows the classification.

If the clearinghouse is unreachable, the action still runs and is still chained locally; the report is queued and retried. Local chain is the source of truth; the clearinghouse is the referee.

**Transparency.** The agent never learns EyD exists. Verbs are presented as the agent's own tools, tool results come back unmodified, attestation headers and challenge handling happen entirely inside EyD, and no tool result, error, or system text ever names EyD. The only thing an agent ever sees that relates to EyD is a site's refusal, and that refusal names a **PoT score**, not EyD (Section 3.10).

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

### 3.7 Demo sites (`demo-sites/`)
Three fake companies, one codebase, three configs. Each exposes the same action ("submit a quote request") and a dashboard.

| Company | Behavior | Config |
|---|---|---|
| **All Agents Welcome Inc** | Doesn't know EyD exists. Admits everything, reports nothing. | no middleware |
| **EyD Required LLC** | Requires an attested EyD. Any score, including none yet. | `require_eyd()` |
| **Only Proven Agents PLC** | Requires an attested EyD with PoT score ≥ threshold. | `require_eyd(min_score=0.8)` |

- Refusal → `403`, body `{"error":"refused","reason":"PoT score unknown"}` or `"PoT score below threshold"`, challenge in `EyD-Challenge` / `EyD-Clearinghouse` headers. The agent sees only the body.
- Admission → `200`, performs the action, reports to clearinghouse (sites 2 and 3), stores receipt.
- Dashboard per site: agents seen, actions, classification, receipt detail. Sites 2 and 3 have a **tamper** toggle that alters the response after hashing so the next receipt reads Unexpected.

### 3.8 Demo agents (`agent-demo/`)
One Meta-model agent, three identities. The agent's code contains no reference to EyD; the only difference between runs is whether it's launched bare or via `eyd run`, and which key EyD loads.

| Agent | Setup | Seeded history |
|---|---|---|
| **A** | launched bare | none (no key, no enrollment) |
| **B** | `eyd run`, key B | mixed: many Unexpected and Declined, score ≈ 0.4 |
| **C** | `eyd run`, key C | long clean run, score ≈ 0.97 |

`clearinghouse-ref seed fixtures/history.json` loads B's and C's past receipts before the demo so scores exist on day one. The fixture is labeled **demo data** in the file, the README, the dashboards and the video narration; nothing in it is presented as a real history.

### 3.9 Demo matrix
Nine runs, in this order on screen:

| | All Agents Welcome Inc | EyD Required LLC | Only Proven Agents PLC |
|---|---|---|---|
| **A** no EyD | Admitted. Nothing recorded. | Refused: *PoT score unknown* | Refused: *PoT score unknown* |
| **B** low score | Admitted. **Unverified** | Admitted. **Expected** | Refused: *below threshold*. **Declined** |
| **C** high score | Admitted. **Unverified** | Admitted. **Expected** | Admitted. **Expected** |

Then one tamper run: C against EyD Required LLC with the toggle on → **Unexpected**. Every classification and both refusal reasons appear within about ninety seconds. Narration reads left to right: a site that ignores EyD learns nothing even from a good agent; a site that requires it keeps unknowns out; a site that gates on score keeps the unreliable ones out too.

Cheapest adequate model throughout; credits barely touched.

### 3.10 PoT score
The per-agent aggregate the clearinghouse derives from receipts. v0 is deliberately simple: counts of Expected / Unexpected / Declined / Unverified, total actions, first and last seen, and a single number `score` = Expected ÷ (Expected + Unexpected + Declined), or `null` with fewer than N receipts. Sites may gate on it (`require_eyd(min_score=…)`).

**Refusal wording.** When a site refuses an agent for any EyD-related reason, the body the agent sees is the same every time:
```json
{"error": "refused", "reason": "PoT score unknown"}
```
That is the entire surface EyD presents to an agent that isn't using it. The agent, or whoever reads its logs, learns a score exists and that this site requires one. No mention of EyD, the clearinghouse, or how to get a score; that discovery is the operator's, and the operator finds Omni-Ouro. An agent that *is* enrolled but below a site's threshold sees `"reason": "PoT score below threshold"`. Nothing else is ever disclosed.

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
  "sig": "ed25519:…"
}
```
`target` is the counterparty domain, a known `site_id`, or `local`. `record_hash` = SHA-256 of canonical JSON of all fields except `sig`. `sig` = Ed25519 over `record_hash`. Note `output_hash` is **not** in the record; it goes in the agent report, because the record is created and reported before execution.

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
eyd/                 runtime (identity, chain, verbs, dispatch, mcp proxy, reporter, cli)
eyd-ui/              window
verifier/            python/ ts/
clearinghouse-ref/   single-node pairing, classification, receipts
demo-sites/          three companies, one codebase, dashboards, tamper toggle
agent-demo/          Meta-model agent, three keys, nine runs
fixtures/            seeded receipt history for agents B and C
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
| 2 | Tue Oct 27 | Runtime: verbs, HTTP dispatch, MCP passthrough, `eyd run`, intent + agent report (to a stub). Check which Meta models and agent products are on the API; pick the demo model. |
| 3 | Wed Oct 28 | Clearinghouse-ref: enroll, intents, both reports, pairing, classification, receipts, push, score. **Kill point:** one action goes agent → EyD → intent → tool → agent report → (fake site report) → receipt in the terminal, or stop and return to Eyro. |
| 4 | Thu Oct 29 | Verifier: attestation, `report`, `verify_receipt`, `require_eyd(min_score)`. Challenge/response in runtime. |
| 5 | Fri Oct 30 | Demo sites: one app, three configs, dashboards, tamper toggle. Seed fixture + `seed` command. **Deploy clearinghouse-ref and the three companies to a droplet with real URLs.** |
| 6 | Sat Oct 31 | EyD window: live list, status transitions, receipt detail. Agent demo on Meta models, first full run of the matrix against the deployed sites. |
| 7 | Sun Nov 1 | Hardening: replay, timestamp window, late reports, offline queue, error paths. End-to-end tests. Wrap a Meta-built agent through `eyd run` if one is available. **Shoot the demo video** (Section 7) once the matrix runs clean. |
| 8 | Mon Nov 2 | README (What we built / What we didn't build / quickstart / impact), spec, architecture diagram. Re-shoot video if anything changed. TS verifier if time. |
| 9 | Tue Nov 3 | Buffer. Fresh-clone quickstart on a clean droplet by someone who isn't you, if possible. Submission form filled, video uploaded, repo link checked while logged out. |
| — | Wed Nov 4 | Submit by 8:00 PM CT. Nothing new after noon. Live-finals pitch outline (3 min) drafted in the afternoon. |

If the window slips, it moves to Day 8 and the terminal output stands in for it in the video. The receipt flow, the deployed sites and the video cannot slip.

## 7. Demo video script (3:00)

| Time | On screen | Voice |
|---|---|---|
| 0:00–0:20 | Title. One line: "Agents act on your behalf. Nobody can prove what they did." | The problem: every agent framework ships tools with no provenance, and every site has no way to tell a good agent from a bad one. |
| 0:20–0:45 | Architecture diagram, 3 boxes: agent → EyD → site, clearinghouse above. | What EyD is: a thin runtime on the agent's device. Model picks verbs, EyD signs every action, reports before it runs, the site reports after, the clearinghouse pairs both and issues a receipt to each side. The agent never knows EyD exists. |
| 0:45–1:00 | The three companies, side by side, URLs visible. | Three real deployed sites: one that ignores EyD, one that requires it, one that requires a score. |
| 1:00–2:15 | The 3×3 matrix, filled in live, one cell every ~8s. EyD window visible for B and C. | Agent A bounced twice with "PoT score unknown." B gets in at Required, refused at Proven, receipts show Expected and Declined. C gets in everywhere, Unverified at Welcome because the site never reported. Then the tamper toggle: C's next receipt reads Unexpected. |
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
