# Single worker by default; SQLite transactions protect league updates.
FROM restic/restic:0.18.0@sha256:4cf4a61ef9786f4de53e9de8c8f5c040f33830eb0a10bf3d614410ee2fcb6120 AS restic-bin
FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt requirements-build.txt ./
RUN python -m pip install --no-cache-dir --require-hashes -r requirements-build.txt \
    && python -m pip install --no-cache-dir --require-hashes --no-build-isolation -r requirements.txt \
    && useradd --system --uid 10001 --create-home --home-dir /home/chess chess
COPY --chown=chess:chess . /app
RUN mkdir -p /data /backups && chown 10001:10001 /data /backups
USER chess
EXPOSE 8000
CMD ["sh", "deploy/start.sh"]

# Only the optional encrypted off-server profile builds this stage.
FROM app AS backup-offsite
COPY --from=restic-bin /usr/bin/restic /usr/local/bin/restic
