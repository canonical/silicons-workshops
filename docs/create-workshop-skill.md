# create-workshop skill — Specification

## Purpose

An agent skill that guides a coding agent or contributor to instantiate a new
conformant Silicon Workshop from the template bundled with the skill
(`assets/workshop-template/`), given BSP analysis
inputs, without requiring knowledge of the internal workshop structure.

The skill is self-contained: it ships its own workshop template
(`assets/workshop-template/`), lookup script (`scripts/c3_lookup.py`) and vendor
table (`references/kernel-sources.json`). It is installed with
`npx skills add canonical/silicons-workshops --skill create-workshop`.

The default workshop targets an EVK certified in the Canonical Certification (C3)
database, on the Ubuntu release and kernel it was certified on. Kernel sources are
checked live against Launchpad before any file is written. The user may choose another
release that has a kernel source (a customization, flagged as such) or supply their own
kernel repository and ref.

## Inputs

| Field | Description | Example |
|-------|-------------|---------|
| `vendor` | Silicon vendor identifier (lowercase) | `mediatek`, `qualcomm`, `renesas` |
| `soc` | SoC family identifier | `genio-510`, `sa8775p`, `rzt2h` |
| `evk_board` | Reference EVK board name | `genio-510-evk`, `iq-9075-evk` |
| `ubuntu_release` | Ubuntu series | `jammy`, `noble`, `resolute` |
| `kernel_repo` | Kernel git repository URL | `https://git.launchpad.net/~canonical-kernel/...` |
| `kernel_ref_type` | `tag`, or `commit` when the repository has no release tags | `tag` |
| `kernel_ref` | Kernel release tag or commit SHA | `Ubuntu-mtk-5.15.0-1038.45` |
| `kernel_flavour` | Kernel config flavour name | `mtk`, `qcom`, `renesas` |
| `toolchain_arch` | Target architecture | `arm64`, `armhf` |

## Behaviour

1. **Step A — Vendor**: offers vendors that have certified EVKs in C3 and at least
   one buildable kernel source (`c3_lookup.py vendors`).

2. **Step B — EVK**: offers the vendor's certified EVKs with the kernel C3 certified
   them on (`c3_lookup.py evks`).

3. **Step C — Ubuntu release**: offers every series with a buildable kernel source,
   the certified one first and marked `(certified)` (`c3_lookup.py series`). Other
   series are customizations and are flagged. The kernel ref is the highest respin of
   the certified kernel's tag, else the latest release tag, else the branch-tip commit
   for repositories that publish no tags.

4. **Step D — Confirmation**: derives all remaining values automatically (`core_base`,
   flavour, snap name) and presents a summary for approval.

5. **Generation** (`scripts/instantiate.py`, deterministic): copies the bundled
   `assets/workshop-template/`, substitutes all `<placeholder>` tokens, keeps the
   toolchain block for the series, renders `sdk/snap/snapcraft/snapcraft.yaml`
   (`build-base`, `architectures` or `platforms` by Ubuntu Core base, kernel source
   path), runs `scripts/check_workshop.py`, and registers the new workshop in
   `catalog.yaml`. If the generated workshop fails its own checks nothing is kept.

6. **Build and repair** (`scripts/run_stages.py`, optional): runs the stages
   `check`, `launch`, `clone`, `deps`, `deb`, `snap` in order and stops at the first
   failure with a verdict (`continue`, `fix-available`, `diagnose`, `wait`, `stop`).
   Known tooling failures are repaired from `references/known-fixes.json`; unknown
   ones are diagnosed by the agent. The budget is 5 repair iterations. Repairs may
   change only `.workshop/`, `sdk/` and `.gitignore`; the kernel tree, patches,
   the kernel ref and `config/workshop.yaml` are never changed. Environment failures,
   kernel or patch errors, the same failure twice, and an exhausted budget stop the
   run. Every attempt is written to `REPAIR-LOG.md`.

7. **Report**: `HANDOFF.md` with the outcome per target, the kernel built against the
   kernel C3 certified, artifacts with checksums, repairs, and what is not proven.

## Requirements

- The skill SHALL produce a complete workshop directory with **no remaining
  `<placeholder>` tokens** in any file after generation.
- The skill SHALL generate `sdk/snap/snapcraft/snapcraft.yaml` using
  `plugin: kernel` with `kernel-ubuntu-debian-package: true`.
- The skill SHALL add a new entry to `catalog.yaml` with `vendor`, `soc`,
  `evk`, `path`, and `ubuntu_releases` populated.
- The skill SHALL reject `kernel.repository` values containing embedded
  credentials (username:token patterns). `git+ssh://` URLs are permitted.
- The skill SHALL pin the kernel to a release tag, or to a commit SHA when the
  repository publishes no release tags. It SHALL NOT pin a moving branch.
- The skill SHALL NOT answer "no releases" or "not supported" from a lookup that
  failed (network, timeout, private repository); it SHALL report the failure.
- The skill SHALL tell the user when a chosen release or kernel was not certified
  in C3, and when no kernel build has been validated for the chosen vendor and series.
  Validation is tracked separately for the `.deb` build and the snap build.
- The skill SHALL NOT modify `kernel-src/`, patches, `config/workshop.yaml`, or the
  kernel ref in order to make a build pass, and SHALL enforce that mechanically.
- The skill SHALL make at most 5 repair iterations per workshop, and SHALL stop on a
  repeated failure, an environment failure, or a failure inside the kernel tree.
- A generated workshop SHALL pass `scripts/check_workshop.py` before it is reported.

## Toolchain notes

| Ubuntu series | profile | installs |
|---------------|---------|----------|
| resolute (26.04) | `clang21` | `clang-21`, `llvm-21-dev`, `bindgen`, native `rustc` 1.93 |
| noble (24.04) | `clang18` | `clang-18`, `bindgen-0.65`, native `rustc` 1.75, `rust-src` |
| jammy (22.04), focal (20.04) | `none` | `dwarfdump` only (5.15 and 5.4 kernels have no Rust) |

> **Note:** The `deps` stage compares the cloned kernel's `debian/control`
> `Build-Depends` with the build host and repairs gaps, so a profile is a default,
> not an assumption. See `references/toolchain-notes.md`.

## Tests

`python3 -m unittest discover -s workshop-catalog/tests` runs the offline tests
(generation for every series, the defects found in the Xilinx ZCU104 report, the
repair loop with a stub `workshop` CLI, and the shallow-clone script).
