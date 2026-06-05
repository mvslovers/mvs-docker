# mvs-docker

Multi-arch Docker / OCI images for running and building **MVS 3.8j on Hercules**.

The foundational image is **`hercules`** — a ready-to-run build of the
[SDL-Hyperion](https://github.com/SDL-Hercules-390/hyperion) S/370 emulator.
The other images (development container, MVS/CE builder, test images) build on
top of it.

## Images

| Image | Purpose | Status |
|-------|---------|--------|
| [`hercules`](#hercules) | SDL-Hyperion S/370 emulator — base image | published, multi-arch |
| [`mvs-dev`](#mvs-dev) | Headless development container | published, amd64 |
| [`mvsce-builder`](#mvsce-builder) | MVS/CE + HTTPD + mvsMF for CI | published, outdated |
| `mvstk4-test` / `mvstk5-test` / `mvsce-test` | Test images | planned |

All images are published to `ghcr.io/mvslovers/<name>` and are public.

> **Note on architectures:** `hercules` is multi-arch (`amd64` + `arm64`).
> `mvs-dev` is built by CI and reproducible, but `amd64`-only for now — its
> `c2asm370` cross-compiler has no native arm64 build yet. It does **not** use
> the `hercules` base image (it is a toolchain that talks to a *remote* MVS, not
> an MVS runtime). `mvsce-builder` is still the outdated one: built locally with
> `make`, `amd64`-only, and slated to be reworked onto the `hercules` base,
> multi-arch, and GitHub Actions.

---

## hercules

`ghcr.io/mvslovers/hercules` — the **SDL-Hyperion** Hercules emulator, built
from [SDL-Hercules-390/hyperion](https://github.com/SDL-Hercules-390/hyperion)
via [hercules-helper](https://github.com/wrljet/hercules-helper).

- **Multi-arch:** `linux/amd64` and `linux/arm64` (one tag, the right arch is
  pulled automatically — including Apple silicon).
- **No MVS inside** — this is just the emulator. You bring your own DASD volumes
  and Hercules configuration.

### Quick start

Print the Hercules version (works the same with Docker and Apple's `container`):

```bash
# Docker
docker run --rm ghcr.io/mvslovers/hercules:latest hercules --version

# Apple container
container run --rm ghcr.io/mvslovers/hercules:latest hercules --version
```

> Apple's `container` CLI mirrors Docker's flags (`-it`, `-d`, `--rm`,
> `--name`, `-v host:container`, `-p host:container`). Every example below works
> with either — just swap `docker` ↔ `container`.

### Tags

Versioning follows the common Docker convention: `latest` is the newest stable
**release**, dev builds live under their own tags, and every release is also
available pinned.

| Tag | Points to | Use it when |
|-----|-----------|-------------|
| `latest` | newest stable release | you just want a current, stable Hercules |
| `4` | newest `4.x` release | follow the major line |
| `4.9` | newest `4.9.x` patch | follow a minor line, auto-get patches |
| `4.9.1`, `4.9.0`, `4.8.0`, `4.7.0` | that exact release | full reproducibility |
| `edge` | current Hyperion `main` HEAD (DEV), rebuilt on Dockerfile changes | test the bleeding edge |
| `nightly` | Hyperion `main` HEAD, rebuilt daily | track upstream development |

**Pin what you depend on.** For anything reproducible — and *especially* for
base images — pin an exact (`4.9.1`) or minor (`4.9`) tag. Avoid building on
`latest`, `edge`, or `nightly`.

Currently published releases: **`4.7.0`, `4.8.0`, `4.9.0`, `4.9.1`**. New
SDL-Hyperion release tags are picked up and built automatically. Releases older
than `4.7` are not provided — their sources no longer compile with the current
GCC/C toolchain.

### Run with your own DASD and configuration

The image's working directory and volume is **`/hercules`**. Keep your Hercules
config and DASD volume files in a local directory and mount it there:

```text
my-mvs/
├── conf/
│   └── mvs.cnf        # your Hercules config
└── dasd/
    └── ...               # your DASD volume files (referenced by the .cnf)
```

```bash
# Docker
docker run --rm -it \
  -v "$PWD":/hercules \
  -p 3270:3270 \
  ghcr.io/mvslovers/hercules:4.9 \
  hercules -f conf/mvs.cnf

# Apple container
container run --rm -it \
  -v "$PWD":/hercules \
  -p 3270:3270 \
  ghcr.io/mvslovers/hercules:4.9 \
  hercules -f conf/mvs.cnf
```

- `-it` gives Hercules an interactive console (panel).
- Publish whatever ports your `.cnf` binds — commonly `3270` for TN3270, and
  `8038` for the built-in HTTP console. Add more `-p` flags as needed.
- Paths in your `.cnf` are resolved relative to `/hercules`, so `conf/...` and
  `dasd/...` just work.

### Use it like a locally installed `hercules`

Add an alias so the containerized emulator behaves as if it were installed on
your host — running against whatever directory you're currently in:

```bash
# ~/.zshrc or ~/.bashrc  (Docker)
alias hercules='docker run --rm -it -v "$PWD":/hercules ghcr.io/mvslovers/hercules:4.9 hercules'

# Apple container
alias hercules='container run --rm -it -v "$PWD":/hercules ghcr.io/mvslovers/hercules:4.9 hercules'
```

Then, from any MVS directory:

```bash
cd my-mvs
hercules --version
hercules -f conf/mvs.cnf
```

### Use as a base image

Bake your configuration and DASD into your own image by building `FROM`
hercules:

```dockerfile
FROM ghcr.io/mvslovers/hercules:4.9

# Your MVS system: config + DASD volumes
COPY conf/ /hercules/conf/
COPY dasd/ /hercules/dasd/

EXPOSE 3270 8038
CMD ["hercules", "-f", "conf/mvs.cnf"]
```

```bash
docker build -t my-mvs .
docker run --rm -it -p 3270:3270 my-mvs
```

**Pin a version** (here `4.9`) so an upstream Hercules change never silently
alters your base. This is exactly how the planned `mvsce` / `tk4-` / `tk5`
distribution images will build on `hercules`.

### How it's built

`hercules` is built and published by GitHub Actions (not `make`):

- a **daily poll** checks SDL-Hyperion for release tags and builds any that are
  missing (smallest version first), then updates the rolling aliases and
  `latest`;
- **`edge`** is rebuilt whenever the `hercules/` Dockerfile changes;
- **`nightly`** rebuilds `main` HEAD once a day;
- a single version can be built on demand via the **Build Hercules Version**
  workflow (input is the Hyperion tag, e.g. `4.9.1`).

---

## mvs-dev

Headless development container for MVS 3.8j projects. Contains all build tools,
editors, and CLI utilities needed to cross-compile C to S/370 assembler and
interact with a remote MVS system via the mvsMF REST API.

**Image:** `ghcr.io/mvslovers/mvs-dev` (public)

This image does **not** contain MVS itself. It connects to an external MVS
system (e.g. a separate mvsce-builder container, remote TK4-/TK5) configured
via `.env` variables.

### Tags

mvs-dev is versioned by its core tool — the **c2asm370** cross-compiler:

| Tag | Points to |
|-----|-----------|
| `latest` | most recent build |
| `1.2` | newest build containing c2asm370 1.2 (rolling) |
| `1.2-YYYYMMDD` | an immutable snapshot for that day's toolchain |

The other tools (neovim, Zowe, …) are pinned in the Dockerfile and may refresh
within a c2asm370 line; the dated snapshot captures that exact state. **Pin a
`1.2-YYYYMMDD` tag** (e.g. in your `.devcontainer/devcontainer.json`) for a fully
reproducible dev environment.

### Included Tools

| Category | Tools |
|----------|-------|
| Compilers / Build | clang, clangd, gcc, make, c2asm370 v1.2 |
| Editors | vim, neovim (latest) + LazyVim |
| Shell | zsh + oh-my-zsh (git, docker, autosuggestions, syntax-highlighting) |
| Node.js | Node.js 22 LTS, npm |
| MVS Tools | Zowe CLI, c2asm370 |
| Neovim Deps | fzf, ripgrep, fd, tree-sitter-cli, lazygit |
| Utilities | python3, curl, jq, git, gh CLI, docker CLI |

### Standalone Usage

```bash
docker pull ghcr.io/mvslovers/mvs-dev

# Interactive shell with current directory mounted as workspace
docker run -it -v "$(pwd)":/home/dev/workspace ghcr.io/mvslovers/mvs-dev
```

### Docker-outside-Docker with mvsce-builder

To start an mvsce-builder as the MVS backend from within mvs-dev,
bind-mount the host Docker socket and use a shared Docker network so both
containers can communicate by name:

```bash
# Create a shared network
docker network create mvs-net

# Start mvs-dev with Docker socket access on the shared network
docker run -it --network mvs-net \
  -v "$(pwd)":/home/dev/workspace \
  -v /var/run/docker.sock:/var/run/docker.sock \
  ghcr.io/mvslovers/mvs-dev

# Inside the container, start mvsce-builder on the same network
docker run -d --name mvs --network mvs-net \
  -p 3270:3270 -p 8888:8888 \
  ghcr.io/mvslovers/mvsce-builder

# The mvsMF API is now reachable at http://mvs:1080 from within mvs-dev
curl -u IBMUSER:SYS1 http://mvs:1080/zosmf/info
```

Set `MVSMF_HOST=mvs` and `MVSMF_PORT=1080` in your project's `.env` file.

### Connecting to MVS

The container connects to an external MVS system via environment variables.
Create a `.env` file in your project (see each project's `.env.example`):

```bash
MVSMF_HOST=mvs              # container name on shared network, or IP/hostname
MVSMF_PORT=1080              # mvsMF API port
MVSMF_USER=IBMUSER           # MVS userid
MVSMF_PASSWORD=SYS1          # MVS password
```

Build scripts (`mvsasm`, `mvslink`, etc.) read these variables to communicate
with MVS via the mvsMF REST API.

---

## mvsce-builder

Build image for CI pipelines. Contains a fully operational MVS/CE system
with HTTPD and mvsMF (z/OSMF-compatible REST API) pre-installed.

**Image:** `ghcr.io/mvslovers/mvsce-builder` (public)

Use cases:
- Cross-compile C to S/370 assembler, then assemble + link on MVS
- Upload sources, submit JCL, poll results via REST API
- Generate XMIT distribution files

### Usage

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

`hercules` and `mvs-dev` are built and published by GitHub Actions (on changes
under their respective directories). The remaining images are still built locally
with `make` and are being reworked to build on the `hercules` base image and move
to GitHub Actions as well:

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

```text
mvs-docker/
├── hercules/          hercules image (SDL-Hyperion emulator, base image)
├── mvs-dev/           mvs-dev image (headless development container)
├── mvsce-builder/     mvsce-builder image (MVS/CE + HTTPD + mvsMF)
├── mvstk4-test/       TK4- test image (planned)
├── mvstk5-test/       TK5 test image (planned)
├── mvsce-test/        MVS/CE test image (planned)
├── common/            shared scripts and configs
├── .github/workflows/ CI: hercules build/release/retag/nightly
├── Makefile           build/push/test automation (non-hercules images)
└── README.md
```

## Related Projects

| Project | Purpose |
|---------|---------|
| [SDL-Hyperion](https://github.com/SDL-Hercules-390/hyperion) | The Hercules S/370 emulator built into the `hercules` image |
| [hercules-helper](https://github.com/wrljet/hercules-helper) | Build automation used to compile Hercules |
| [crent370](https://github.com/mvslovers/crent370) | C runtime library for MVS 3.8j |
| [c2asm370](https://github.com/mvslovers/c2asm370) | Cross-compiler C to S/370 |
| [mvsmf](https://github.com/mvslovers/mvsmf) | z/OSMF REST API for MVS 3.8j |
| [mvsce](https://github.com/MVS-sysgen/docker-mvsce) | Base MVS/CE Docker image |
