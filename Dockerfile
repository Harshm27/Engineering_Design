# Drawing to Solid: 2D engineering drawing -> verified 3D solid.
#
# Build:  docker build -t drawing-to-solid .
# Run:    docker run --rm -v "$PWD/out:/out" drawing-to-solid
#
FROM python:3.11-slim

LABEL org.opencontainers.image.title="Drawing to Solid" \
      org.opencontainers.image.description="2D engineering drawing to verified 3D solid" \
      org.opencontainers.image.version="1.0"

# OpenCASCADE (cadquery-ocp) and its bundled VTK need these at runtime.
# libgl1, libx11-6 and libexpat1 are linked directly (confirmed with ldd against
# the installed OCP shared objects); the rest cover VTK's X11 rendering path,
# which cadquery touches on import in some versions. All are small.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libx11-6 \
        libexpat1 \
        libxext6 \
        libxrender1 \
        libsm6 \
        libice6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY drawing2solid/ ./drawing2solid/
COPY examples/ ./examples/
COPY selftest.py webapp.py SCHEMA.md SKILL.md README.md DOCKER.md ./

# Results are written here. Mount a host folder over it to keep them:
#   -v "$PWD/out:/out"
ENV OUTDIR=/out
RUN mkdir -p /out

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Web front end, when run with the `serve` subcommand.
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=4s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=3).status==200 else 1)" || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["selftest"]
