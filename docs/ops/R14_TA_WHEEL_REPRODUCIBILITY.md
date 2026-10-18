# R1.4-G — ta wheel reproducibility investigation

**Review-only evidence; not a reproducible-build certification.**

R1.4-E run 39159452766 built `ta-0.11.0-py3-none-any.whl` with SHA256 `ce5bde5f92496f29486bebc3f588c8f1ce11fb35b504831d9308ba40d733c450`.
R1.4-F run 39161343627 built the same wheel filename with SHA256 `a805c47a6db828447b1886e665800c1f80b35b9ef0df21fb059ee3b2bae190e4`. Both workflows succeeded, including analyzer isolated installation and import smoke in F. The differing hashes warrant investigation; they do not alone establish a compromise.

This manual-only workflow:
1. Preserves `ta==0.11.0` direct pin, records Python/pip/platform/commit, downloads one exact source distribution and records its SHA256.
2. Builds two wheels from that single source distribution in the **same disposable runner** with `SOURCE_DATE_EPOCH=1704067200`, no pip wheel cache, and records both SHA256 hashes.
3. Compares complete wheel bytes and individual ZIP member-content digests; writes comparison JSON before failing closed on mismatch.
4. Uploads both wheel files and provenance even if the comparison fails.

**Limitations:** the two builds share a runner, build-toolchain and dependency index; build dependencies are not pinned or verified against trusted hashes. A same-run byte match does not demonstrate independent cross-run reproducibility, reproducible source acquisition, verified source provenance or security. A mismatch is an investigation trigger, not permission to modify the package. `SOURCE_DATE_EPOCH` is only one possible source of nondeterminism; archive metadata, build backends, compression, generated files and environment can matter.

**Next gate:** inspect source hashes, build backend and wheel ZIP metadata across runs; independently reproduce with pinned tools and audited immutable inputs before designing transitive hash locks. Do not approve production images or runtime parity based on this diagnostic. No protected experiments, production deployments, collector changes or trading activation.
