# mvsce: MVS/CE with current UFSD, HTTPD, mvsMF and FTPD releases.
#
# MVS/CE 3.0.0 already installs UFSD, HTTPD, mvsMF and FTPD through MVP (not
# started), including the STC procedures, the parmlib members and the UFS
# disks. Those MVP packages date from July 2026, before the libc370 spool
# walk fixes (libc370 #28, #126) that mvsMF needs for jobs with many SYSOUT
# data sets (mvslovers/mvsmf#374). This image replaces the contents of the
# load libraries with the pinned releases below and turns on autostart.
#
# RAKF is replaced as well: the base image carries an older RAKF under the
# same FMID TRKF200 (and the same banner, RAKF V2R0M0). setup_mvsce.py removes
# it from the SMP4 inventory and installs RAKF 2.0.0 (TK5 Update 6) by
# RECEIVE/APPLY/ACCEPT, then IPLs once with CLPA so the new ICHSFR00 and
# ICHRIN00 in SYS1.LPALIB are loaded. The package is a release asset of
# MVS-sysgen/RAKF, pinned by SHA-256; the build fails if it differs.
#
# Bump a version by changing its ARG; nothing else refers to it. The one
# exception is RAKF_VERSION, which also needs new RAKF_ZIP_SHA256 and
# RAKF_IEZCTGPL_SHA256 values (sha256sum of the two downloads).
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
ARG HERCULES_REPO=https://github.com/SDL-Hercules-390/hyperion.git

# Debian trixie, as the runtime of mainframed767/mvsce, so the binaries
# find the same libraries. Built the way ../hercules builds it: a portable
# -O3 instead of hercules-helper's -march=native, which would SIGILL on a
# host whose CPU lacks the build machine's instructions. Regina is there
# because mainframed767/hercules builds with it too.
FROM debian:trixie AS hercules

ARG HERCULES_REF
ARG HERCULES_REPO

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       sudo time git curl wget ca-certificates python3 \
       build-essential autoconf automake libtool pkg-config m4 flex bison \
       cmake unzip make gcc g++ gawk libltdl-dev zlib1g-dev libbz2-dev \
       regina-rexx libregina3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/wrljet/hercules-helper.git /opt/hercules-helper

# HERCULES_REPO: the Hyperion repository to clone. hercules-helper
# hard-codes it in its flavor config, so it is rewritten there; a fork
# (e.g. https://github.com/mvslovers/hyperion.git) makes its branches
# and commits reachable for HERCULES_REF.
RUN sed -i "s|^git_repo_hercules=.*|git_repo_hercules=${HERCULES_REPO}|" \
      /opt/hercules-helper/sdl-hyperion.conf /opt/hercules-helper/hercules-helper.conf \
    && grep -qx "git_repo_hercules=${HERCULES_REPO}" /opt/hercules-helper/sdl-hyperion.conf

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
ARG HERCULES_REPO
ARG UFSD_VERSION=1.4.0
ARG HTTPD_VERSION=4.3.0
ARG MVSMF_VERSION=1.3.0
ARG FTPD_VERSION=1.2.0
ARG RAKF_VERSION=2.0.0
# TK5INST.zip of the RAKF release: trkf200.xmi, the TK5 Update 6 install
# deck. It has no IEZCTGPL (TK5 has that macro in SYS1.MACLIB, MVS/CE does
# not); the one of the same tag is added from the repository.
# The v2.0.0 asset was replaced upstream on 2026-10-22 (same tag, RDEFINE
# now checks class and profile for duplicates); this is the new one.
ARG RAKF_ZIP_SHA256=f38359ef3430ca305bbbaf11058811efbba1134a5db7a9d52112756c837f1c1c
ARG RAKF_IEZCTGPL_SHA256=9b4564f758063f2a9eecfe13eef02cef3d57ef06685637e1abe331e5dde9dae0

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
ADD https://github.com/mvslovers/ftpd/releases/download/v${FTPD_VERSION}/ftpd-${FTPD_VERSION}-load.xmit /tmp/ftpd.xmit
ADD --checksum=sha256:${RAKF_ZIP_SHA256} https://github.com/MVS-sysgen/RAKF/releases/download/v${RAKF_VERSION}/TK5INST.zip /tmp/rakf/TK5INST.zip
ADD --checksum=sha256:${RAKF_IEZCTGPL_SHA256} https://raw.githubusercontent.com/MVS-sysgen/RAKF/v${RAKF_VERSION}/MACLIB/IEZCTGPL.hlasm /tmp/rakf/IEZCTGPL.hlasm

# One CPU instead of MVS/CE's two. With NUMCPU 2 the IPL stalled in 2 of
# 24 starts in ways that both involve CP01 (stuck right after CP00 reset
# it by SIGP; CP01 in disabled wait 064 while CP00 spins); with NUMCPU 1,
# 0 of 24 (mvs-docker runs 36890781934/36890792177 vs 36892915143/
# 36892926001, brexx370#277). The cause is not known. MVSCE_NUMCPU=2 at
# run time restores two CPUs.
RUN sed -i 's/^NUMCPU .*/NUMCPU    1/' /MVSCE/conf/local.cnf \
    && grep -q '^NUMCPU    1$' /MVSCE/conf/local.cnf

COPY setup_mvsce.py /tmp/setup_mvsce.py

# Starts Hercules, IPLs MVS, installs RAKF 2.0.0, IPLs again with CLPA,
# installs the modules, verifies the running RAKF, server and mvsMF levels
# and shuts down. The modified DASDs under /MVSCE/DASD/ are baked into this
# layer; the base image's entrypoint copies them to /dasd.
RUN cd /MVSCE && UFSD_VERSION=${UFSD_VERSION} HTTPD_VERSION=${HTTPD_VERSION} \
    MVSMF_VERSION=${MVSMF_VERSION} FTPD_VERSION=${FTPD_VERSION} \
    HERCULES_REF=${HERCULES_REF} python3 -u /tmp/setup_mvsce.py \
    && rm -f /tmp/ufsd.xmit /tmp/httpd.xmit /tmp/mvsmf.xmit /tmp/ftpd.xmit \
       /tmp/setup_mvsce.py \
    && rm -rf /tmp/rakf

# Wraps the base image's ./mvs.sh so that the Hercules log and the console
# hardcopy show up in `docker logs` (see entrypoint.sh).
COPY --chmod=755 entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

LABEL org.opencontainers.image.source="https://github.com/mvslovers/mvs-docker" \
      org.opencontainers.image.description="MVS/CE ${MVSCE_VERSION} with UFSD ${UFSD_VERSION}, HTTPD ${HTTPD_VERSION}, mvsMF ${MVSMF_VERSION}, FTPD ${FTPD_VERSION} and RAKF ${RAKF_VERSION}, Hercules ${HERCULES_REF}" \
      io.mvslovers.mvsce.version="${MVSCE_VERSION}" \
      io.mvslovers.hercules.ref="${HERCULES_REF}" \
      io.mvslovers.hercules.repo="${HERCULES_REPO}" \
      io.mvslovers.ufsd.version="${UFSD_VERSION}" \
      io.mvslovers.httpd.version="${HTTPD_VERSION}" \
      io.mvslovers.mvsmf.version="${MVSMF_VERSION}" \
      io.mvslovers.ftpd.version="${FTPD_VERSION}" \
      io.mvslovers.rakf.version="${RAKF_VERSION}" \
      io.mvslovers.target.dist="mvsce" \
      io.mvslovers.target.user="IBMUSER" \
      io.mvslovers.target.password="SYS1" \
      io.mvslovers.target.hlq="IBMUSER" \
      io.mvslovers.target.volume="WORK00" \
      io.mvslovers.target.jobclass="A" \
      io.mvslovers.target.msgclass="H" \
      io.mvslovers.target.hercules-user="hercules" \
      io.mvslovers.target.hercules-password="hercules" \
      io.mvslovers.target.ports="8080:mvsmf 3270:tn3270 2121:ftp 8888:hercules 3505:reader_ascii 3506:reader_ebcdic"

# io.mvslovers.target.*: what mvsce-target prints for an instance (user,
# HLQ, the volume and classes for mbt, the published guest ports); the
# tk5 image carries its own.
EXPOSE 2121 3270 3505 3506 8080 8888
