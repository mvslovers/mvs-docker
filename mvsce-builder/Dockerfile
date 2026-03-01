FROM mainframed767/mvsce:latest

USER root

# Download mvsMF XMIT from GitHub release
ADD https://github.com/mvslovers/mvsmf/releases/download/current/mvsmf.xmit /tmp/mvsmf.xmit

# Copy setup script
COPY setup_mvsce.py /tmp/setup_mvsce.py

# Run setup: starts Hercules, IPLs MVS, installs HTTPD + mvsMF,
# shuts down. Modified DASDs at /MVSCE/DASD/ are baked into this layer.
# (The VOLUME declaration on /dasd is irrelevant - we work with /MVSCE/DASD/)
RUN cd /MVSCE && python3 -u /tmp/setup_mvsce.py

EXPOSE 3270 3505 3506 1080 8888
