"""P2-C research & feature layer (OFFLINE ONLY; no feedback to Paper, no network, stdlib only).

Pipeline: raw schema-v2 forward data (immutable, read-only, SEALED days by default)
  -> reader (normalized, quality-preserving bundle)
  -> features (point-in-time view, feature_available_at <= decision_time)
  -> labels (forward-looking, separate namespace and file)
  -> deterministic research dataset (manifest + logical hash).

Independence: this package never imports the collector package ``p2_forward``; the reader is re-implemented from
``p2_forward/p2_forward/SCHEMA.md`` (schema v2) like the independent verifiers.
"""
PACKAGE_VERSION = "p2c-research-0.1.0"
