FROM mainframed767/mvsce:latest

USER root

# Download mvsMF XMIT from GitHub release
ADD https://github.com/mvslovers/mvsmf/releases/download/current/mvsmf.xmit /tmp/mvsmf.xmit

# Download crent370 release and extract XMIT files
ADD https://github.com/mvslovers/crent370/releases/download/v0.1.0/crent370-0.1.0-mvs.tar.gz /tmp/crent370-mvs.tar.gz
RUN cd /tmp && tar xzf crent370-mvs.tar.gz \
    && mv crent370-0.1.0/CRENT370.V0R1M0.MACLIB.XMIT . \
    && mv crent370-0.1.0/CRENT370.V0R1M0.NCALIB.XMIT . \
    && rm -rf crent370-0.1.0 crent370-mvs.tar.gz

# Copy setup script
COPY setup_mvsce.py /tmp/setup_mvsce.py

# Run setup: starts Hercules, IPLs MVS, installs HTTPD + mvsMF + crent370,
# shuts down. Modified DASDs at /MVSCE/DASD/ are baked into this layer.
# (The VOLUME declaration on /dasd is irrelevant - we work with /MVSCE/DASD/)
RUN cd /MVSCE && python3 -u /tmp/setup_mvsce.py

EXPOSE 3270 3505 3506 1080 8888
