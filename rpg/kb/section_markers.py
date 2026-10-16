"""kb/section_markers.py — context section headers that code (not just the model) looks up.

Single source for markers that are produced in one module and split/matched in another.
The legacy Chinese forms are kept so text rendered before the English switch (caches, logs
replayed in tests, old saves) is still recognised.
"""
from __future__ import annotations

# "Worldline convergence · upcoming anchors" block: produced by retrieval/assemble.py,
# split out by context_engine.core._split_anchor_pending, re-attached by kb/recall.py.
ANCHOR_PENDING_MARKER = "=== Worldline Convergence · Upcoming Anchors ==="
LEGACY_ANCHOR_PENDING_MARKER = "=== 世界线收束·接下来的锚点 ==="
ANCHOR_PENDING_MARKERS = (ANCHOR_PENDING_MARKER, LEGACY_ANCHOR_PENDING_MARKER)
