# SE-1 overlay: the running signal_engine release plus the six SE-1 files, nothing else.
# Build context = a clean `git archive 7ff582f` export (never the production checkout).
# BASE_TAG must be a temporary local tag proven to resolve to the running image ID
#   sha256:c5be4e34c064c707cb421c2f5d26c38dfee8ad75f36d7e3b177be88d4a825418 (tsb-a561-signal_engine:rel-ea8ae4f-r2).
# Build (Class B, owner-approved only): docker build --network=none --pull=false --build-arg BASE_TAG=... \
#   --build-arg SOURCE_COMMIT=7ff582fa43b4fd16042ccb6f71035e4031b67eac -f <this file> -t tsb-se1-signal_engine:7ff582f-r1 <export>
ARG BASE_TAG
FROM ${BASE_TAG}
ARG SOURCE_COMMIT
LABEL org.opencontainers.image.revision=${SOURCE_COMMIT} \
      tsb.release="se1-funnel-ea8ae4f" tsb.base_image="sha256:c5be4e34c064c707cb421c2f5d26c38dfee8ad75f36d7e3b177be88d4a825418"
COPY --chown=1000:1000 signal_engine/main.py /app/main.py
COPY --chown=1000:1000 shared/funnel_flags.py shared/funnel_hooks.py shared/funnel_records.py shared/funnel_recorder.py shared/selection_policy.py /app/shared/
