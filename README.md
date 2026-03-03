# mvs-docker

Docker images for MVS 3.8j development and CI/CD workflows.

## Images

### mvs-dev

Headless development container for MVS 3.8j projects. Contains all build tools,
editors, and CLI utilities needed to cross-compile C to S/370 assembler and
interact with a remote MVS system via the mvsMF REST API.

**Image:** `ghcr.io/mvslovers/mvs-dev` (public)

This image does **not** contain MVS itself. It connects to an external MVS
system (e.g. a separate mvsce-builder container, remote TK4-/TK5) configured
via `.env` variables.

#### Included Tools

| Category | Tools |
|----------|-------|
| Compilers / Build | clang, clangd, gcc, make, c2asm370 v1.2 |
| Editors | vim, neovim (latest) + LazyVim |
| Shell | zsh + oh-my-zsh (git, docker, autosuggestions, syntax-highlighting) |
| Node.js | Node.js 22 LTS, npm |
| MVS Tools | Zowe CLI, c2asm370 |
| Neovim Deps | fzf, ripgrep, fd, tree-sitter-cli, lazygit |
| Utilities | python3, curl, jq, git, gh CLI, docker CLI |

#### Standalone Usage

```bash
docker pull ghcr.io/mvslovers/mvs-dev

# Interactive shell with current directory mounted as workspace
docker run -it -v "$(pwd)":/home/dev/workspace ghcr.io/mvslovers/mvs-dev
```

#### Docker-outside-Docker

To use the Docker CLI inside the container, bind-mount the host Docker socket.
This lets you start an mvsce-builder as the MVS backend directly from within
the devcontainer:

```bash
# Start mvs-dev with Docker socket access
docker run -it \
  -v "$(pwd)":/home/dev/workspace \
  -v /var/run/docker.sock:/var/run/docker.sock \
  ghcr.io/mvslovers/mvs-dev

# Inside the container, start an mvsce-builder as MVS backend
docker run -d --name mvs \
  -p 3270:3270 -p 3505:3505 -p 3506:3506 -p 1080:1080 -p 8888:8888 \
  ghcr.io/mvslovers/mvsce-builder
```

#### VS Code Devcontainer / GitHub Codespaces

Create a `.devcontainer/devcontainer.json` in your project:

```json
{
  "image": "ghcr.io/mvslovers/mvs-dev:latest",
  "remoteUser": "dev",
  "mounts": [
    "source=/var/run/docker.sock,target=/var/run/docker.sock,type=bind"
  ]
}
```

Open the project in VS Code with the Dev Containers extension, or push to
GitHub and open in Codespaces.

#### Connecting to MVS

The container connects to an external MVS system via environment variables.
Create a `.env` file in your project (see each project's `.env.example`):

```bash
MVSMF_HOST=192.168.1.100   # IP of your MVS system
MVSMF_PORT=1080             # mvsMF API port
MVSMF_USER=IBMUSER          # MVS userid
MVSMF_PASSWORD=SYS1          # MVS password
```

Build scripts (`mvsasm`, `mvslink`, etc.) read these variables to communicate
with MVS via the mvsMF REST API.

---

### mvsce-builder

Build image for CI pipelines. Contains a fully operational MVS/CE system
with HTTPD and mvsMF (z/OSMF-compatible REST API) pre-installed.

**Image:** `ghcr.io/mvslovers/mvsce-builder` (public)

Use cases:
- Cross-compile C to S/370 assembler, then assemble + link on MVS
- Upload sources, submit JCL, poll results via REST API
- Generate XMIT distribution files

#### Usage

```bash
docker pull ghcr.io/mvslovers/mvsce-builder

docker run -d --name mvs-build \
  -p 3270:3270 -p 3505:3505 -p 3506:3506 -p 1080:1080 -p 8888:8888 \
  ghcr.io/mvslovers/mvsce-builder

# Wait for MVS to IPL (~15s), then verify mvsMF is running
curl -u IBMUSER:SYS1 http://localhost:1080/zosmf/info
```

### mvstk4-test / mvstk5-test / mvsce-test (planned)

Test images based on TK4-, TK5, and MVS/CE for validating builds
against different MVS configurations.

**Status:** Planned

## Build

```bash
# Build all images
make all

# Build individual images
make mvsce-builder
make mvs-dev

# Push all images to ghcr.io
make publish

# Push individual images
make publish-mvsce-builder
make publish-mvs-dev

# Smoke tests
make test-mvsce-builder
make test-mvs-dev

# Cleanup
make clean
```

## Ports (mvsce-builder)

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
├── mvs-dev/           mvs-dev image (headless devcontainer)
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
