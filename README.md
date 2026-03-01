# mvs-docker

Docker images for MVS 3.8j CI/CD workflows.

## Images

### build (MVS/CE + HTTPD + mvsMF)

Build image for CI pipelines. Contains a fully operational MVS/CE system
with HTTPD and mvsMF (z/OSMF-compatible REST API) pre-installed.

Use cases:
- Cross-compile C to S/370 assembler, then assemble + link on MVS
- Upload sources, submit JCL, poll results via REST API
- Generate XMIT distribution files

**Status:** Work in progress

### test (planned)

Test images based on TK4-, TK5, and MVS/CE for validating builds
against different MVS configurations.

**Status:** Planned

## Quick Start

```bash
# Build image
docker build -t mvs-docker-build build/

# Run
docker run -d --name mvs-build \
  -p 3270:3270 -p 3505:3505 -p 8080:8080 -p 8888:8888 \
  mvs-docker-build

# Wait for MVS to IPL, then test mvsMF
curl http://localhost:8080/zosmf/info
```

## Ports

| Port | Service |
|------|---------|
| 3270 | TN3270 (terminal access) |
| 3505 | JES2 ASCII socket reader |
| 8080 | HTTPD + mvsMF REST API |
| 8888 | Hercules web console |

## Related Projects

| Project | Purpose |
|---------|---------|
| [crent370](https://github.com/mvslovers/crent370) | C runtime library for MVS 3.8j |
| [c2asm370](https://github.com/mvslovers/c2asm370) | Cross-compiler C to S/370 |
| [mvsmf](https://github.com/mvslovers/mvsmf) | z/OSMF REST API for MVS 3.8j |
| [mvsce](https://github.com/MVS-sysgen/docker-mvsce) | Base MVS/CE Docker image |
