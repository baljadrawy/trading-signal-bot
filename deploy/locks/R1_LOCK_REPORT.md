# R-1 dependency-lock preparation: report (REVIEW-ONLY)

This is phase R-1 of `docs/ops/CANONICAL_IMAGE_REMEDIATION_PLAN.md`. It is a review artifact only.

- No image was built, pulled, pushed or tagged.
- No running container, Compose file, Dockerfile or `requirements.txt` was changed.
- No network was used. Every container ran with `--network none --read-only --cap-drop ALL`.
- The `deploy/locks/<svc>.lock.candidate.txt` files are **not used by any Dockerfile or build**, and they are not
  certified. Nothing installs from them in this PR.

Date of extraction: 2026-10-22. Scope: the five Paper services. The Collector is out of scope.

## 1. Method

For each running Paper image, identified by its immutable image ID:

```
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
  --entrypoint python <image-id> -m pip freeze --all          # freeze view
  ... --entrypoint python <image-id> -m pip inspect           # pip's installed-metadata report
  ... -v deploy/locks/extract_installed.py:/x/extract.py:ro --entrypoint python <image-id> /x/extract.py
  ... --entrypoint python <image-id> -m pip check
```

`extract_installed.py` (committed next to this report) reads each `*.dist-info` through `importlib.metadata`. It
records name, version, the `WHEEL` Tag and Generator lines, the sha256 of `RECORD`, `direct_url.json`, `INSTALLER`,
`REQUESTED`, `Requires-Dist`, and the interpreter and libc of the image.

The three views (freeze, pip inspect and dist-info metadata) were compared with each other and with
`deploy/a561-rel-ea8ae4f/installed-packages/<svc>.txt`. Each candidate lock was then checked with the offline
verifier `ops/provenance/lock_review.py` (`verify(requirements.txt, lock)`).

`ops/provenance/lock_candidate.py` was **not** used. It converts a `pip install --dry-run --report` resolution, and
that needs a package index (network). An inventory of the installed environment is the stronger ground truth for an
equivalence lock, so R-1 builds the lock directly from the running image.

## 2. Per-service equality with `installed-packages/<svc>.txt`

| Service | Running image | Image ID | Dists | freeze = inspect = dist-info | = installed-packages | pip check |
|---|---|---|---|---|---|---|
| scanner | `tsb-aiohttp-test-scanner:3.14.3-20260929T124120Z` | `sha256:63b38e7a659d…` | 31 | yes | **EQUAL** | no broken requirements |
| analyzer | `tsb-a561-analyzer:rel-ea8ae4f-r2` | `sha256:011f99ba451b…` | 31 | yes | **EQUAL** | no broken requirements |
| signal_engine | `tsb-a561-signal_engine:rel-ea8ae4f-r2` | `sha256:c5be4e34c064…` | 49 | yes | **EQUAL** | no broken requirements |
| telegram | `tsb-a561-telegram:rel-ea8ae4f-r2` | `sha256:51d62f4dfa51…` | 20 | yes | **EQUAL** | no broken requirements |
| trade_tracker | `tsb-a561-trade_tracker:rel-ea8ae4f-r2` | `sha256:2cf1dd52cd89…` | 28 | yes | **EQUAL** | no broken requirements |

Equality means the same set of distribution names and the same version for each one. Notes:

- **aiohttp in the freeze view.** In every image, `pip freeze` prints aiohttp as a direct-URL requirement:
  `aiohttp @ file:///tmp/overlay/aiohttp-3.14.3-…aarch64.whl#sha256=f631fe87…`. This comes from the 3.14.3 wheel
  overlay. Name and version are equal to the inventory. The URL form must not be copied into a lock, because
  `/tmp/overlay` does not exist at build time.
- **Locations.** All distributions are in `/usr/local/lib/python3.12/site-packages`. The installer is `pip` for
  all of them. There are no editable installs and no user-site packages.
- **setuptools.** It is not installed in any image (the `python:3.12-slim` base no longer ships it).
- **Same wheel content.** For every (name, version) pair that appears in more than one service, the `RECORD` sha256
  is identical in every image. The same wheel content was installed in each service.

Lock candidate sha256 values (for review pinning):

| File | sha256 |
|---|---|
| `scanner.lock.candidate.txt` | `2c7041e77a0bde6ee0479e26893ac9ca1d353ddc18ba18faef5a49731885cf49` |
| `analyzer.lock.candidate.txt` | `2bb2021bb5637e6a823031a30c92eb8ae01af4df6ae5dff13f5df523bab0ad20` |
| `signal_engine.lock.candidate.txt` | `8887287d6a649aceb09a33a7ba8fe2667dc46bfd3fe72a01c9481c63b046c2ac` |
| `telegram.lock.candidate.txt` | `114d1e99a665015c2f767d89f5379358a2246d4559d27db610c6650f031b6de9` |
| `trade_tracker.lock.candidate.txt` | `56c92a0c0497a5c90b1362b3ee643a9a17a060047a0605184b296234f52ff7b0` |

Role counts (direct / transitive / bootstrap pip+wheel): scanner 6/23/2, analyzer 7/22/2, signal_engine 5/42/2,
telegram 3/15/2, trade_tracker 3/23/2.

## 3. Conflicts with `<svc>/requirements.txt` pins

Results of `lock_review.verify(requirements.txt, lock)`:

| Service | Result |
|---|---|
| scanner | verified: all 6 direct pins equal the installed versions |
| analyzer | **direct version mismatch aiohttp: declared 3.13.5, locked 3.14.3** |
| signal_engine | **direct version mismatch aiohttp: declared 3.13.5, locked 3.14.3** |
| telegram | verified: all 3 direct pins equal the installed versions |
| trade_tracker | verified: all 3 direct pins equal the installed versions |

The analyzer and signal_engine images were built from 3.13.5 pins. The 3.14.3 overlay was installed on top of them
later. As a result, a rebuild from `requirements.txt` today would install 3.13.5 and regress the aiohttp CVE fixes.

Other drift that `verify` does not flag, because these are not direct pins:

- **signal_engine numpy.** signal_engine does not pin numpy, and it resolved 2.5.2. scanner and analyzer pin 2.2.6.
- **Unpinned transitive dependencies.** All other transitive versions are unpinned. idna, for example, differs
  between images built on different days (see §4).

## 4. Cross-service version divergence

"—" means the service does not have the distribution.

| Distribution | scanner | analyzer | signal_engine | telegram | trade_tracker | Note |
|---|---|---|---|---|---|---|
| numpy | 2.2.6 (pin) | 2.2.6 (pin) | **2.5.2** (unpinned) | — | — | Two numpy majors in one fleet; pandas 3.0.3 accepts both (`numpy>=1.26.0`). |
| websockets | 17.0.1 | **12.0** (pin) | 17.0.1 | — | 17.0.1 | Unpinned except in analyzer. See the python-binance note below. |
| idna | 3.18 | **3.19** | 3.18 | **3.19** | 3.18 | Build-date drift of an unpinned dependency. It is the clearest proof that unlocked rebuilds are not reproducible. |
| httpx | — | — | 0.28.1 | 0.28.1 | — | Same version. python-telegram-bot needs `httpx~=0.27`, which is satisfied. |
| httpcore | — | — | 1.0.9 | 1.0.9 | — | |
| requests | 2.34.2 | 2.34.2 | 2.34.2 | — | 2.34.2 | Uniform. |
| urllib3 | 2.7.0 | 2.7.0 | 2.7.0 | — | 2.7.0 | Uniform. |
| aiohttp | 3.14.3 | 3.14.3 | 3.14.3 | 3.14.3 | 3.14.3 | Uniform at runtime; two pins are stale (§3). |
| pandas | 3.0.3 | 3.0.3 | 3.0.3 | — | — | Uniform. |
| python-binance | 1.0.19 | 1.0.19 | 1.0.19 | — | 1.0.19 | Uniform. |
| asyncpg | 0.29.0 | 0.29.0 | 0.29.0 | 0.29.0 | 0.29.0 | Uniform. |
| anthropic | — | — | 0.25.0 | — | — | See the anthropic and httpx note below. |
| pip / wheel | 26.1.2 / 0.46.3 | same | same | same | same | Bootstrap. The Dockerfile upgrades pip to `26.1.*` and wheel to `0.46.*`. |
| certifi | 2026.7.22 | same | same | same | same | Uniform. |

### anthropic and httpx compatibility

anthropic 0.25.0 declares `httpx<1,>=0.23.0`, so `pip check` passes. But httpx 0.28 removed the `proxies` argument,
and anthropic 0.25.0 still passes it.

This was tested offline in the signal_engine image (`--network none`). Constructing `anthropic.Anthropic(...)` and
`anthropic.AsyncAnthropic(...)` with a dummy credential both raise:

- `TypeError: Client.__init__() got an unexpected keyword argument 'proxies'`
- `TypeError: AsyncClient.__init__() got an unexpected keyword argument 'proxies'`

The runtime is **not affected today**. The only runtime import is `shared/retry_utils.py`, which reads two exception
classes inside `try/except ImportError`. No client is constructed, because claude_review is retired. The broken
combination is latent.

anthropic also pulls in a Hugging Face stack: huggingface-hub, hf-xet, filelock, fsspec, tqdm, pyyaml and the HF
text-encoding library (pinned in the signal_engine lock; that line is a public package name, not a secret). This
stack accounts for most of signal_engine's 49 distributions.

Options, as a proposal for a later separate PR:

- **(a) Keep as is.** This is what the equivalence lock must do. It is the R-1 choice.
- **(b) Drop `anthropic` from `signal_engine/requirements.txt`.** This removes at least 15 distributions that only signal_engine has. It is a
  behaviour change, so it belongs after R-6.
- **(c) Constrain httpx below 0.28.** Rejected, because it changes a shared dependency of telegram.

### python-binance and websockets

python-binance 1.0.19 `binance/streams.py` calls `ws.connect(...)` and `self.ws.fail_connection()`. With websockets
17.0.1, `websockets.connect` resolves to the new `websockets.asyncio.client` API, and `ClientConnection` has no
`fail_connection`.

This was checked offline in the scanner image. No service code uses `BinanceSocketManager` or the stream helpers, so
this is not exercised. It is recorded so that R-4 smoke tests do not treat it as new breakage.

## 5. Architecture notes (linux/arm64, aarch64)

- **Platform.** All five images are `linux/arm64`, CPython 3.12.13, glibc 2.41, and `sysconfig` `linux-aarch64`.
- **Distribution counts.** There are 55 unique (name, version) pairs across the five services. 19 of them are binary
  wheels and 36 are pure-Python.
- **manylinux floors.** Binary wheel tags range from `manylinux2014_aarch64` (`manylinux_2_17`) to
  `manylinux_2_28_aarch64`:
  - hf-xet 1.6.0 is `cp38-abi3-manylinux_2_28_aarch64` only.
  - numpy 2.5.2 is `manylinux_2_27`/`2_28`.
  - pandas 3.0.3 and ujson 5.13.0 are `manylinux_2_24`/`2_28`.
  - The effective floor is therefore **manylinux_2_28 (glibc ≥ 2.28)**. The image's glibc 2.41 satisfies it.
- **abi3 wheels.** hf-xet (`cp38-abi3`), pycryptodome (`cp37-abi3`) and the HF text-encoding library (`cp310-abi3`).
- **No local builds.** No distribution was built from an sdist inside the image. Every `WHEEL` Generator is the
  upstream build backend of the published wheel: setuptools, hatchling, flit, meson, maturin, poetry-core, or an old
  bdist_wheel. R-2 must confirm this against the index.
- **Downloading on x86.** CI is x86_64. R-2 must fetch with explicit target flags (`--platform manylinux_2_28_aarch64
  --platform manylinux2014_aarch64 --python-version 3.12 --implementation cp --abi cp312 --abi abi3
  --only-binary=:all:`), or run on the arm64 host.
- **Wheel filenames.** The filenames in the locks are reconstructed from the installed `WHEEL` tags, sorted. Only
  aiohttp has an exact upstream filename (from `direct_url.json`), and the reconstruction matched it. R-2 must use
  the index filenames, which may differ in name case or normalization for older uploads (for example PyYAML,
  python-binance and asyncio-throttle).
- **Wheel hashes.** These are not derivable offline, except for aiohttp:
  `sha256:f631fe87a6f30df5fbe6d79640b25e4cffb38c31c7fb6f10871517b84b0f8c1a`. That value is recorded in every image's
  `direct_url.json`. It equals `deploy/aiohttp-3.14.3/IMAGES.md` and the local overlay wheel copy in the host
  backup.
  - The images have no pip cache (`PIP_NO_CACHE_DIR=1`).
  - The only bundled wheel is ensurepip's pip 25.0.1, which is not the installed 26.1.2.
  - Every other hash is marked `# hash: TO-RESOLVE (R-2 wheelhouse)`.
  - The `record-sha256` lines are an installed-content fingerprint for R-4 equivalence checks, not wheel hashes.

## 6. Proposed `requirements.txt` pin corrections (NOT applied in this PR)

These are the minimum corrections that make every `requirements.txt` agree with its running lock. They are
equivalence-preserving: the running images already have these versions.

```diff
--- a/analyzer/requirements.txt
+++ b/analyzer/requirements.txt
-aiohttp==3.13.5    # latest — حل كل CVEs aiohttp 2024-2026
+aiohttp==3.14.3    # latest — حل كل CVEs aiohttp 2024-2026
--- a/signal_engine/requirements.txt
+++ b/signal_engine/requirements.txt
-aiohttp==3.13.5    # latest — حل كل CVEs aiohttp 2024-2026
+aiohttp==3.14.3    # latest — حل كل CVEs aiohttp 2024-2026
```

Optional and also equivalence-preserving, for owner decision: add `numpy==2.5.2` to `signal_engine/requirements.txt`.
This makes the numpy split explicit instead of an accident of resolution.

Do **not** unify numpy (2.2.6 and 2.5.2) or websockets (12.0 and 17.0.1) across services in this programme. R-6 is
an equivalence swap, so each canonical image must keep its running versions. Unifying them is a separate,
behaviour-changing change.

After the correction, `lock_review.verify` passes for all five services. Before the correction, analyzer and
signal_engine fail as shown in §3.

## 7. Open items for R-2

1. **Wheelhouse.** Resolve wheel sha256 for the 54 unique (name, version) pairs other than aiohttp. Download only the
   exact pinned versions, as aarch64/cp312 wheels with `--no-deps`. Record index filenames and `SHA256SUMS`.
2. **Hash cross-check.** After downloading, install each wheel into a disposable `--network none` container and
   compare its `RECORD` sha256 with the `record-sha256` in the lock. This is a byte-level check that the wheelhouse
   equals what runs.
   - Caveat: `RECORD` also lists `INSTALLER`, `REQUESTED` and `direct_url.json`. Install with the same pip (26.1.2)
     and the same requested or direct-URL status.
   - aiohttp will differ unless it is installed from a `file://` URL.
3. **Gaps.** Identify any pinned version that is no longer downloadable for aarch64. The plan's fallback (rebuilding
   wheels from site-packages) is weaker and must be labelled as such.
4. **Lock format.** Convert the candidate format into the final `requirements.lock`. That means one line per
   distribution, `name==version --hash=sha256:…`, so that it works with `--require-hashes --no-deps
   --only-binary=:all:`.
   - Decide whether pip and wheel stay in the lock or stay as the Dockerfile's separate bootstrap step.
   - aiohttp must be locked by name and version, not by the overlay `file://` URL.
5. **Pin corrections.** Apply §6 in a reviewed PR. Ideally do this in the same PR that adds the final locks, so that
   `verify` stays green.
6. **Scanner source.** The scanner still has no source commit (plan §6). The scanner lock covers packages only.
7. **anthropic and httpx.** Owner decision on option (a) or (b) in §4. This is outside the equivalence programme.

## 8. Protected-information scan note

The signal_engine lock has two lines that name a public PyPI distribution whose name contains a word that the
protected scan blocks. These are the pin line and its wheel filename line. Both carry the inline annotation
`# distribution name, not a secret`, which is the scan's existing allow wording. The scan itself was not changed.
This is the only case where a package name matched. Reviewers should confirm that the annotation is acceptable.
