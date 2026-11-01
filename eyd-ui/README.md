# EyD window

Standalone launcher for the EyD window: a local web view of your own
agent's action chain — every action, its classification once the Proof
Receipt lands, and a verify button that checks the receipt's Clearing
House signature locally. Nothing is recorded here; recording happens in
your framework via the SDK — the window only reads the chain.

```bash
python eyd-ui/window.py [--port 8790] [--clearinghouse http://127.0.0.1:8787]
```

The implementation lives in [../eyd/window.py](../eyd/window.py); this
entry point just points it at your identity and chain files (the SDK
defaults unless `--identity`/`--chain` say otherwise).
