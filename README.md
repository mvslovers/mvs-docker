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
| [`mvsce`](#mvsce) | MVS/CE + UFSD + HTTPD + mvsMF + FTPD, for CI and disposable test instances | published, multi-arch |
| [`tk5`](#tk5) | TK5 (minimal configuration) + UFSD + HTTPD + mvsMF + FTPD, installed with SMP | published, multi-arch |

All images are published to `ghcr.io/mvslovers/<name>` and are public.

> **Note on architectures:** `hercules` and `mvsce` are multi-arch
> (`amd64` + `arm64`), both built by CI. `mvs-dev` is built by CI and
> reproducible, but `amd64`-only for now — its `c2asm370` cross-compiler has
> no native arm64 build yet. It does **not** use the `hercules` base image (it
> is a toolchain that talks to a *remote* MVS, not an MVS runtime).

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
system (e.g. a separate mvsce container, a remote TK5) configured
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

### Docker-outside-Docker with mvsce

To start an mvsce container as the MVS backend from within mvs-dev,
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

# Inside the container, start mvsce on the same network
docker run -d --rm --name mvs --network mvs-net \
  -p 3270:3270 -p 8888:8888 \
  ghcr.io/mvslovers/mvsce

# The mvsMF API is now reachable at http://mvs:8080 from within mvs-dev
curl -u IBMUSER:SYS1 'http://mvs:8080/zosmf/test?fn=version'
```

Set `MVSMF_HOST=mvs` and `MVSMF_PORT=8080` in your project's `.env` file.

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

## mvsce

A fully operational MVS/CE system with UFSD, HTTPD, mvsMF (z/OSMF-compatible
REST API) and FTPD installed and started at IPL, in the same state on every
start: the MVS side of CI pipelines and of disposable test instances
(`mvsce-target`, below). The build itself runs on the host (cc370); MVS
gets the deploy and the tests.

**Image:** `ghcr.io/mvslovers/mvsce` (public)

**Formerly `mvsce-builder`, frozen since 2026-10-19.**
`ghcr.io/mvslovers/mvsce-builder` stays pullable at its last level
(`:latest` and `:dev` = `sha256:a6096e33…`, the `mvsce:latest` of that day)
but gets no updates, so anything still naming it silently tests an aging
image. The link `mvsce-builder/mvsce-target` is gone. Use
`ghcr.io/mvslovers/mvsce` and `mvsce/mvsce-target`.

### What's inside

| Component | Version | Where |
|-----------|---------|-------|
| [MVS/CE](https://github.com/MVS-sysgen/sysgen) (`mainframed767/mvsce`) | 3.0.0 | base image |
| [Hercules](https://github.com/SDL-Hercules-390/hyperion) (SDL-Hyperion, `develop`) | `a742398074` (4.10.0.11783) | `/home/hercules/herctest/herc4x`, replacing MVS/CE's |
| [UFSD](https://github.com/mvslovers/ufsd) | 1.4.0 | `MVSLOVER.UFSD.LOADLIB` |
| [HTTPD](https://github.com/mvslovers/httpd) | 4.3.0 | `HTTPD.LINKLIB` |
| [mvsMF](https://github.com/mvslovers/mvsmf) | 1.3.0 | `HTTPD.LINKLIB` |
| [FTPD](https://github.com/mvslovers/ftpd) | 1.2.0 | `MVSLOVER.FTPD.LOADLIB` |

The versions are `ARG`s in `mvsce/Dockerfile`
(`MVSCE_VERSION`, `HERCULES_REF`, `UFSD_VERSION`, `HTTPD_VERSION`,
`MVSMF_VERSION`, `FTPD_VERSION`) and are recorded as image labels
(`io.mvslovers.<component>.version`, `io.mvslovers.hercules.ref`).

**Hercules is rebuilt, not taken from MVS/CE.** `mainframed767/mvsce:3.0.0`
carries a Hercules from March 2026 (`g5081b9ea`) without the 3215-C console
fix ([hyperion#889](https://github.com/SDL-Hercules-390/hyperion/pull/889)),
which can hang the IPL, and without the X'75' TCP/IP fixes the servers rely
on (#864, #870, #875, #885). A build stage on Debian trixie, MVS/CE's own
runtime, builds Hyperion at `HERCULES_REF` with a portable `-O3` into the
same prefix, so MVS/CE's `/mvs.sh` runs it unchanged. The build fails unless
`hercules --version` names `HERCULES_REF` and every binary and module finds
its libraries; the build-time IPL checks the running banner again. The
stage goes away once `mainframed767/mvsce` itself carries a Hercules at or
after that commit.

**A Hercules from a fork or branch:** `HERCULES_REPO` (default
`https://github.com/SDL-Hercules-390/hyperion.git`) names the repository to
clone; `HERCULES_REF` must then be a full commit SHA on any of its branches,
since the banner check compares SHAs. It is recorded as
`io.mvslovers.hercules.repo`, and `tk5/Dockerfile` and `hercules/Dockerfile`
take the same argument. On a Docker host, from the repository root:

```sh
docker build -t mvsce:fix mvsce \
  --build-arg HERCULES_REPO=https://github.com/mvslovers/hyperion.git \
  --build-arg HERCULES_REF=<sha>
```

MVS/CE 3.0.0 already installs UFSD, HTTPD, mvsMF and FTPD through MVP, but
does not start them, and its MVP packages predate fixes mvsMF depends on (e.g. listing
the spool of a job with many steps,
[mvsmf#374](https://github.com/mvslovers/mvsmf/issues/374)). The build keeps
everything MVP set up (procedures, `UFSDPRM0`, `FTPDPRM0`, the UFS disks) and
only:

- replaces the modules in the three load libraries with the pinned releases,
- writes `SYS2.PARMLIB(HTTPPRM0)` with the z/OSMF routes as mvsMF documents
  them (`/zosmf/*` is `AUTH=TOKEN`),
- rewrites `SYS2.PROCLIB(FTPD)` with the `HASPACE1` DD that FTPD's JES
  interface needs (MVP's procedure has only `HASPCKPT`),
- sets up RAKF for the two servers that drop from `STC` to an identity of
  their own at startup, as
  [FTPD_RAKF_SETUP.md](https://github.com/mvslovers/ftpd/blob/v1.2.0/docs/FTPD_RAKF_SETUP.md)
  and httpd's `docs/installation.md` (section 8) describe: the users `FTPD`
  and `HTTPD` (group `USER`, no operations authority, random passwords
  nobody keeps) and the facility `FTPAUTH`, granted to the `ADMIN` group
  only, so `IBMUSER` and `MVSCE01` may use FTP while `MVSCE02` and `FTPD`
  itself get `530 Not authorized for FTP access`,
- adds `S UFSD` / `S HTTPD` / `S FTPD` to `SYS1.PARMLIB(COMMND00)`.

It then starts all three and **fails unless** the `UFSD000I`/`HTTPD000I`/
`FTPD000I` banners and `/zosmf/test?fn=version` report the pinned versions,
neither server logs `RAKF0004`, `HTTPD004W` or `FTPD004W`, HTTPD logs
`HTTPD002I AUTHORIZED BY`, FTPD `FTPD004I STC IDENTITY SET TO FTPD/USER`, `FTPD001I READY` follows, an FTP login as `IBMUSER` succeeds and
one as `FTPD` is refused, so a build that installed nothing cannot be
published as the new level. The build jobs print to `printers/prt00e.txt`
(MSGCLASS A); a failed build shows its tail, a good one empties it.

### Usage

```bash
docker pull ghcr.io/mvslovers/mvsce

docker run -d --rm --name mvs-build \
  -p 3270:3270 -p 3505:3505 -p 3506:3506 -p 8080:8080 -p 8888:8888 \
  ghcr.io/mvslovers/mvsce

# Wait for MVS to IPL and HTTPD to come up, then check the mvsMF level
curl -u IBMUSER:SYS1 'http://localhost:8080/zosmf/test?fn=version'
```

mvsMF answers before TSO is up: on an idle 4-CPU host the authenticated
`fn=version` returned 200 about 2 s after `docker run`, and `IKT005I TCAS IS
INITIALIZED` followed about 1.5 s later. Wait for each separately.
`/zosmf/info` answers 401 without credentials, so a readiness probe has to
authenticate.

FTPD reports `FTPD001I READY` about 2 s after `docker run` and greets
right away. Stock MVS/CE has `DMN=1,CNSTR=(1,50,1)` in
`SYS1.PARMLIB(IEAIPS00)`, and with that minimum MPL of 1 the SRM keeps
swappable domain-1 started tasks (FTPD, `SETPFKEY`) swapped out for
about 30 s after the IPL: FTPD's first connection waited in the host's
listen backlog until then. The image raises the minimum to 10
(measured and pinned down by ftpd,
[ftpd#176](https://github.com/mvslovers/ftpd/issues/176)); CI checks
that FTPD greets within 10 s of mvsMF answering. Passive
mode answers with `127,0,0,1` (MVS/CE's `FTPDPRM0`), so data connections work
inside the container only.

### Disposable test instances: `mvsce-target`

`mvsce/mvsce-target` starts an instance of `mvsce` (MVS/CE, the default) or,
with `--dist tk5`, of `tk5`, waits until mvsMF answers and prints it as an
mbt 3 environment target; `down` removes it again, completely. What the
target says -- user, password, HLQ, the volume and classes for mbt, the
published ports -- comes from the image's `io.mvslovers.target.*` labels, so
each image carries its own; an `mvsce` image built before those labels gets
the MVS/CE values below. It runs the instance in one of two places, and
prints the same target either way:

| Where | How | Address and ports |
|-------|-----|-------------------|
| `--host SSH` (or `MVSCE_TARGET_HOST`) | Docker on that host; the script sends itself through `ssh HOST bash -s`, nothing is installed there | the address `ssh -G` resolves for the host, random host ports |
| locally, Docker present | Docker | `localhost`, random host ports |
| locally, no Docker (macOS) | Apple's `container`, the arm64 image natively; needs `python3` | the VM's own address (`192.168.64.x`), the native ports |

`MVSCE_TARGET_RUNTIME=docker|container` forces the local runtime.

```bash
eval "$(mvsce/mvsce-target up --host mvsdev)"   # or: up (locally); --dist tk5 for TK5
mbt target ping env --tso --wait 60     # TSO is up ~1.5 s after mvsMF
mbt test --mvs --target env
mvsce/mvsce-target down "$MVSCE_TARGET_NAME" --host mvsdev
```

| Command | Does |
|---------|------|
| `up [NAME] [--dist mvsce\|tk5] [--port N ...] [--wait SEC] [--pull always\|missing]` | start, wait for the authenticated `fn=version` (default 120 s), print the target; on failure print the log tail and remove the instance |
| `status NAME` | print the target of a running instance |
| `down NAME` | stop it and check that it is gone |
| `list` | instances on that host, with distribution, address, ports, age and owner |
| `reap [--older-than MIN]` | remove instances older than MIN minutes (default 240) |

The output is `export` lines by default, `.env` lines with `--env`, JSON
with `--json`:

| Variable | `mvsce` | `tk5` |
|----------|---------|-------|
| `MBT_TARGET_MVSMF_URL` | `http://<address>:<port of 8080>` | the same |
| `MBT_TARGET_MVSMF_USER` / `_PASSWORD` | `IBMUSER` / `SYS1` | `HERC01` / `CUL8TR` |
| `MBT_TARGET_HLQ` | `IBMUSER` | `HERC01` |
| `MBT_TARGET_VOLUME` | `WORK00` | `WORK01` |
| `MBT_TARGET_JOBCLASS` / `_MSGCLASS` | `A` / `H` (held, readable through mvsMF) | `A` / `H` (TK5 prints and purges class A at once) |
| `MBT_TARGET_TN3270_HOST` / `_PORT` / `_USER` / `_PASSWORD` | the TN3270 console, `IBMUSER` / `SYS1` | `HERC01` / `CUL8TR` |
| `MBT_TARGET_HERCULES_URL` / `_USER` / `_PASSWORD` | the Hercules web console, `hercules` / `hercules` | no login |
| `MVSCE_TARGET_NAME`, `_DIST`, `_RUNTIME`, `_IMAGE`, `_HERCULES_REF` | the instance, `mvsce` or `tk5`, `docker` or `container`, the image by digest, the Hercules commit | |
| `MVSCE_TARGET_FTP_PORT`, `_RDR_PORTS` | FTPD, and the ASCII/EBCDIC card readers | FTPD, the ASCII reader (TK5 has no EBCDIC one) |
| `MVSCE_TARGET_PORT_<N>` | for each `--port N`: where guest port N is reachable |

`--port N` (repeatable) makes another guest port reachable, for a server
the image does not run itself (e.g. one under test listening on 3305).
Under Docker it is published to a random host port, under Apple's
`container` it is N itself. Other instances reach it at the printed
address and port too: measured container to container on both runtimes
(Docker through the host's address and mapped port, Apple VM to VM).

At most six instances run per host under Docker and three under Apple's
`container` (`MVSCE_TARGET_MAX` overrides both). Under `container` each
idle instance costs about half a CPU core (measured below), which is
what the three is for; under Docker an instance took about 60 MB and
stayed far below a core on a 4-vCPU host, and its lowest CPU shares
leave the host's own work first. Each carries
the label `io.mvslovers.target=<name>` and leaves nothing behind (Docker:
`--rm` with its anonymous volumes; Apple's `container`: `--rm`, it creates
no volumes). `MVSCE_TARGET_IMAGE` selects any other image, e.g. `:dev`, and
overrides `--dist` (`MVSCE_TARGET_DIST`).

Under Apple's `container` each instance is a VM of its own, `512M` and 2
CPUs by default (`MVSCE_TARGET_MEMORY`, `MVSCE_TARGET_CPUS`). Measured on
an Apple M2 Pro Mac with 16 GB and 10 cores: `up` returns after about 6 s
(mvsMF answers 3 s after the start, at 1024M, 512M and 384M alike); at
512M the guest still reports about 500 MB available; four
instances started in parallel took 7–8 s and moved the host's free memory
from 19 % to 17 %, but each idle instance used about half a core (218 % of
one core for four), against 8–10 % per container under Docker on mvsdev.

Under Docker each instance runs with `--cpu-shares 2`, the lowest weight
(`MVSCE_TARGET_CPU_SHARES`), to lean a contended CPU towards other work
on the host. That buys less than the weight suggests: with systemd's
cgroup v2 the containers sit in `system.slice`, while processes started
from a login or tmux session sit in `user.slice`, and the two slices split
a contended host half and half whatever the containers' weight. Measured
on mvsdev (4 cores), three CPU-bound loops in a container against three
in a login session, 10 s each, two runs: at weight 1024 the container got
1.82 and 1.83 cores and the session 1.60 and 1.56; at weight 2 the
container got 1.39 and 1.62 and the session 1.94 and 1.80. So the low
weight moves 0.2 to 0.45 of a core towards the session; the bulk of the
protection is the slice split, which needs root to change.

### Inside the image

- BREXX from `SYS2.LINKLIB` needs a `REGION`: without one the fetch fails
  `IEA703I 106-0C` (`0C` is storage); `REGION=4M` works.
- `SYS2.LINKLIB` is APF-authorized (`IEAAPF00`: `SYS2.LINKLIB MVS000`),
  but a module still has to be link-edited `AC(1)` to run authorized.

`docker logs` carries the Hercules log and the console hardcopy
(`/logs/hercules.log`, `/logs/mvslog.txt`), preceded by the host CPU and
followed by `[*] Hercules ended: exit code …` once Hercules quits. A wait
loop should therefore also stop as soon as the container is no longer
running, rather than waiting out its timeout.

Unlike stock MVS/CE the image runs Hercules with **one CPU** (`NUMCPU 1`):
with two, the IPL occasionally stalled around the second CPU. Start the
container with `-e MVSCE_NUMCPU=2` to get two back.

**Shutdown.** `SYS2.JCLLIB(SHUTFAST)` (or `SHUTDOWN`, with 5 minutes of
warnings) shuts MVS down and ends the container: measured with the
servers running, 61 s from submitting SHUTFAST through mvsMF to the
container's exit. Stock MVS/CE's `SCRIPTS/SHUTDOWN.RC` did neither here:
it stops TSO and VTAM but not UFSD, HTTPD and FTPD, so JES2 never reached
`$HASP099` and the shutdown stopped after `HALT NET`; and its `poweroff` is
armed on a `SIGP Stop` only a second CPU produces. The image adds
`P FTPD` / `P HTTPD` / `P UFSD` (one console line per pause: of two lines
typed within a second, MVS acts on the second only) and a `poweroff` on the
wait state CCC. The build shuts down that way with the servers up, so it
fails if the shutdown does not stop them.

The `mvsce IPL sample` workflow (manual dispatch) starts the image
on a dozen runners and reports per start whether mvsMF came up, how
Hercules ended and on which CPU — the diagnostic for
[brexx370#277](https://github.com/mvslovers/brexx370/issues/277).

## tk5

**Image:** `ghcr.io/mvslovers/tk5` (public; `mvsce-target up --dist tk5` starts one)

[TK5](https://www.prince-webdesign.nl/tk5) — Rob Prins' MVS 3.8j turnkey
system — in its **minimal configuration**, with UFSD, HTTPD, mvsMF and FTPD
**installed with SMP** from their release packages: for what `mvsce` cannot
answer, TK5-specific behaviour and SMP installs. The container carries a
real SMP inventory of the released levels (`TUFS140`, `THTP430`, `TZMF130`,
`TFTP120`, `REC APP ACC` in both zones), on which an upgrade to a `-dev`
level, `DELETE` included, can be rehearsed.

| Component | Version | Where |
|-----------|---------|-------|
| [TK5](https://www.prince-webdesign.nl/tk5) | Update 5 (2026-02-18), minimal configuration | `/tk5`, as unpacked, without TK5's own Hercules builds and its PDF manuals |
| [Hercules](https://github.com/SDL-Hercules-390/hyperion) (SDL-Hyperion, `develop`) | `a742398074` (4.10.0.11783) | `/opt/hercules` |
| [UFSD](https://github.com/mvslovers/ufsd) | 1.4.0 (`TUFS140`) | `UFSD.LINKLIB` |
| [HTTPD](https://github.com/mvslovers/httpd) | 4.3.0 (`THTP430`) | `HTTPD.LINKLIB` |
| [mvsMF](https://github.com/mvslovers/mvsmf) | 1.3.0 (`TZMF130`) | `MVSMF.LINKLIB` |
| [FTPD](https://github.com/mvslovers/ftpd) | 1.2.0 (`TFTP120`) | `FTPD.LINKLIB` |

The values are `ARG`s in `tk5/Dockerfile`; a new TK5 update is `TK5_UPDATE`,
`TK5_URL` and `TK5_SHA256` (the download page publishes no checksum, so it
is pinned to the one this image was built from). TK5's own `conf/`,
`scripts/` and `dasd/` stay as shipped: the image sets only the variables TK5
itself reads (`CNSLPORT`, `HTTPPORT`, `RDRPORT`, `REP101A`, …) and IPLs the
way TK5's `mvs_ipl` does in daemon mode.

```bash
docker run -d --rm --name tk5 -p 2121:2121 -p 3270:3270 -p 8080:8080 \
  ghcr.io/mvslovers/tk5:dev
curl -u HERC01:CUL8TR 'http://localhost:8080/zosmf/test?fn=version'
```

**Minimal configuration.** `REP101A=specific`, `CMD101A=02` (TK5 manual,
"Start MVS with a minimal configuration"): IEA101A is answered with
`R 00,CMD=02`, so TCAM, MF1, JRP and SNASOL do not start and the NCPs are
not loaded. `-e REP101A=default` gives the full TK5 back, the servers
included.

**How the products are installed** (`tk5/setup_tk5.py`, at build time): each
product's own allocation and SMP install job from its release package, as its
README describes, with `USER=HERC01` on the job card (RAKF) and the
libraries on `TSO001`. An install counts only when every module the APPLY
reports as copied (`HMA2380`) is in the target library's member list. The
XMITs go in through the card reader, switched to EBCDIC for them (TK5's own
FTP server, FTPD 1.0.1, refuses every upload). TK5's HTTPD 3.3.0 library is
renamed to `HTTPD.V3R3M0.LINKLIB` first, as HTTPD 4 creates
`HTTPD.LINKLIB`.

**The configuration is TK5's way, not MVS/CE's:**

- Procedures `UFSD`, `UFSDCLNP`, `HTTPD` and `FTPD` in `SYS2.PROCLIB`
  (replacing TK5's HTTPD 3.3.0 and FTPD 1.0.1 ones), from the SAMPLIBs with
  `D='SYS1.PARMLIB'` (TK5 has no `SYS2.PARMLIB`), the spool DDs on `SPOOL0`,
  and `MVSMF.LINKLIB` ahead of `HTTPD.LINKLIB` in HTTPD's `STEPLIB`.
- `HTTPPRM0` and `FTPDPRM0` as shipped, and a `UFSDPRM0` of the image's own
  in `SYS1.PARMLIB`: `UFSD.ROOT` on `/`, `UFSD.SCRATCH` on `/tmp`,
  `HERC01.UFSHOME` on `/u/herc01`. No web root: HTTPD's
  `httpd-webroot.img` goes in by IND$FILE only, so `/` answers 404.
- RAKF: users `HTTPD` and `FTPD` in group `USER`, as both servers sign on
  (TK5 ships `FTPD` in group `FTPD` only). TK5's `FACILITY FTPAUTH` stays as
  shipped: FTP only for `ADMIN` (`HERC01`, `HERC02`, `IBMUSER`).
- No APF entries: on TK5 the servers authorise themselves through RAKF's
  SVC 244 (`HTTPD002I AUTHORIZED BY SVC`), as their READMEs describe, so no
  second IPL.
- Autostart from TK5's BSPPILOT startup scripts, `SYS1.PARMLIB(STARTMIN)`
  and `(STARTSTD)`, not `COMMND00`.

Ports as in `mvsce`: mvsMF/HTTPD 8080, FTPD 2121, TN3270 3270, ASCII card
reader 3505, Hercules web console 8888 (TK5's default is 8038). Users are
TK5's own: `HERC01`/`CUL8TR` (ADMIN, RAKFADM), `HERC02`/`CUL8TR`,
`HERC03`/`PASS4U`, `HERC04`/`PASS4U`, `IBMUSER`/`IBMPASS`.

**Start.** TK5 runs its start script `SYS1.PARMLIB(STARTMIN)` (NET, JES2's
devices, the servers) from a JES2 automatic command, `$TA,I=30` in
`SYS1.JES2PARM(STARTMIN)`, 30 s after JES2's start; JES2 takes no interval
below 30 (`I=1` and `I=10`: `$HASP000 … INVALID SPECIFICATION`). The image's
`HERCULES_RC`, `local_conf/ipl.rc`, sets one Hercules automatic operator rule
and then calls TK5's `scripts/ipl.rc` unchanged: on `BSPSETPF ENDED`
(BSPPILOT is up) it enters `F BSPPILOT,SCRIPT=STARTMIN`; the script's first
command, `$CA,ALL`, cancels the waiting automatic command, so it runs once.
With the servers that early TK5 showed MVS/CE's SRM hold (TK5's `IEAIPS00`
is MVS/CE's), so the image raises domain 1's minimum MPL to 10 here as well,
and `IPL_PAUSE=1` shortens the pauses in `scripts/ipl.rc`.

Measured on mvsdev (4 cores, idle, three starts): TSO 8 s after
`docker run`, mvsMF 10.3–10.6 s, FTP greeting 11.1–11.5 s; stock TK5 in its
minimal configuration took 44 s to TSO and 47 s to mvsMF.

**Shutdown.** `SYS2.JCLLIB(SHUTDOWN)` (TSO: `SHUTDOWN`) runs TK5's Hercules
`scripts/shutdown`: 30 s, then BSPPILOT's `SHUTNOW` script, `$PJES2`,
`Z EOD`, `QUIESCE` and `poweroff`, and the container ends. TK5's shutdown
scripts (`SYS1.PARMLIB(SDMIN*)`, `(SDSTD*)`) stop TSO and VTAM but not our
servers, which kept JES2 from `$HASP099`; the image adds `IF FTPD` /
`COM P FTPD` / `ENDIF` (and HTTPD, then UFSD) to all six. Measured with the
servers running: 100 s from submitting `SHUTDOWN` through mvsMF to the
container's exit. The build shuts down that way too.

**Traps** (found running OFTPD tests in this image):

- mvsMF puts the submitting user on the job card: a job with `USER=HERC02`
  submitted as `HERC01` runs as `HERC01`. To run as another user, submit as
  that user.
- `HERC02` is in group `ADMIN` like `HERC01`; the ordinary users are
  `HERC03` and `HERC04` (group `USER`).
- A started task's `SYSOUT=*` output is printed and purged at once (class
  A); only a held class such as `H` keeps it readable.
- BREXX is `BREXX.V2R5M3.RXLIB`. A REXX `/*` comment in column 1 ends an
  in-stream `DD *`; use `DD DATA,DLM=@@`.

## Build

`hercules`, `mvs-dev`, `mvsce` and `tk5` are built and published by GitHub
Actions (on changes under their respective directories); `mvsce` and `tk5`
go to `:dev` and are promoted to `:latest` by hand (`promote.yml`), `mvsce`
after the IPL sample.
`make` builds and tests locally:

```bash
# Build all images
make all

# Build individual images
make mvsce
make mvs-dev

# Push all images to ghcr.io
make publish

# Push individual images
make publish-mvsce
make publish-mvs-dev

# Smoke tests
make test-mvsce
make test-mvs-dev

# Cleanup
make clean
```

## Ports (mvsce)

| Port | Service |
|------|---------|
| 2121 | FTPD (control connection; passive data ports are not published) |
| 3270 | TN3270 (terminal access) |
| 3505 | JES2 ASCII socket reader |
| 3506 | JES2 EBCDIC card reader |
| 8080 | HTTPD + mvsMF REST API |
| 8888 | Hercules web console |

## Repository Structure

```text
mvs-docker/
├── hercules/          hercules image (SDL-Hyperion emulator, base image)
├── mvs-dev/           mvs-dev image (headless development container)
├── mvsce/             mvsce image (MVS/CE + UFSD + HTTPD + mvsMF + FTPD), mvsce-target
├── tk5/               tk5 image (TK5, minimal, + UFSD + HTTPD + mvsMF + FTPD via SMP)
├── common/            shared scripts and configs
├── .github/workflows/ CI: hercules, mvs-dev, mvsce (build, IPL sample, promote)
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
