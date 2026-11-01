# SE-1 overlay: the running signal_engine release plus the six SE-1 files, nothing else.
# Build context = a clean `git archive 7ff582f` export (never the production checkout).
# The base is pinned by digest (R2-05): no temporary tag is created. The digest equals the running
# image ID sha256:c5be4e34c064c707cb421c2f5d26c38dfee8ad75f36d7e3b177be88d4a825418 (RepoDigests, verified).
# Build (Class B, owner-approved only; refuse if the target tag already exists; the post-build gate
# checks that the revision label equals the full SOURCE_COMMIT and that there are exactly 26 layers):
#   docker build --network=none --pull=false --build-arg SOURCE_COMMIT=7ff582fa43b4fd16042ccb6f71035e4031b67eac \
#     -f <path to this Dockerfile> -t tsb-se1-signal_engine:7ff582f-r1 <export directory>
FROM tsb-a561-signal_engine@sha256:c5be4e34c064c707cb421c2f5d26c38dfee8ad75f36d7e3b177be88d4a825418
ARG SOURCE_COMMIT
LABEL org.opencontainers.image.revision=${SOURCE_COMMIT} \
      tsb.release="se1-funnel-ea8ae4f" tsb.base_image="sha256:c5be4e34c064c707cb421c2f5d26c38dfee8ad75f36d7e3b177be88d4a825418"
COPY --chown=1000:1000 signal_engine/main.py /app/main.py
COPY --chown=1000:1000 shared/funnel_flags.py shared/funnel_hooks.py shared/funnel_records.py shared/funnel_recorder.py shared/selection_policy.py /app/shared/
