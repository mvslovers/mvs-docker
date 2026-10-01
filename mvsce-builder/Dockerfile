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

ARG MVSCE_VERSION=3.0.0
FROM mainframed767/mvsce:${MVSCE_VERSION}

ARG MVSCE_VERSION
ARG UFSD_VERSION=1.3.0
ARG HTTPD_VERSION=4.1.0
ARG MVSMF_VERSION=1.1.0

USER root

ADD https://github.com/mvslovers/ufsd/releases/download/v${UFSD_VERSION}/ufsd-${UFSD_VERSION}-load.xmit /tmp/ufsd.xmit
ADD https://github.com/mvslovers/httpd/releases/download/v${HTTPD_VERSION}/httpd-${HTTPD_VERSION}-load.xmit /tmp/httpd.xmit
ADD https://github.com/mvslovers/mvsmf/releases/download/v${MVSMF_VERSION}/mvsmf-${MVSMF_VERSION}-load.xmit /tmp/mvsmf.xmit

COPY setup_mvsce.py /tmp/setup_mvsce.py

# Starts Hercules, IPLs MVS, installs the modules, verifies the running
# mvsMF level and shuts down. The modified DASDs under /MVSCE/DASD/ are baked
# into this layer; the base image's entrypoint copies them to /dasd.
RUN cd /MVSCE && UFSD_VERSION=${UFSD_VERSION} HTTPD_VERSION=${HTTPD_VERSION} \
    MVSMF_VERSION=${MVSMF_VERSION} python3 -u /tmp/setup_mvsce.py \
    && rm -f /tmp/ufsd.xmit /tmp/httpd.xmit /tmp/mvsmf.xmit /tmp/setup_mvsce.py

# Wraps the base image's ./mvs.sh so that the Hercules log and the console
# hardcopy show up in `docker logs` (see entrypoint.sh).
COPY --chmod=755 entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

LABEL org.opencontainers.image.source="https://github.com/mvslovers/mvs-docker" \
      org.opencontainers.image.description="MVS/CE ${MVSCE_VERSION} with UFSD ${UFSD_VERSION}, HTTPD ${HTTPD_VERSION} and mvsMF ${MVSMF_VERSION}" \
      io.mvslovers.mvsce.version="${MVSCE_VERSION}" \
      io.mvslovers.ufsd.version="${UFSD_VERSION}" \
      io.mvslovers.httpd.version="${HTTPD_VERSION}" \
      io.mvslovers.mvsmf.version="${MVSMF_VERSION}"

EXPOSE 3270 3505 3506 8080 8888
