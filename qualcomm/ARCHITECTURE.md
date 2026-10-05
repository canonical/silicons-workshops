# Qualcomm Silicon Workshop — Architecture

How the workshop is structured and how a command flows end to end. This mirrors
the renesas reference architecture so the two silicon workshops share one shape.

---

## The core idea: separate "WHAT" from "HOW"

- **WHAT to build** → declarative data in `config/workshop.yaml`
  (SoC, kernel repo, ref, flavour, kconfig fragments, quirks). No logic, just
  values. A future BSP agent edits this file and nothing else.
- **HOW it is built** → bash scripts under `sdk/`
  (clone, build the `.deb`, build the `.snap`, validate…).

The `.workshop/*.yaml` files are thin **dispatchers**: they only map a command
name to a script. They contain no build logic.

---

## Three layers

### Layer 1 — `config/workshop.yaml` (WHAT)

The single declarative file (see README §2). No credentials live here
(contract §14); private-repo auth comes from ssh-agent. The Qualcomm vendor
block (`kernel.config.fragments`, `kernel.config.disable`) is documented in
`DESIGN.md`.

### Layer 2 — `sdk/` (HOW)

```
sdk/
├── common/                       # shared by every SDK
│   ├── bin/clone-kernel          # the clone-kernel command
│   ├── workshop.sh               # config parsing, logging, toolchain, binfmt
│   └── source.sh                 # clone / require-source / apply-patches
│
├── deb/                          # Debian Packaging SDK
│   ├── bin/kernel-build-debs     # command entry point (orchestrator)
│   └── lib/
│       ├── package.sh            # clean + annotate + updateconfigs + dpkg-buildpackage
│       └── validate.sh           # verify the .debs (+ snapd kconfig)
│
└── snap/                         # Snap Packaging SDK
    ├── bin/kernel-build-snap
    ├── lib/
    │   ├── pack.sh               # stage debs → snapcraft (initrd plugin) → stage
    │   └── validate.sh           # verify the .snap (type: kernel + initrd.img)
    └── snapcraft/                # the deb → plugin:kernel recipe (contract §8)
        ├── snap/snapcraft.yaml
        └── build-inputs/         # staged debs + dtb (gitignored)
```

**`bin/` = command, `lib/` = logic.** Each `bin/` script is a short orchestrator;
the actual work lives in `lib/`. This is the SDK shape the contract (and the
renesas reference) expects.

### Layer 3 — `.workshop/` (workshop definition + host provisioning)

```
.workshop/
├── qcom-noble.yaml         # WORKSHOP definition (24.04): SDKs + action→script map
├── deb-sdk/sdk.yaml        # functional SDK declaration (thin)
├── snap-sdk/sdk.yaml       # functional SDK declaration (thin)
└── noble-build/            # build-host PROVISIONING SDK (hooks only)
    ├── sdk.yaml
    └── hooks/{setup-base, setup-project, check-health}
```

Two SDK kinds:

- **Functional SDKs** (`deb-sdk`, `snap-sdk`): the contract's "real work" SDKs.
  Their `.workshop/*/sdk.yaml` is intentionally thin — the actual scripts live
  under `sdk/deb/`, `sdk/snap/`.
- **Build-host provisioning SDK** (`noble-build`): hooks only. Installs the
  cross-toolchain, kernel/packaging deps, initrd/qemu tooling and snapcraft;
  registers the arm64 foreign architecture; health-checks the result.

---

## What each hook does (provisioning)

Run automatically by `workshop launch` / `workshop refresh`:

- **`setup-base`** (root): adds the arm64 foreign architecture + ports apt
  source; installs the arm64 cross-toolchain, Clang/LLVM, dtc, kernel
  build-deps, Debian/Ubuntu packaging tools (incl. `dwarfdump`), initrd deps
  (`dracut-core`), qemu (system+user), squashfs-tools, sparse, and snapcraft
  (latest/edge, for the initrd plugin).
- **`setup-project`** (workshop user): adds git host keys so clones don't
  prompt; maps the Launchpad SSH login for private repos. No credentials read
  from config.
- **`check-health`**: fails the launch early if the deb-SDK toolchain is
  missing; warns (does not fail) on missing snap-only tooling.

---

## How a command flows (end to end)

`workshop run qcom-noble -- kernel-build-debs`:

```
workshop tool
  → reads qcom-noble.yaml, finds action "kernel-build-debs"
  → runs:  bash sdk/deb/bin/kernel-build-debs
        → sources sdk/common/workshop.sh   (config parsing, helpers)
        → sources sdk/deb/lib/package.sh    (build logic)
        → workshop_read_config              (read config/workshop.yaml → CFG_*)
        → workshop_validate_config
        → workshop_resolve_toolchain
        → workshop_require_source           (kernel-src must exist; else fail)
        → deb_build   (mrproper → clean → drop zfs → annotate → updateconfigs → dpkg-buildpackage)
        → deb_stage   (move .debs → out/deb/)
        → deb_validate(arch + linux-image + snapd kconfig)
```

`clone-kernel` is a **separate** command: it clones/checks-out `kernel-src/`
from the config. Build commands never clone or fetch — clone once, rebuild many.

The snap flow is the same shape: `snap_build` stages the `out/deb` debs (+ dtb)
into `sdk/snap/snapcraft/build-inputs/`, runs snapcraft's `initrd` plugin, then
`snap_stage` + `snap_validate`.

---

## Runtime directories (host-visible, gitignored)

```
kernel-src/     cloned kernel source        (clone-kernel)
out/deb/        built .deb packages         (kernel-build-debs)
out/snap/       built kernel snap           (kernel-build-snap)
```
