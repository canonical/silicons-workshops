# Silicon Workshop — Template

> **This is the workshop-catalog template, not a working workshop.**
> To create a new Silicon Workshop for a specific silicon family, use the
> **create-workshop** skill (`.github/skills/create-workshop/SKILL.md`).
> It will copy this template, substitute all `<placeholder>` tokens, and
> register the new workshop in `catalog.yaml`.

---

A reproducible build environment for an Ubuntu kernel for a silicon reference
EVK. It produces:

- **Ubuntu kernel Debian packages** (`.deb`) — for Ubuntu Classic
- **Ubuntu Core kernel snap** (`.snap`) — for Ubuntu Core

What gets built is controlled declaratively in
`config/workshop.yaml`; how it is built lives in the SDKs under `sdk/`.

---

## 1. Prerequisites

- The **`workshop`** tool (Canonical craft-family orchestration).
- Network access to the configured kernel repository. The checked-in defaults
  use **public** Launchpad repos (`https://`, no auth needed).
- Only if a repo is **private** (`git+ssh://…`): load your key into ssh-agent
  (`ssh-add -l` to verify) and connect the ssh-agent plug (see §3). For a
  private Launchpad host that needs an explicit user, add it to your **own**
  `~/.ssh/config` outside the workshop — never to project config.

The build host (cross-toolchains, snapcraft, rust, qemu binfmt, kernel
build-deps) is provisioned automatically by the workshop's setup hooks — you do
not install those yourself.

---

## 2. Configure what to build

`config/workshop.yaml` is the single declarative configuration. The checked-in
defaults describe the reference <SoC> EVK and work as-is. Adjust if needed:

```yaml
silicon:
  soc: <soc>            # <soc>   board: <soc>-evk      # not needed
ubuntu:
  release: resolute     # must match the workshop variant you launch (see §3)
  core_base: core26     # core24 kernel:
  # Public https:// example (resolute). Noble:
  #   <kernel-repo-url>
  repository: <kernel-repo-url>
  ref:
    type: branch        # branch     value: main-next
  config:
    type: flavour
    value: <kernel-flavour>      # debian/scripts/misc/annotations --flavour
  device_trees: []      # empty = stage all produced DTBs
toolchain:
  arch: arm64           # arm64 (Cortex-A55)   cross_compile: ""     # empty = auto-derive from arch
```

---

## 3. Launch the workshop

Two base variants. **Launch the one matching `ubuntu.release`:**


```
workshop launch <vendor>-resolute
```

The first launch runs provisioning (`setup-base`, `setup-project`, health
check) — installs toolchains/build-deps and may take several minutes.

Only if you use a **private** repo, connect ssh-agent (plug lives on each SDK):

```
workshop connect <vendor>-resolute/deb-sdk:ssh-agent
```

---

## 4. Commands

Run with `workshop run <WORKSHOP> -- <command>`. **Clone once, then build
repeatedly.** Cloning is a separate step; the build commands never clone or
fetch — they use the already-cloned `kernel-src/` as-is.

> **Always name the workshop** (`<vendor>-resolute` or `<vendor>-noble`). Because
> this project defines two variants, omitting the name fails with
> *"cannot infer workshop name: multiple workshops found"*.
> The examples below use `<vendor>-resolute`; swap in `<vendor>-noble` if that is
> the variant you launched.


### Examples

```
# 1) Clone the kernel source once (reads repo/ref from config/workshop.yaml)
workshop run <vendor>-resolute -- clone-kernel

# 2) Build the Debian packages (reuses kernel-src, no re-clone)
workshop run <vendor>-resolute -- kernel-build-debs

# ...or the kernel snap (also reuses kernel-src)
workshop run <vendor>-resolute -- kernel-build-snap

# Build for armhf without editing config
WORKSHOP_ARCH=armhf workshop run <vendor>-resolute -- kernel-build-debs

# Refresh the source to the latest ref, then rebuild
workshop run <vendor>-resolute -- clone-kernel
workshop run <vendor>-resolute -- kernel-build-debs

```

Every command supports `--help`:

```
workshop run <vendor>-resolute -- kernel-build-debs --help
```

---

## 5. Outputs

```
out/
├── deb/
│   ├── *.deb
│   └── metadata/          # .changes, .buildinfo, packages.txt
├── snap/
│   ├── *.snap
│   └── metadata/          # snaps.txt
    └── *.snap
```

A command only reports success **after its output is validated**
(e.g. the `.deb` is structurally readable and arch-correct with a
`linux-image` containing a kernel; the `.snap` is `type: kernel` with kernel
content). If validation fails, the command exits non-zero.

---

## 6. Environment overrides

Set these inline before `workshop run`:


---

## 7. Rebuilding / cleaning

- **Build commands never clone or fetch.** They use the existing `kernel-src/`
  as-is, so you can rebuild repeatedly with no network access.
- To update the source to the latest of the configured ref (or after changing
  `kernel.ref` in `config/workshop.yaml`), re-run `clone-kernel` — it fetches
  and re-checks-out.
- To force a completely fresh clone, remove the tree first:
  ```
  rm -rf kernel-src
  workshop run <vendor>-resolute -- clone-kernel
  ```
  `build/`) are gitignored.

---

## 8. Troubleshooting


---

## 9. Project layout

```
renesas/
├── config/
│   └── workshop.yaml         # declarative "what to build" (the only config)
├── sdk/
│   ├── common/               # shared helpers + clone-kernel
│   │   ├── bin/clone-kernel
│   │   ├── workshop.sh       # config parse, logging, toolchain
│   │   └── source.sh         # clone / require source
│   ├── deb/                  # Debian Packaging SDK  → kernel-build-debs
│   └── snap/                 # Snap Packaging SDK    → kernel-build-snap
├── .workshop/                # workshop + SDK definitions and setup hooks
├── ARCHITECTURE.md           # how the pieces fit together (start here)
├── DESIGN.md                 # contract divergences + rationale
└── README.md                 # this file
```
---

## Template Placeholders

When instantiating this template with the create-workshop skill, the following
`<placeholder>` tokens are substituted:

| Placeholder           | config/workshop.yaml field      | Example value                          |
|-----------------------|---------------------------------|----------------------------------------|
| `<vendor>`            | `silicon.vendor`                | `mediatek`, `qualcomm`, `renesas`      |
| `<soc>`               | `silicon.soc`                   | `genio-1200`, `sa8775p`, `rzt2h`       |
| `<evk-board>`         | `silicon.board`                 | `genio-1200-evk`, `rzt2h-evk`           |
| `<ubuntu-release>`    | `ubuntu.release`                | `noble`, `resolute`                     |
| `<core-base>`         | `ubuntu.core_base`              | `core24`, `core26`                      |
| `<kernel-repo-url>`   | `kernel.repository`             | `https://git.launchpad.net/...`          |
| `<kernel-ref>`        | `kernel.ref.value`              | `main`, `main-next`, `Ubuntu-6.8.0-...` |
| `<kernel-flavour>`    | `kernel.config.value`           | `mtk`, `renesas`, `generic`            |
| `<toolchain-arch>`    | `toolchain.arch`                | `arm64`, `armhf`                        |
| `<Vendor>`            | Display name in descriptions    | `MediaTek`, `Qualcomm`, `Renesas`      |

The .workshop/ dispatch YAML files also use `<vendor>`, `<soc>`, `<evk-board>`,
and `<Vendor>` as placeholders in name, summary, and description fields.
