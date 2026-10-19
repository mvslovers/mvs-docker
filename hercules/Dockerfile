FROM ubuntu:26.04 AS builder

ARG TARGETARCH
ARG TARGETPLATFORM
ARG HERCULES_FLAVOR=sdl-hyperion
# Optional: pin Hercules to a specific Hyperion git ref (e.g. a release tag
# like "Release_4.9.1"). Empty = build the current main HEAD (DEV build).
ARG HERCULES_REF=
ARG HERCULES_REPO=https://github.com/SDL-Hercules-390/hyperion.git

ENV DEBIAN_FRONTEND=noninteractive

RUN echo "Building for ${TARGETPLATFORM} (${TARGETARCH})"

RUN rm -rf /var/lib/apt/lists/* && \
  apt-get clean && \
  apt-get update || apt-get update && \
  apt-get install -y \
  sudo \
  time \
  git \
  curl \
  wget \
  ca-certificates \
  python3 \
  build-essential \
  autoconf \
  automake \
  libtool \
  pkg-config \
  m4 \
  flex \
  bison \
  cmake \
  unzip \
  tar \
  make \
  gcc \
  g++ \
  gawk \
  libltdl-dev \
  zlib1g-dev \
  libbz2-dev && \
  apt-get clean && \
  rm -rf /var/lib/apt/lists/*

WORKDIR /opt

RUN git clone https://github.com/wrljet/hercules-helper.git

# HERCULES_REPO: the Hyperion repository to clone. hercules-helper
# hard-codes it in its flavor config, so it is rewritten there; a fork
# (e.g. https://github.com/mvslovers/hyperion.git) makes its branches
# and commits reachable for HERCULES_REF.
RUN sed -i "s|^git_repo_hercules=.*|git_repo_hercules=${HERCULES_REPO}|" \
      /opt/hercules-helper/sdl-hyperion.conf /opt/hercules-helper/hercules-helper.conf \
    && grep -qx "git_repo_hercules=${HERCULES_REPO}" /opt/hercules-helper/sdl-hyperion.conf

WORKDIR /build

# Build with a portable -O3 instead of hercules-helper's default -march=native.
# -march=native bakes in the build runner's CPU instructions (e.g. ARMv9/SVE2 on
# GitHub's arm64 runners), which crash with SIGILL on other hosts such as Apple
# silicon. opt_configure_optimization overrides the helper's optimization flags.
RUN opt_configure_optimization="-O3" \
  /opt/hercules-helper/hercules-buildall.sh \
  --auto \
  --flavor=${HERCULES_FLAVOR} \
  ${HERCULES_REF:+--git-commit=${HERCULES_REF}} \
  --accept-root \
  --no-packages \
  --no-tests \
  --no-setcap \
  --no-envscript \
  --no-bashrc \
  --prefix=/usr/local

FROM ubuntu:26.04

# Runtime dependencies not contained in the copied /usr/local:
#   netbase        -> /etc/protocols + /etc/services (Hercules socket setup,
#                     getprotobyname); without it networking fails
#   libregina3-dev -> provides the unversioned libregina.so symlink that
#                     Hercules dlopen()s at runtime for REXX automation
#                     (see the hercules-helper README)
#   zlib1g, libbz2-1.0 -> runtime libs for reading zlib/bzip2-compressed
#                     CCKD DASD images (built with zlib1g-dev/libbz2-dev above)
RUN apt-get update && \
  apt-get install -y --no-install-recommends netbase libregina3-dev zlib1g libbz2-1.0 && \
  apt-get clean && \
  rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local /usr/local

RUN echo "/usr/local/lib" > /etc/ld.so.conf.d/hercules.conf && \
  ldconfig

WORKDIR /hercules

VOLUME ["/hercules"]

CMD ["/bin/bash"]

