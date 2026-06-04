FROM ubuntu:26.04 AS builder

ARG TARGETARCH
ARG TARGETPLATFORM
ARG HERCULES_FLAVOR=sdl-hyperion
# Optional: pin Hercules to a specific Hyperion git ref (e.g. a release tag
# like "Release_4.9.1"). Empty = build the current main HEAD (DEV build).
ARG HERCULES_REF=

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
  g++ && \
  apt-get clean && \
  rm -rf /var/lib/apt/lists/*

WORKDIR /opt

RUN git clone https://github.com/wrljet/hercules-helper.git

WORKDIR /build

RUN /opt/hercules-helper/hercules-buildall.sh \
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

COPY --from=builder /usr/local /usr/local

RUN echo "/usr/local/lib" > /etc/ld.so.conf.d/hercules.conf && \
  ldconfig

WORKDIR /hercules

VOLUME ["/hercules"]

CMD ["/bin/bash"]

