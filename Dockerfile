# Munim as a stdio MCP server in a container.
#
# This exists for directory listings that introspect a server before accepting
# it, and for anyone who would rather not install a Python tool on their
# machine. It is not how the project expects to be run: munim holds OAuth
# sessions with each client's provider, and `munim connect` opens a browser and
# writes to a store on the host. In a container that store is empty and
# disappears when the container does, so mount it if you want it to persist:
#
#   docker run -i --rm -v "$HOME/.munim:/home/munim/.munim" munim
#
# With nothing mounted the server still starts and still lists all of its
# tools, which is what an introspection check asks of it. Every tool that needs
# a credential then answers with the command that would set one up, because a
# tool that is switched off is not the same as one that was never built.

FROM python:3.13-slim

# Build from this repository rather than from PyPI on purpose: a directory
# check should exercise the code in the commit it is looking at, not whatever
# was last released.
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

# Not root. The server reads and writes a credential store under $HOME, and
# there is no reason for that to be /root.
RUN useradd --create-home --uid 10001 munim
USER munim
WORKDIR /home/munim

# stdio, so stdout is the JSON-RPC channel and nothing else may write to it.
# Python buffers stdout when it is a pipe, which would hold protocol frames
# back until a buffer filled.
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["munim-mcp"]
