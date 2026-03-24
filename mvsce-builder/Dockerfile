FROM mainframed767/mvsce:latest

USER root

# Download UFSD load modules from GitHub release
ADD https://github.com/mvslovers/ufsd/releases/download/v1.0.0-dev/ufsd-1.0.0-dev-load.tar.gz /tmp/ufsd-load.tar.gz
RUN cd /tmp && tar xzf ufsd-load.tar.gz \
    && mv ufsd-1.0.0-dev/mvs/ufsd-1.0.0-dev-syslmod.xmit ufsd.xmit \
    && rm -rf ufsd-1.0.0-dev ufsd-load.tar.gz

# Download HTTPD 4.x assets from GitHub release
ADD https://github.com/mvslovers/httpd/releases/download/v4.0.0-dev/httpd-4.0.0-dev-syslmod.xmit /tmp/httpd.xmit
ADD https://github.com/mvslovers/httpd/releases/download/v4.0.0-dev/wwwroot_v3.img /tmp/wwwroot_v3.img

# Download mvsMF XMIT from GitHub release
ADD https://github.com/mvslovers/mvsmf/releases/download/v1.0.0-dev/mvsmf-1.0.0-dev-syslmod.xmit /tmp/mvsmf.xmit

# Install Go and ufsd-utils
RUN apt-get update && apt-get install -y --no-install-recommends golang-go \
    && GOBIN=/usr/local/bin go install github.com/mvslovers/ufsd-utils/cmd/ufsd-utils@latest \
    && apt-get purge -y golang-go && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* /root/go

# Copy setup script
COPY setup_mvsce.py /tmp/setup_mvsce.py

# Run setup: starts Hercules, IPLs MVS, installs components,
# shuts down. Modified DASDs at /MVSCE/DASD/ are baked into this layer.
# (The VOLUME declaration on /dasd is irrelevant - we work with /MVSCE/DASD/)
RUN cd /MVSCE && python3 -u /tmp/setup_mvsce.py

EXPOSE 3270 3505 3506 8080 8888
