# mvsce-builder: MVS/CE with current UFSD, HTTPD and mvsMF releases.
#
# MVS/CE 3.0.0 already installs UFSD, HTTPD and mvsMF through MVP (not
# started), including the STC procedures, the parmlib members and the UFS
# disks. Those MVP packages date from July 2026, before the libc370 spool
# walk fixes (libc370 #28, #126) that mvsMF needs for jobs with many SYSOUT
# data sets (mvslovers/mvsmf#374). This image replaces the contents of the
# three load libraries with the pinned releases below and turns on autostart.
#
# Bump a version by changing its ARG; nothing else refers to it.
#
# Hercules is replaced as well. MVS/CE 3.0.0 carries the Hercules of
# mainframed767/hercules as of March 2026 (4.10.0.11668, g5081b9ea), which
# predates the console fix SDL-Hercules-390/hyperion#889 (a lost wakeup in
# the 3215-C console that can hang the IPL) and the X'75' TCP/IP fixes
# #864, #870, #875 and #885 the servers depend on. The stage below builds
# Hyperion at HERCULES_REF into the very prefix MVS/CE uses, so /mvs.sh,
# PATH and LD_LIBRARY_PATH stay as they are. Drop the stage once
# mainframed767/mvsce itself reports a Hercules at or after HERCULES_REF.

ARG MVSCE_VERSION=3.0.0
ARG HERCULES_REF=a742398074b24c6e9dfff1e4065a55b69a8a4883

# Debian trixie, as the runtime of mainframed767/mvsce, so the binaries
# find the same libraries. Built the way ../hercules builds it: a portable
# -O3 instead of hercules-helper's -march=native, which would SIGILL on a
# host whose CPU lacks the build machine's instructions. Regina is there
# because mainframed767/hercules builds with it too.
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

RUN opt_configure_optimization="-O3" \
    /opt/hercules-helper/hercules-buildall.sh \
      --auto --flavor=sdl-hyperion --git-commit=${HERCULES_REF} \
      --accept-root --no-packages --no-tests --no-setcap \
      --no-envscript --no-bashrc \
      --prefix=/home/hercules/herctest/herc4x

FROM mainframed767/mvsce:${MVSCE_VERSION}

ARG MVSCE_VERSION
ARG HERCULES_REF
ARG UFSD_VERSION=1.4.0
ARG HTTPD_VERSION=4.3.0
ARG MVSMF_VERSION=1.3.0

USER root

# Replace MVS/CE's Hercules, then check what is actually installed: the
# build fails unless the version banner names HERCULES_REF and every
# binary and module resolves all its libraries.
RUN rm -rf /home/hercules/herctest/herc4x
COPY --from=hercules /home/hercules/herctest/herc4x /home/hercules/herctest/herc4x
RUN banner=$(hercules --version 2>&1 | grep -m 1 HHC01413I) \
    && echo "$banner" \
    && sha=$(echo "$banner" | sed -n 's/.*-g\([0-9a-f]\{7,\}\).*/\1/p') \
    && case "${HERCULES_REF}" in \
         "$sha"*) [ -n "$sha" ] ;; \
         *) echo "Hercules is g$sha, expected ${HERCULES_REF}" >&2; false ;; \
       esac \
    && ! ldd /home/hercules/herctest/herc4x/bin/hercules \
             /home/hercules/herctest/herc4x/lib/hercules/*.so \
         | grep 'not found'

ADD https://github.com/mvslovers/ufsd/releases/download/v${UFSD_VERSION}/ufsd-${UFSD_VERSION}-load.xmit /tmp/ufsd.xmit
ADD https://github.com/mvslovers/httpd/releases/download/v${HTTPD_VERSION}/httpd-${HTTPD_VERSION}-load.xmit /tmp/httpd.xmit
ADD https://github.com/mvslovers/mvsmf/releases/download/v${MVSMF_VERSION}/mvsmf-${MVSMF_VERSION}-load.xmit /tmp/mvsmf.xmit

# One CPU instead of MVS/CE's two. With NUMCPU 2 the IPL stalled in 2 of
# 24 starts in ways that both involve CP01 (stuck right after CP00 reset
# it by SIGP; CP01 in disabled wait 064 while CP00 spins); with NUMCPU 1,
# 0 of 24 (mvs-docker runs 36890781934/36890792177 vs 36892915143/
# 36892926001, brexx370#277). The cause is not known. MVSCE_NUMCPU=2 at
# run time restores two CPUs.
RUN sed -i 's/^NUMCPU .*/NUMCPU    1/' /MVSCE/conf/local.cnf \
    && grep -q '^NUMCPU    1$' /MVSCE/conf/local.cnf

COPY setup_mvsce.py /tmp/setup_mvsce.py

# Starts Hercules, IPLs MVS, installs the modules, verifies the running
# mvsMF level and shuts down. The modified DASDs under /MVSCE/DASD/ are baked
# into this layer; the base image's entrypoint copies them to /dasd.
RUN cd /MVSCE && UFSD_VERSION=${UFSD_VERSION} HTTPD_VERSION=${HTTPD_VERSION} \
    MVSMF_VERSION=${MVSMF_VERSION} HERCULES_REF=${HERCULES_REF} \
    python3 -u /tmp/setup_mvsce.py \
    && rm -f /tmp/ufsd.xmit /tmp/httpd.xmit /tmp/mvsmf.xmit /tmp/setup_mvsce.py

# Wraps the base image's ./mvs.sh so that the Hercules log and the console
# hardcopy show up in `docker logs` (see entrypoint.sh).
COPY --chmod=755 entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

LABEL org.opencontainers.image.source="https://github.com/mvslovers/mvs-docker" \
      org.opencontainers.image.description="MVS/CE ${MVSCE_VERSION} with UFSD ${UFSD_VERSION}, HTTPD ${HTTPD_VERSION} and mvsMF ${MVSMF_VERSION}, Hercules ${HERCULES_REF}" \
      io.mvslovers.mvsce.version="${MVSCE_VERSION}" \
      io.mvslovers.hercules.ref="${HERCULES_REF}" \
      io.mvslovers.ufsd.version="${UFSD_VERSION}" \
      io.mvslovers.httpd.version="${HTTPD_VERSION}" \
      io.mvslovers.mvsmf.version="${MVSMF_VERSION}"

EXPOSE 3270 3505 3506 8080 8888
