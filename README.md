# mvs-docker

Docker images for MVS 3.8j CI/CD workflows.

## Images

### mvsce-builder

Build image for CI pipelines. Contains a fully operational MVS/CE system
with HTTPD and mvsMF (z/OSMF-compatible REST API) pre-installed.

**Image:** `ghcr.io/mvslovers/mvsce-builder`

Use cases:
- Cross-compile C to S/370 assembler, then assemble + link on MVS
- Upload sources, submit JCL, poll results via REST API
- Generate XMIT distribution files

### mvstk4-test / mvstk5-test / mvsce-test (planned)

Test images based on TK4-, TK5, and MVS/CE for validating builds
against different MVS configurations.

**Status:** Planned

## Quick Start

```bash
# Pull image
docker pull ghcr.io/mvslovers/mvsce-builder

# Run
docker run -d --name mvs-build \
  -p 3270:3270 -p 3505:3505 -p 3506:3506 -p 1080:1080 -p 8888:8888 \
  ghcr.io/mvslovers/mvsce-builder

# Wait for MVS to IPL (~60s), then test mvsMF
curl -u IBMUSER:SYS1 http://localhost:1080/zosmf/info
```

## Build

```bash
# Build image (runs on mvsdev.lan via SSH)
make mvsce-builder

# Build + push to ghcr.io
make publish-mvsce-builder

# Smoke test (start, wait for IPL, check mvsMF, cleanup)
make test-mvsce-builder
```

## Ports

| Port | Service |
|------|---------|
| 3270 | TN3270 (terminal access) |
| 3505 | JES2 ASCII socket reader |
| 3506 | JES2 EBCDIC card reader |
| 1080 | HTTPD + mvsMF REST API |
| 8888 | Hercules web console |

## Repository Structure

```
mvs-docker/
├── mvsce-builder/     mvsce-builder image (MVS/CE + HTTPD + mvsMF)
├── mvstk4-test/       TK4- test image (planned)
├── mvstk5-test/       TK5 test image (planned)
├── mvsce-test/        MVS/CE test image (planned)
├── common/            shared scripts and configs
├── Makefile           build/push/test automation
└── README.md
```

## Related Projects

| Project | Purpose |
|---------|---------|
| [crent370](https://github.com/mvslovers/crent370) | C runtime library for MVS 3.8j |
| [c2asm370](https://github.com/mvslovers/c2asm370) | Cross-compiler C to S/370 |
| [mvsmf](https://github.com/mvslovers/mvsmf) | z/OSMF REST API for MVS 3.8j |
| [mvsce](https://github.com/MVS-sysgen/docker-mvsce) | Base MVS/CE Docker image |
