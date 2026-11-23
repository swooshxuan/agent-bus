FROM node:22-slim

# Build args let users behind slow networks point at a local mirror.
# Defaults are the upstream sources.
ARG DEBIAN_MIRROR=deb.debian.org
ARG NPM_REGISTRY=https://registry.npmjs.org

RUN if [ "$DEBIAN_MIRROR" != "deb.debian.org" ]; then \
        sed -i "s|deb.debian.org|$DEBIAN_MIRROR|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
        sed -i "s|deb.debian.org|$DEBIAN_MIRROR|g" /etc/apt/sources.list 2>/dev/null || true; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN npm config set registry "$NPM_REGISTRY" \
    && npm install -g @anthropic-ai/claude-code

# Run as a non-root user: the CLI refuses --dangerously-skip-permissions as
# root. The node image already ships a "node" user (uid 1000); agent-bus also
# passes --user <host uid>:<host gid> at run time so the mounted work
# directory stays writable.
USER node
# The host work directory is mounted here by agent-bus.
WORKDIR /work
