"""P2-F0 adversarial validation (OFFLINE ONLY; stdlib only; never imports p2_forward; synthetic data for its own
validation). Spec: docs/p2/P2F0_ADVERSARIAL_VALIDATION.md. Frozen contracts: ``contracts/`` (``contracts.verify``).

The battery receives a candidate's full eligible row panel and tries to disprove the claimed edge: integrity ->
minimum n -> economics / attribution -> robustness -> placebos -> multiplicity -> one verdict from a frozen taxonomy
that never says "proven"."""
PACKAGE_VERSION = "p2f0-falsification-1.0.0"
