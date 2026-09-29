# Security overlay: replace ONLY aiohttp 3.13.5 -> 3.14.3 on an EXACT existing production image.
# BASE_TAG must be a temporary local tag proven to resolve to the exact production image ID.
# Build: docker build --network=none --pull=false --build-arg BASE_TAG=... --build-arg ORIG_USER=... -t <unique test tag> .
ARG BASE_TAG
FROM ${BASE_TAG}
ARG ORIG_USER=root
USER root
COPY aiohttp-3.14.3-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl /tmp/overlay/
RUN echo "f631fe87a6f30df5fbe6d79640b25e4cffb38c31c7fb6f10871517b84b0f8c1a  /tmp/overlay/aiohttp-3.14.3-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl" | sha256sum -c - \
 && python -m pip install --no-deps --no-index --no-cache-dir --disable-pip-version-check /tmp/overlay/aiohttp-3.14.3-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl \
 && rm -rf /tmp/overlay
USER ${ORIG_USER}
