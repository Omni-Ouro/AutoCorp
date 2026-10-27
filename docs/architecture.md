# Architecture

```
                ┌────────────────────────┐
                │      Clearinghouse      │  registry + referee
                │ enroll · intents ·      │  hashes only, never content
                │ reports · receipts ·    │
                │ PoT score               │
                └▲──────────┬──────────┬─▲┘
        intent     │  receipt │  site    │ │ pubkey/score lookup
        (before)   │          │  report  │ │ (cached at the site)
                ┌──┴──────────▼──┐   ┌───┴────────────┐
                │  EyD runtime   │   │      Site       │
                │ sign · chain · ├─► │ require_eyd()   │
                │ dispatch       │◄─┤ report outcome  │
                └─▲──────────────┘   └─────────────────┘
                  │ verbs presented as its own tools
                ┌─┴──────────────┐
                │  Any agent     │  never learns EyD exists;
                │  (Meta models) │  only ever sees a PoT refusal
                └────────────────┘
```

- Intent is reported **before** execution; outcome after. Site report is
  paired only if the site resolves to the intent's target (replay defence).
- Classification: Expected (hashes match) · Unexpected · Declined · Unverified.
- Local chain is the source of truth; the clearinghouse is the referee.
  Offline actions still chain and queue their reports.
- The clearinghouse is never in a site's request path: known agents are
  admitted on a local signature check even when it is down.

Spec: [../spec/PROOF_v0.md](../spec/PROOF_v0.md) · Design: [../EYD_DESIGN.md](../EYD_DESIGN.md)
