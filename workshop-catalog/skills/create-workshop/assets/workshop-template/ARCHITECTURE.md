# Silicon Workshop — Architecture (Template)

How the workshop is structured and how a command flows end to end.
This file documents the template structure. The same architecture applies
to all workshops instantiated from this template.

> **Snap SDK divergence vs Renesas reference:** This template uses
> `sdk/snap/snapcraft/snapcraft.yaml` (Snapcraft Kernel plugin,
> `kernel-ubuntu-debian-package: true`). The Renesas reference workshop
> () uses a different path: it builds the snap against a
> `snapcraft.yaml` embedded in the kernel source tree. New workshops MUST
> use this template’s plugin-owned path. See § Snap SDK Design below.

---

## The core idea: separate "WHAT" from "HOW"

The whole structure follows one principle:

- **WHAT to build** → declarative data in `config/workshop.yaml`
  (SoC, kernel repo, branch, arch, flavour…). No logic, just values. A future
  BSP agent edits this file and nothing else.
- **HOW it is built** → bash scripts under `sdk/`
  (clone, build the `.deb`, build the `.snap`, validate…).

The `.workshop/*.yaml` files are thin **dispatchers**: they only map a command
name to a script. They contain no build logic.

---

## Before vs now

### Earlier (original workshop)

```
.workshop/
├── <vendor>-noble.yaml          # ALL build logic inline in actions:
│                               #   (clone, configure, build-deb, build-snap, gadget)
├── <vendor>-resolute.yaml       # ~90% copy of the above
├── <vendor>-noble-build/        # setup scripts for noble
│   └── hooks/
└── <vendor>-resolute-build/     # setup scripts for resolute
    └── hooks/
config/board.env                # identity + secrets
```

Everything lived inside the two YAMLs' `actions:` blocks; the two variants were
near-duplicates; credentials sat in `board.env`.

### Now

```
config/workshop.yaml            # WHAT (single declarative config)
sdk/                            # HOW (shared bash scripts)
.workshop/                      # workshop definitions (dispatch) + host setup
```

The build logic moved out of YAML into `sdk/`; the two variants now share all
build code; `board.env` is gone (auth is via ssh-agent only).

---

## Three layers

### Layer 1 — `config/workshop.yaml` (WHAT)

The single declarative file. Example:

```yaml
silicon: { soc: <soc>, board: <soc>-evk }
ubuntu:  { release: resolute, core_base: core26 }
kernel:
  repository: https://git.launchpad.net/~canonical-kernel/ubuntu/+source/linux-<vendor>/+git/resolute
  ref:    { type: branch, value: main-next }
  config: { type: flavour, value: <vendor> }
toolchain: { arch: arm64 }
```

No credentials here (contract §14). Private-repo auth comes from ssh-agent.

### Layer 2 — `sdk/` (HOW)

The real work. Three directories:

```
sdk/
├── common/                       # shared by every SDK
│   ├── bin/clone-kernel          # the clone-kernel command
│   ├── workshop.sh               # config parsing, logging, toolchain resolution
│   └── source.sh                 # clone / require-source / apply-patches
│
├── deb/                          # Debian Packaging SDK
│   ├── bin/kernel-build-debs     # command entry point (orchestrator)
│   └── lib/
│       ├── package.sh            # clean + build-dep + dpkg-buildpackage + stage
│       └── validate.sh           # verify the .debs
│
└── snap/                         # Snap Packaging SDK
    ├── bin/kernel-build-snap
    └── lib/
        ├── pack.sh               # snapcraft pack + stage
        └── validate.sh           # verify the .snap
```

**`bin/` = command, `lib/` = logic.** Each `bin/` script is a short
orchestrator; the actual work lives in `lib/`. This is the SDK shape the
contract (and the qcom reference) expects.

`tools/gadget-build` is deliberately **outside `sdk/`** — the gadget is out of
contract scope, so it is kept separate to keep the SDK boundary clean.

### Layer 3 — `.workshop/` (workshop definitions + host provisioning)

Two different kinds of file live here — keep them distinct:

```
.workshop/
├── <vendor>-noble.yaml      # WORKSHOP definition (24.04): which SDKs + action→script map
├── <vendor>-resolute.yaml   # WORKSHOP definition (26.04)
│
├── deb-sdk/sdk.yaml        # functional SDK declaration (thin)
├── snap-sdk/sdk.yaml       # functional SDK declaration (thin)
│
├── noble-build/            # build-host PROVISIONING SDK (24.04)
│   ├── sdk.yaml
│   └── hooks/{setup-base, setup-project, check-health}
└── resolute-build/         # build-host provisioning SDK (26.04)
    ├── sdk.yaml
    └── hooks/
```

Two SDK kinds:

- **Functional SDKs** (`deb-sdk`, `snap-sdk`): the contract's "real work" SDKs.
  Their `.workshop/*/sdk.yaml` is intentionally thin (just "this SDK exists,
  may need ssh-agent") — the actual scripts are under `sdk/deb/`, `sdk/snap/`.
- **Build-host provisioning SDKs** (`noble-build`, `resolute-build`): the
  equivalent of your old `<vendor>-*-build/`. They contain only **hooks** that
  prepare the container (install snapcraft, cross-toolchains, rust, fix apt
  sources, register qemu binfmt). They are not functional; they only set up the
  environment.

Why the provisioning SDK is per-variant: noble and resolute have different
Ubuntu bases → different setup (snapcraft stable vs edge, different apt source
handling). But the **functional SDKs and all build scripts under `sdk/` are
shared** by both variants — no duplication.

---

## What each hook does (provisioning)

Run automatically by `workshop launch` / `workshop refresh`:

- **`setup-base`** (runs as root): installs snapcraft, cross-toolchains
  (arm64/armhf), kernel build-deps, rust (`rustc`/`rust-src`/`cargo`),
  `bindgen`/`rustfmt`/`xmlto`, `libdw-dev`, qemu-user; fixes apt sources so
  arm64/armhf come from `ports.ubuntu.com` and amd64 from `archive.ubuntu.com`.
- **`setup-project`** (runs as the workshop user): adds git host keys so clones
  don't prompt; optionally imports a local GPG key. No credentials read from
  config.
- **`check-health`**: verifies the toolchain/snapcraft are present and correct;
  fails the launch early if something is missing.

---

## How a command flows (end to end)

`workshop run -- kernel-build-debs`:

```
workshop tool
  → reads <vendor>-resolute.yaml, finds action "kernel-build-debs"
  → runs:  bash sdk/deb/bin/kernel-build-debs
        → sources sdk/common/workshop.sh   (config parsing, helpers)
        → sources sdk/deb/lib/package.sh    (build logic)
        → workshop_read_config              (read config/workshop.yaml)
        → workshop_validate_config
        → workshop_resolve_toolchain
        → workshop_require_source           (kernel-src must exist; else fail)
        → deb_build                         (clean → build-dep → dpkg-buildpackage)
        → deb_stage                         (move .debs → out/deb/)
        → deb_validate                      (arch + linux-image sanity)
```

`clone-kernel` is a **separate** command (`sdk/common/bin/clone-kernel`): it
clones/checks-out `kernel-src/` from the config. Build commands never clone or
fetch — clone once, rebuild many times.

---

## Runtime directories (host-visible, gitignored)

```
kernel-src/     cloned kernel source        (clone-kernel)
gadget-src/     cloned gadget source        (clone-gadget)
out/deb/        built .deb packages         (kernel-build-debs)
out/snap/       built kernel snap           (kernel-build-snap)
out/gadget/     built gadget snap           (gadget-build)
```

These are plain project directories (not workshop mounts), so you can inspect
outputs directly on the host.

---

## Old vs new — quick comparison

| | Original workshop | Now |
|---|---|---|
| Build logic | Inline in YAML `actions:` | Bash scripts under `sdk/` |
| YAML role | Everything | Dispatcher (calls a script) |
| Config | `board.env` + scattered in YAML | Single `config/workshop.yaml` |
| Identity / secrets | `board.env` | None (ssh-agent) |
| Commands | 8 (clone/configure/build-deb/build-snap/gadget…) | 3 functional (`clone-kernel`, `kernel-build-debs`, `kernel-build-snap`) + 2 gadget |
| Duplication | noble/resolute YAMLs ~90% copy | `sdk/` shared; only host-setup is per-variant |
| SDK concept | none (one host-setup SDK) | 2 functional SDKs (deb, snap) + host-setup |

Philosophy in one line: **"what" (config) and "how" (sdk scripts) are
separated, YAML is a thin bridge, and common code is shared.** This matches the
project's contract and the qcom reference.
