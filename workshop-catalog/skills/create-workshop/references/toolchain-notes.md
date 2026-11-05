# Toolchain Notes

The build host's compiler and Rust packages come from a **toolchain profile**,
not from one hand-edited hook. `scripts/instantiate.py` keeps one
`# >>> toolchain:<name>` block in `.workshop/<series>-build/hooks/setup-base`
(`TOOLCHAIN_PACKAGES`) and in `check-health` (`TOOLCHAIN_TOOLS`).

**Always read the kernel tree's `debian/control` `Build-Depends` before trusting
a profile.** The `deps` stage of `scripts/run_stages.py` does this after
`clone-kernel` and reports any `clang`, `llvm`, `bindgen`, `rustc`, `rust-src`,
`rustfmt` or `dwarfdump` the kernel names but the build host does not install.

## Contents

- Profiles
- Evidence by kernel
- Profile details
- Extra packages
- Private Launchpad repos and SSH
- check-config false positives
- Ubuntu release matching

## Profiles

| Profile | Default for | Installs |
|---------|-------------|----------|
| `none` | focal, jammy | `dwarfdump` only |
| `clang18` | noble | `clang-18`, `bindgen-0.65`, `rustc`, `rust-src`, `rustfmt` (Noble archive) |
| `clang21` | resolute; noble when the row says `"toolchain": "clang21"` | `clang-21`, `llvm-21-dev`, `bindgen`, `rustc`, `rust-src`, `rustfmt`; adds the apt.llvm.org repo when the archive lacks `clang-21` |

A row in `references/kernel-sources.json` can override the series default with
`"toolchain"`. For a custom target, `instantiate.py --toolchain` does the same.

## Evidence by kernel

Measured from cloned trees, not assumed:

| Kernel | Series | `rust/` in tree | Toolchain in Build-Depends |
|--------|--------|-----------------|----------------------------|
| linux-mtk 5.15.0-1041 | jammy | no | `dwarfdump` only |
| linux-xilinx-zynqmp 5.15.0-1082 | jammy | no | none (`pahole`/`dwarves` only) |
| linux-mtk 6.8.0-1006 | noble | yes | `clang-18`, `bindgen-0.65`, `rustc`, `rust-src`, `rustfmt` |
| linux-qcom 6.8.0-1080 | noble | yes | `clang-18`, `bindgen-0.65`, `rustc`, `rust-src`, `rustfmt` |
| linux-renesas 7.0 (`main-next`) | resolute | yes | `clang-21`, `llvm-21-dev`, `bindgen`, `rustc >= 1.82`, `rust-src`, `rustfmt` |

Not measured: focal (5.4) kernels, linux-xilinx 6.8 (noble), linux-nvidia-tegra,
linux-raspi. Treat their profiles as defaults until the `deps` stage has looked
at a clone. Focal is the least validated: no workshop has been built for it.

## Profile details

### none (focal, jammy)

5.4 and 5.15 kernels have no Rust and need no clang. Installing `clang-21` and
`rustc-1.91` for them (as an earlier template did) is unnecessary and adds an
external apt repository to every launch.

`dwarfdump` is **separate from `dwarves`** and the jammy 5.15 build fails
without it:

```text
/bin/sh: dwarfdump: not found
```

### clang18 (noble 6.8)

`clang-18`, `bindgen-0.65` and the default Noble `rustc` (1.75) are all in the
archive. `rust-src` is required: without it `make rustavailable` fails with
"core standard library not found". The `check-health` hook checks for
`bindgen-0.65`, not `bindgen`; the wrong name aborts the workshop refresh.

### clang21 (resolute, some noble trees)

Needs `clang-21` and `rustc >= 1.82`. Resolute ships `rustc` 1.93 natively. On
Noble `clang-21` is not in the archive, so the hook adds `apt.llvm.org` and uses
the versioned `rustc-1.91`/`rust-1.91-src` packages, registered as the default
`rustc` with `update-alternatives` (the kernel Makefile uses unversioned
`rustc`). The hook decides at run time from the candidate version of `rustc`.

## Extra packages

Kernel- or vendor-specific packages go in the `EXTRA_PACKAGES` list of
`setup-base`, between the `@EXTRA-PACKAGES` markers, one per line. The repair
step appends there. Examples seen: `arm-trusted-firmware-tools srecord
uuid-dev` for Renesas BSP tools.

## Private Launchpad repos and SSH

For `git+ssh://` repos, the workshop container's `~/.ssh/config` must have
`User <launchpad-id>` for `git.launchpad.net`. This is NOT forwarded from the
host's `~/.ssh/config` by the ssh-agent plug: only the agent socket is
forwarded. Add a `LAUNCHPAD_USER=<id>` entry to `config/board.env` (gitignored)
and make sure `setup-project` reads it. See the `mediatek-workshop` for the
pattern.

## check-config false positives

Some kernels have multi-flavour annotations where one flavour disables Rust
(for example `arm64-qcom-rt: '-'`) while another requires it (`arm64: 'y'`).
If `check-config` fails with `CONFIG_RUST_IS_AVAILABLE changed from y to -` on
the non-RT flavour, the annotation is wrong. That is a defect in the kernel
tree. **The repair step does not edit it**: it stops and reports it, and the
kernel team or the user decides. A known local workaround, for the user to apply
knowingly, is:

```bash
sed -i "s/'arm64-qcom-rt': '-'/'arm64-qcom-rt': 'y'/" \
  kernel-src/debian.qcom/config/annotations
```

## Ubuntu release matching

Use the workshop variant that matches `ubuntu.release` in `config/workshop.yaml`
(`workshop launch <vendor>-<series>`). The wrong variant (for example noble for
a resolute kernel) causes toolchain version failures that are hard to debug.
