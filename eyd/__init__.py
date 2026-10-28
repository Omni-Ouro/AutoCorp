"""EyD SDK — a library the agent framework imports.

It sits in the framework's tool-call path as a hook: every call the
agent makes is signed under the agent's own Ed25519 key and reported
to the clearinghouse before it goes out, and the signed Proof Receipt
comes back to both parties. See EYD_DESIGN.md §3.1.
"""
__version__ = "0.1.0"
EYD_VERSION = "0.1"

from .sdk import EyD, ToolResult, current_headers, verb_for_tool  # noqa: E402

__all__ = ["EyD", "ToolResult", "current_headers", "verb_for_tool", "__version__", "EYD_VERSION"]
