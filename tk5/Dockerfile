# syntax=docker/dockerfile:1
#
# tk5: MVS 3.8j TK5 (Rob Prins' turnkey system), as shipped, on the
# Hercules mvsce runs.
#
# The system comes from the TK5 download, pinned by checksum. The page
# publishes no checksum, so TK5_SHA256 is the one this file was written
# against (the zip of Update 5, 2026-02-18, 498312872 bytes); a re-upload
# under the same name fails the build instead of changing the system. A
# new update is TK5_UPDATE, TK5_URL and TK5_SHA256.
#
# TK5 brings its own Hercules builds (SDL 4.9.1 for 64-bit Linux, 4.3.99
# elsewhere). They are dropped for Hyperion at HERCULES_REF, built the way
# ../mvsce builds it, so both images run the same emulator: the console
# fix SDL-Hercules-390/hyperion#889 and the X'75' TCP/IP fixes are in it,
# and arm64 gets the same build as amd64.
#
# TK5 is configured through its own hooks only: the ${VAR:=default}
# settings in conf/tk5.cnf and its rc files (ENV below). conf/, scripts/
# and dasd/ stay as shipped.

ARG TK5_UPDATE=5
ARG TK5_URL=https://www.prince-webdesign.nl/images/downloads/mvs-tk5.zip
ARG TK5_SHA256=710d002843631322810a276dd42c793fda458548dc64d86e2914a62db7425f84
ARG HERCULES_REF=a742398074b24c6e9dfff1e4065a55b69a8a4883

FROM debian:trixie AS hercules

ARG HERCULES_REF

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       sudo time git curl wget ca-certificates python3 \
       build-essential autoconf automake libtool pkg-config m4 flex bison \
       cmake unzip make gcc g++ gawk libltdl-dev zlib1g-dev libbz2-dev \
       regina-rexx libregina3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/wrljet/hercules-helper.git /opt/hercules-helper

WORKDIR /build

# -O3 instead of hercules-helper's -march=native, which would SIGILL on a
# host whose CPU lacks the build machine's instructions.
RUN opt_configure_optimization="-O3" \
    /opt/hercules-helper/hercules-buildall.sh \
      --auto --flavor=sdl-hyperion --git-commit=${HERCULES_REF} \
      --accept-root --no-packages --no-tests --no-setcap \
      --no-envscript --no-bashrc \
      --prefix=/opt/hercules

FROM debian:trixie AS system

ARG TK5_URL
ARG TK5_SHA256

RUN apt-get update \
    && apt-get install -y --no-install-recommends unzip \
    && rm -rf /var/lib/apt/lists/*

ADD --checksum=sha256:${TK5_SHA256} ${TK5_URL} /tmp/mvs-tk5.zip

# Everything but TK5's Hercules binaries and the PDF manuals (doc/, also
# in the download); hercules/httproot stays, conf/tk5.cnf serves it.
RUN unzip -q /tmp/mvs-tk5.zip -d /tmp \
    && mv /tmp/mvs-tk5 /tk5 \
    && rm -rf /tk5/hercules/linux /tk5/hercules/darwin /tk5/hercules/windows \
              /tk5/hercules/external_packages_binaries /tk5/doc \
    && test -f /tk5/conf/tk5.cnf && test -d /tk5/hercules/httproot

FROM debian:trixie-slim

ARG TK5_UPDATE
ARG TK5_URL
ARG TK5_SHA256
ARG HERCULES_REF

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libltdl7 zlib1g libbz2-1.0 regina-rexx python3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=hercules /opt/hercules /opt/hercules
ENV PATH=/opt/hercules/bin:$PATH \
    LD_LIBRARY_PATH=/opt/hercules/lib:/opt/hercules/lib/hercules

# The build fails unless the banner names HERCULES_REF and every binary
# and module resolves all its libraries.
RUN banner=$(hercules --version 2>&1 | grep -m 1 HHC01413I) \
    && echo "$banner" \
    && sha=$(echo "$banner" | sed -n 's/.*-g\([0-9a-f]\{7,\}\).*/\1/p') \
    && case "${HERCULES_REF}" in \
         "$sha"*) [ -n "$sha" ] ;; \
         *) echo "Hercules is g$sha, expected ${HERCULES_REF}" >&2; false ;; \
       esac \
    && ! ldd /opt/hercules/bin/hercules /opt/hercules/lib/hercules/*.so \
         | grep 'not found'

COPY --from=system /tk5 /tk5

# TK5's own settings (conf/tk5.cnf, scripts/*.rc). The ports are the ones
# mvsce uses, so a client needs no second set: TN3270 3270, Hercules web
# console 8888 (TK5: 8038), ASCII card reader 3505. REP101A=default on
# every architecture: TK5's mvs_ipl switches ARM to the IPL reply and
# device set without the 3705s, for TK5's own ARM Hercules; this image
# runs the same Hercules everywhere.
ENV HERCULES_RC=scripts/ipl.rc \
    CNSLPORT=3270 \
    HTTPPORT=8888 \
    RDRPORT=3505 \
    NUMCPU=1 \
    MAXCPU=1 \
    REP101A=default

WORKDIR /tk5

COPY --chmod=755 entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

LABEL org.opencontainers.image.source="https://github.com/mvslovers/mvs-docker" \
      org.opencontainers.image.description="MVS 3.8j TK5 Update ${TK5_UPDATE}, Hercules ${HERCULES_REF}" \
      io.mvslovers.tk5.update="${TK5_UPDATE}" \
      io.mvslovers.tk5.sha256="${TK5_SHA256}" \
      io.mvslovers.hercules.ref="${HERCULES_REF}"

EXPOSE 3270 3505 8888
