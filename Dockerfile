
ARG PYTHON_IMAGE=python:3.11.6-slim-bookworm


FROM ${PYTHON_IMAGE} AS build
SHELL ["/bin/sh", "-eu", "-c"]

ARG SOURCE_DATE_EPOCH=0
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build

RUN python -m pip install \
      --no-color \
      --no-warn-script-location \
      --break-system-packages \
      --progress-bar off \
      'poetry>=2,<3' poetry-plugin-export setuptools wheel

COPY pyproject.toml poetry.lock README.md ./
RUN mkdir -p dist \
    && poetry export \
         --without-hashes \
         --format constraints.txt \
         --output dist/constraints.txt \
    && poetry run \
         python -m pip wheel \
           --isolated \
           --requirement dist/constraints.txt \
           --wheel-dir dist/vendor

COPY src/ src/
RUN poetry build --format wheel

# ---------- финальная стадия ----------
FROM ${PYTHON_IMAGE} AS final
SHELL ["/bin/sh", "-eu", "-c"]
ARG SOURCE_DATE_EPOCH=0

ARG USER=app
ARG UID=10001
ARG GID=10001
RUN addgroup --gid "${GID}" "${USER}" \
    && adduser --disabled-password --gecos "" \
         --home /app --ingroup "${USER}" --uid "${UID}" "${USER}"

RUN --mount=type=bind,from=build,source=/build/dist,target=/tmp/dist \
    python -m pip install \
      --isolated \
      --no-index \
      --no-color \
      --no-cache-dir \
      --disable-pip-version-check \
      --no-warn-script-location \
      --no-deps \
      --break-system-packages \
      --progress-bar off \
      /tmp/dist/*.whl /tmp/dist/vendor/*.whl

USER ${USER}
WORKDIR /app
ENV AUDIT_SVC_CONFIG=/etc/audit-svc/config.yaml \
    PORT=8080 \
    PYTHONUNBUFFERED=1
EXPOSE 8080/tcp

CMD ["server"]
