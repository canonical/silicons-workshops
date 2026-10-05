# Qualcomm Silicon Workshop

A reproducible build environment for the **Qualcomm Ubuntu Kernel** for
reference EVKs. The reference board is the **Rubik Pi 3 (QCS6490)**. It
produces:

- **Ubuntu kernel Debian packages** (`.deb`) — for Ubuntu Classic
- **Ubuntu Core kernel snap** (`.snap`, with an initrd) — for Ubuntu Core

The kernel `.deb` is built directly from the configured kernel source via the
tree's native `debian/rules` packaging. The kernel `.snap` is built the
contract's **deb → plugin:kernel** way: it reuses the `.deb` output and
assembles an Ubuntu Core initrd with snapcraft's `initrd` plugin (no recompile).
What gets built is controlled declaratively in `config/workshop.yaml`; how it is
built lives in the SDKs under `sdk/`.

> **New to this layout?** Read [`ARCHITECTURE.md`](ARCHITECTURE.md) first, then
> [`DESIGN.md`](DESIGN.md) for how (and why) this workshop diverges from the
> renesas reference.

---

## 1. Prerequisites

- The **`workshop`** tool (Canonical craft-family orchestration).
- Network access to the configured kernel repository. The checked-in default is
  a **public** GitHub repo (`https://`, no auth needed).
- Only if a repo is **private** (`git+ssh://…`): load your key into ssh-agent
  and connect the ssh-agent plug (see §3); for private Launchpad also set
  `identity.launchpad_user` in `config/workshop.yaml`.

The build host (arm64 cross-toolchain, kernel build-deps, packaging tools, qemu
binfmt, snapcraft) is provisioned automatically by the workshop's setup hooks —
you do not install those yourself.

---

## 2. Configure what to build

`config/workshop.yaml` is the single declarative configuration. The checked-in
defaults describe the reference Rubik Pi 3 (QCS6490) and work as-is:

```yaml
schema_version: 1
silicon:
  vendor: qualcomm
  soc: qcs6490
  board: rubikpi3
ubuntu:
  release: noble        # 24.04
  core_base: core24
kernel:
  repository: https://github.com/rubikpi-ai/linux-debian.git
  ref:    { type: commit, value: 0f0155ba6d60 }
  config:
    type: flavour
    value: rubikpi
    fragments:                       # merged via annotations --update
      - config/canonical-snapd.config
      - config/customer.config
    disable: [CORESIGHT_DUMMY, CORESIGHT_TPDM]
  device_trees: [qcs6490-thundercomm-rubikpi3]
toolchain:
  arch: arm64
```

The `fragments` and `disable` keys are the **Qualcomm vendor
block** (contract §4 extension) — see [`DESIGN.md`](DESIGN.md).

---

## 3. Launch the workshop

```
workshop launch qcom-noble
```

The first launch runs provisioning (`setup-base`, `setup-project`,
`check-health`) — installs the toolchain/build-deps and may take several
minutes.

### 3b. Snap prerequisite (only for `kernel-build-snap`)

snapcraft is a classic snap, so it needs `snapd` + container nesting — a
workshop/LXD-level setting a hook can't apply from inside. `setup-base` installs
snapcraft if `snapd` is present; if the snap build later reports snapcraft
missing, do this once per fresh workshop:

```
C=$(lxc list --all-projects -c n --format csv | grep qcom-noble)   # container
lxc config set "$C" security.nesting=true
lxc restart "$C"
lxc exec "$C" -- bash -c '
  apt-get install -y snapd
  systemctl enable --now snapd.socket snapd.service; sleep 8
  snap install snapcraft --classic --channel=latest/edge'   # stable lacks the initrd plugin
```

Only if you use a **private** repo, connect ssh-agent:

```
workshop connect qcom-noble/deb-sdk:ssh-agent
```

---

## 4. Commands

Run with `workshop run qcom-noble -- <command>`. **Clone once, then build
repeatedly** — the build commands never clone or fetch.

| Command | Does | Output |
|---------|------|--------|
| `clone-kernel` | Clone/checkout the configured kernel repo | `kernel-src/` |
| `kernel-build-debs` | Ubuntu kernel `.deb`s from `kernel-src/` (native `debian/rules`) | `out/deb/` |
| `kernel-build-snap` | Ubuntu Core kernel `.snap` reusing `out/deb/` (initrd plugin) | `out/snap/` |

### Examples

```
# 1) Clone the kernel source once (reads repo/ref from config/workshop.yaml)
workshop run qcom-noble -- clone-kernel

# 2) Build the Debian packages (reuses kernel-src, no re-clone)
workshop run qcom-noble -- kernel-build-debs

# 3) Build the kernel snap (reuses out/deb; run --uid 0 for the initrd chroot)
workshop run qcom-noble --uid 0 -- kernel-build-snap

# Keep your laptop usable: cap parallelism
WORKSHOP_JOBS=6 workshop run qcom-noble -- kernel-build-debs
```

Every command supports `--help`.

> **Why `--uid 0` for the snap:** the initrd plugin does a real `mount`/`chroot`,
> which needs root. The command registers the arm64 binfmt handler itself.

---

## 5. Outputs

```
out/
├── deb/
│   ├── *.deb
│   └── metadata/          # .changes, .buildinfo, packages.txt
└── snap/
    ├── *.snap             # type: kernel, arm64, WITH initrd.img
    └── metadata/          # snaps.txt
```

A command reports success **only after its output is validated**: the `.deb` is
arch-correct with a `linux-image` containing a kernel (and the snapd baseline
kconfig is checked in `/boot/config`); the `.snap` is `type: kernel` and
contains `initrd.img`. On failure the command exits non-zero.

---

## 6. Environment overrides

| Variable | Applies to | Effect |
|----------|-----------|--------|
| `WORKSHOP_ARCH` | both | Override `toolchain.arch`. |
| `WORKSHOP_BOARD` | both | Override `silicon.soc`. |
| `WORKSHOP_JOBS` | both | Build parallelism (default: half the cores). |
| `SKIP_CLEAN=1` | debs | Skip the initial `mrproper` + `debian/rules clean`. |
| `SKIP_CHOWN=1` | debs | Skip the pre-build ownership reset. |
| `SKIP_BUILD_DEPS=1` | debs | Skip `apt-get build-dep`. |
| `BUILDPACKAGE_OPTS` | debs | Extra flags for `dpkg-buildpackage`. |
| `SNAPCRAFT_OPTS` | snap | Extra flags for `snapcraft pack`. |

---

## 7. Adding another Qualcomm board

Qualcomm silicon is board-agnostic to this workshop: only `config/workshop.yaml`
changes. Point `kernel.repository`/`ref` at the board's tree, set the flavour,
DTB(s), and any `disable` quirks, then run the §4 commands. No
SDK or workshop changes are needed.

---

## 8. Project layout

```
qualcomm/
├── config/
│   ├── workshop.yaml         # declarative "what to build" (the only config)
│   ├── canonical-snapd.config# Ubuntu Core (snapd) kconfig fragment
│   └── customer.config       # customer kconfig delta
├── sdk/
│   ├── common/               # shared helpers + clone-kernel
│   ├── deb/                  # Debian Packaging SDK  → kernel-build-debs
│   └── snap/                 # Snap Packaging SDK    → kernel-build-snap
│       └── snapcraft/        # the deb → initrd-plugin recipe
├── .workshop/                # workshop + SDK definitions and setup hooks
├── ARCHITECTURE.md           # how the pieces fit together (start here)
├── DESIGN.md                 # contract divergences + rationale
└── README.md                 # this file
```
