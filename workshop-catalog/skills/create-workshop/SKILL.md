---
name: create-workshop
description: >
  Create a new Silicon Workshop from the workshop-catalog template for a
  specific silicon family. Copies workshop-template/, substitutes all
  placeholder values, generates the Snapcraft Kernel plugin snapcraft.yaml,
  and registers the new workshop in catalog.yaml. Use when creating a new
  silicon workshop (e.g. for MediaTek, Qualcomm, NXP, or another vendor).
allowed-tools: Bash(*), EditFile(*), CreateFile(*), ReadFile(*)
license: MIT
---

# create-workshop — Silicon Workshop creation skill

## Purpose

Instantiate a new conformant Silicon Workshop from `workshop-template/` in the
`workshop_catalog`. The result is a ready-to-launch workshop directory with all
silicon-specific values substituted, a valid `snapcraft.yaml` using the
Snapcraft Kernel plugin, and an updated `catalog.yaml`.

---

## Guided Selection — Ask the user in sequence

Do NOT ask for all inputs at once. Follow the three-step guided flow below to
collect only what is valid. Reject requests for silicon that is not in the
supported catalog.

---

### Step A: Select silicon vendor

**ALWAYS fetch live data — never rely on a cached list.** The catalog changes
as new silicon is added.

**Before presenting the vendor list**, perform a full three-step validation
for every candidate vendor — do NOT show a vendor until all three conditions
are confirmed:

1. A `linux-<vendor>` source repository exists in `~canonical-kernel` on Launchpad
2. At least one Ubuntu series branch exists in that repository
3. At least one certified IoT device exists on `ubuntu.com/certified/iot?q=<vendor>`

Only vendors that pass **all three checks** appear in the Step A list. Never
present a vendor that will dead-end at Step B (no releases) or Step C (no
certified devices).

```
For each candidate vendor (renesas, qcom→qualcomm, mtk→mediatek, xilinx, etc.):
  Fetch: https://code.launchpad.net/~canonical-kernel/ubuntu/+source/linux-<pkg>/+git
         → confirms kernel exists and lists available series
  Fetch: https://ubuntu.com/certified/iot?q=<vendor-search-term>
         → confirms at least one certified device exists
  Include in Step A list only if BOTH fetches return results.
```

Present the cross-referenced list to the user. If the user requests a vendor
not in the list:
> "There is no public Canonical kernel for `<vendor>` in `~canonical-kernel`
> on Launchpad and/or no certified IoT device on ubuntu.com/certified/iot.
> A workshop can only be created for silicon with both. Currently supported:
> [list from live fetch]"

Stop — do not proceed.

---

### Step B: Select Ubuntu release

**Fetch live** from Launchpad the list of series (git branches) available for
the selected vendor's kernel package:

```
Fetch: https://code.launchpad.net/~canonical-kernel/ubuntu/+source/linux-<pkg>/+git
       (list all branch URLs — each branch name IS the series, e.g. noble, jammy, resolute)
```

Present only the series that have a kernel repository. Ask the user to select one.

---

### Step C: Select EVK (certified device)

**Fetch live** from the Ubuntu certified IoT catalog filtered by vendor:

```
Fetch: https://ubuntu.com/certified/iot?q=<vendor-name>
       (extract device names from the results table)
```

Present the list of certified EVK/board names and ask the user to select one.
Map the selected device name to a normalized `evk_board` identifier
(lowercase, hyphen-separated, e.g. `Genio 1200 EVK` → `genio-1200-evk`).

If the certified page does not list releases per device, use the series
selected in Step B to determine the EVK is valid for that release.

---

### Step D: Confirm and collect remaining inputs

After the three guided steps, confirm the selection with the user:

> "Creating a workshop for:
> - Vendor: **Qualcomm** (`linux-qcom`)
> - Release: **noble** (24.04, core24)
> - EVK: **Dragonwing IQ-9075 EVK** (`iq-9075-evk`)
>
> Is this correct? (yes/no)"

If confirmed, the remaining inputs are either known from the catalog below or
need to be resolved (kernel tag via Launchpad step 1b). Do not ask the user
for values that can be derived from the selection.

**Derived values from selection** (do not ask the user):

| Input | How to derive |
|-------|--------------|
| `vendor` | from Step A |
| `Vendor` | display name from Step A |
| `kernel_pkg_name` | from vendor table in Step A |
| `kernel_repo` | `https://git.launchpad.net/~canonical-kernel/ubuntu/+source/<pkg>/+git/<series>` |
| `kernel_flavour` | `renesas`, `qcom`, `mtk`, `xilinx` (matches `--flavour` in the kernel tree) |
| `toolchain_arch` | `arm64` (all currently supported EVKs) |
| `core_base` | `core22` for jammy, `core24` for noble, `core26` for resolute |
| `ubuntu_release` | from Step B |
| `evk_board` | from Step C |
| `soc` | derive from EVK name (e.g. `iq-9075-evk` → `qcs9075`) |
| `soc_families` | use the silicon family group (e.g. `qcs9075, sa8775p`) |
| `clang_version` | `18` for noble (Qualcomm/MediaTek/Xilinx), `21` for resolute (Renesas) |
| `kernel_ref` | resolve from Launchpad (step 1b) — latest release tag |

---

## Required Inputs

The following are now fully derived from the guided selection. They are listed
here for reference and override — the user should not normally need to provide
them manually.

| Input | Description | Example |
|-------|-------------|---------|
| `vendor` | Silicon vendor identifier (lowercase, kebab-safe) | `mediatek` |
| `Vendor` | Display name for the vendor | `MediaTek` |
| `soc` | SoC family identifier | `genio-1200` |
| `evk_board` | Reference EVK board name | `genio-1200-evk` |
| `ubuntu_release` | Ubuntu release name(s) (space-separated if multiple) | `noble` |
| `core_base` | Ubuntu Core snap base | `core24` (noble) or `core26` (resolute) |
| `kernel_repo` | Kernel source git URL | `https://git.launchpad.net/~canonical-hwe-private/ubuntu/+source/linux-mtk/+git/noble` |
| `kernel_ref` | Release tag for the kernel. **Always use a tag, never `main` or `master`.** The skill will look this up automatically from Launchpad if not provided. | `Ubuntu-qcom-6.8.0-1080.85` |
| `kernel_flavour` | Ubuntu kernel config flavour | `mtk` |
| `toolchain_arch` | Target architecture | `arm64` |
| `soc_families` | All SoC families this workshop supports (comma-separated) | `genio-700, genio-1200` |
| `kernel_pkg_name` | Kernel snap/deb package base name (from the Launchpad repo name, e.g. `linux-qcom` not `linux-qualcomm`) | `linux-qcom`, `linux-mtk`, `linux-renesas` |
| `clang_version` | clang version required by kernel Build-Depends | `21` (Renesas/resolute), `18` (Qualcomm/noble, MediaTek/noble, MediaTek/jammy) |
| `rust_src_pkg` | rust-src package name | `rust-src` (default), `rust-1.91-src` (if versioned) |

**Credential check:** If `kernel_repo` contains a `username:token@` or
`user:password@` pattern, reject it immediately with:
> Error: Credentials must never be embedded in the kernel repository URL.
> Use a git+ssh:// URL for private repositories. Authentication is supplied
> at runtime via ssh-agent.

A `git+ssh://` URL without embedded credentials is accepted.

---

## Steps

### 1. Determine workshop directory name

The new workshop directory is `<vendor>-workshop/` at the catalog root.
If a directory with that name already exists, append a qualifier:
`<vendor>-<soc>-workshop/`.

Announce: "Creating `<vendor>-workshop/` from `workshop-template/`."

### 1b. Resolve the kernel release tag from Launchpad

**Skip this step if the user provided an explicit `kernel_repo` URL and a
specific `kernel_ref` tag (e.g. `Ubuntu-qcom-6.8.0-1080.85`).** Only
resolve automatically when:
- `kernel_ref` was not provided, OR
- `kernel_ref` is a branch name (`main`, `master`, `main-next`, etc.)

If the user provided their own fork or a custom URL with a specific commit or
tag, use those values as-is and skip to step 2.

All Canonical Ubuntu kernel repositories follow this pattern:
```
https://code.launchpad.net/~canonical-kernel/ubuntu/+source/<pkg>/+git/<series>
```
For example:
- Qualcomm Noble: `https://code.launchpad.net/~canonical-kernel/ubuntu/+source/linux-qcom/+git/noble`
- MediaTek Noble: `https://code.launchpad.net/~canonical-kernel/ubuntu/+source/linux-mtk/+git/noble`
- Renesas Resolute: `https://code.launchpad.net/~canonical-kernel/ubuntu/+source/linux-renesas/+git/resolute`

**To find the latest release tag:**

Fetch the Launchpad page for the kernel repository and look for the most
recent tag starting with `Ubuntu-<flavour>-`. This is shown as the "Last
commit for master" description on the Launchpad git page.

```bash
# Example: fetch the Launchpad page and extract the latest tag
curl -s "https://code.launchpad.net/~canonical-kernel/ubuntu/+source/linux-<pkg>/+git/<series>" \
  | grep -o 'Ubuntu-[a-z]*-[0-9][^"]*' | head -1
```

Alternatively, use git to list tags directly:
```bash
git ls-remote --tags "https://git.launchpad.net/~canonical-kernel/ubuntu/+source/linux-<pkg>/+git/<series>" \
  | grep -o 'Ubuntu-[^}]*$' | sort -V | tail -1
```

Set `kernel_ref` to the resolved tag (e.g. `Ubuntu-qcom-6.8.0-1080.85`).
Set `kernel_ref_type` to `tag`.

**Why this matters:** Moving branches (`master`, `main`) can introduce new
kernel flavour variants, toolchain requirements, or `check-config` policy
failures at any time. A pinned release tag is always buildable and matches
a specific Ubuntu image release.

### 2. Copy the template

Copy `workshop-template/` to `<vendor>-workshop/` at the catalog root.
Do NOT copy `.git/` if present.

```bash
cp -r workshop-template/ <vendor>-workshop/
```

### 3. Substitute all `<placeholder>` tokens

In the following files, replace every `<placeholder>` token with the
corresponding input value. Use exact case as shown below.

**`config/workshop.yaml`**

| Placeholder         | Replace with              |
|---------------------|---------------------------|
| `<vendor>`          | `vendor` input            |
| `<soc>`             | `soc` input               |
| `<evk-board>`       | `evk_board` input         |
| `<ubuntu-release>`  | `ubuntu_release` input    |
| `<core-base>`       | `core_base` input         |
| `<kernel-repo-url>` | `kernel_repo` input                              |
| `<kernel-ref>`      | `kernel_ref` input (resolved tag from step 1b)   |
| `<kernel-flavour>`  | `kernel_flavour` input                           |
| `<series>`          | Ubuntu series from Step B (e.g. `jammy`, `noble`) |
| `<Series>`          | Capitalised series (e.g. `Jammy`, `Noble`)        |
| `<ubuntu-version>`  | Ubuntu version from Step B (e.g. `22.04`, `24.04`) |
| `<toolchain-arch>`  | `toolchain_arch` input    |

**`.workshop/vendor-noble.yaml` and `.workshop/vendor-resolute.yaml`**

| Placeholder    | Replace with   |
|----------------|----------------|
| `<vendor>`     | `vendor` input |
| `<Vendor>`     | `Vendor` input |
| `<soc>`        | `soc` input    |
| `<evk-board>`  | `evk_board` input |

After substitution, no `<placeholder>` token should remain in any of these files.
Run a final check:
```bash
grep -r '<[a-z]' <vendor>-workshop/config/ <vendor>-workshop/.workshop/*.yaml \
  | grep -v '^.*#' || echo "No remaining placeholders"
```

If any unsubstituted placeholders remain, report them and stop.

### 4. Rename and update workshop dispatch files

The template ships a single generic dispatch file `vendor-series.yaml` and a
`series-build/` provisioning SDK directory. Substitute the `<series>` and
`<ubuntu-version>` placeholders with the values for the selected release.

**Map Ubuntu release → substitution values:**

| Ubuntu release | `<series>` | `<Series>` | `<ubuntu-version>` |
|---------------|------------|------------|---------------------|
| jammy (22.04) | `jammy` | `Jammy` | `22.04` |
| noble (24.04) | `noble` | `Noble` | `24.04` |
| resolute (26.04) | `resolute` | `Resolute` | `26.04` |

Steps:
1. Rename `vendor-series.yaml` → `<vendor>-<series>.yaml`
2. In the renamed file, replace all `<series>`, `<Series>`, `<ubuntu-version>` tokens
3. Rename `series-build/` → `<series>-build/`
4. In all files under `<series>-build/`, replace `<series>`, `<Series>`, `<ubuntu-version>` tokens

### 5. Generate `sdk/snap/snapcraft/snapcraft.yaml`

Replace the placeholder values in `sdk/snap/snapcraft/snapcraft.yaml` using
the config-to-snapcraft mapping:

| Placeholder            | Replace with                                        |
|------------------------|-----------------------------------------------------|
| `linux-<vendor>-<soc>` | `kernel_pkg_name` input (e.g. `linux-qcom`)        |
| `<Vendor>`             | `Vendor` input                                      |
| `<soc>`                | `soc` input                     |
| `<evk-board>`          | `evk_board` input               |
| `<core-base>`          | `core_base` input               |
| `<toolchain-arch>:`    | `toolchain_arch` input + `:`    |
| `<kernel-flavour>`     | `kernel_flavour` input          |

The resulting `snapcraft.yaml` must contain:
- `plugin: kernel`
- `kernel-ubuntu-debian-package: true`
- `kernel-ubuntu-kconfigflavour: <kernel_flavour>`
- `base: <core_base>`

Verify current Snapcraft Kernel plugin documentation before modifying keys:
https://documentation.ubuntu.com/snapcraft/latest/reference/plugins/kernel_plugin/

### 6. Validate — no credentials in config

Re-read `config/workshop.yaml`. If `kernel.repository` contains a `:`
followed by non-empty text before a `@` character (credential pattern), reject
with the error from step 1.

A `git+ssh://` URL is explicitly permitted.

### 7. Register in catalog.yaml

If `catalog.yaml` does not exist at the catalog root, create it first:

```yaml
# Silicon Workshop Catalog
# Machine-readable index for the BSP agent to discover and select workshops.
# Add a new entry here each time you create a workshop with create-workshop.

schema_version: 1

workshops:
```

Then append a new entry:

```yaml
  - name: <vendor>-workshop
    vendor: <vendor>
    soc_families:
      - <soc>                # add additional soc_families if provided
    evk: <evk_board>
    path: <vendor>-workshop/
    ubuntu_releases:
      - <ubuntu_release>
```

### 8. Print next steps

Report what was created and print the following next steps for the user:

```
Workshop created: <vendor>-workshop/

Next steps:
  1. Review config/workshop.yaml — verify all values are correct.
  2. If the kernel repository is private, ensure your ssh-agent has the
     appropriate key loaded before cloning.
  3. Launch the workshop:
       workshop launch <vendor>-<release>
  4. Clone the kernel source (run once):
       workshop run <vendor>-<release> -- clone-kernel
  5. Build Debian packages (Ubuntu Classic target):
       workshop run <vendor>-<release> -- kernel-build-debs
  6. Build kernel snap (Ubuntu Core target):
       workshop run <vendor>-<release> -- kernel-build-snap
  7. When the EVK build succeeds, update catalog.yaml and commit both
     <vendor>-workshop/ and catalog.yaml to the workshop_catalog repository.
```

---

## Toolchain Notes

**Always read the kernel tree's `debian/control` `Build-Depends` before
assuming a toolchain version.** Different kernel branches have different
requirements. Examples found in practice:

| Kernel | Ubuntu base | clang | rustc | bindgen |
|--------|-------------|-------|-------|---------|
| linux-renesas 7.0 (resolute) | resolute 26.04 | clang-21 | 1.93.1 (native) | bindgen |
| linux-qcom 6.8 (noble) | noble 24.04 | clang-18 | 1.75 (native) | bindgen-0.65 |
| linux-mtk (noble) | noble 24.04 | clang-18 | 1.75 (native) | bindgen-0.65 |
| linux-mtk (jammy) | jammy 22.04 | clang-18 | 1.75 (native) | bindgen-0.65 |

### Jammy (22.04) workshops — clang-18 kernels (e.g. MediaTek 5.15)
Jammy kernels use `clang-18` and `bindgen-0.65`. Use `rustc` (default Jammy),
`rust-src`, `rustfmt`. No LLVM 21 repo needed.

> **Important:** Jammy kernel 5.15 Build-Depends also requires `dwarfdump`
> (the `dwarfdump` package), which is **separate from `dwarves`**. Both must be
> installed. Without `dwarfdump` the kernel build fails with:
> ```
> /bin/sh: dwarfdump: not found
> ```

### Noble (24.04) workshops — clang-21 kernels (e.g. Renesas noble, MediaTek)
These kernels require `clang-21` which is **not in Noble's default archive**.
The `noble-build/hooks/setup-base` adds `apt.llvm.org/noble/` and installs
`clang-21`, `llvm-21-dev`, `rustc-1.91`, `rust-1.91-src`, `rustfmt` (via
`rustfmt-1.91` slave). The `update-alternatives` call registers `rustc-1.91`
as the unversioned `rustc`. **`rust-src` must also be installed** — without it
the kernel's `make rustavailable` fails with "core standard library not found".

### Noble (24.04) workshops — clang-18 kernels (e.g. Qualcomm, MediaTek)
These kernels use `clang-18` (available in Noble's default archive) and
`bindgen-0.65`. Use `rustc` (default Noble 1.75), `rust-src`, `rustfmt`.
No LLVM 21 repo needed. No `update-alternatives` needed.

**Important:** The `check-health` hook must check for `bindgen-0.65` (not
`bindgen`) when `bindgen-0.65` is installed. Using the wrong name causes the
health check to fail and the workshop refresh to abort.

### Resolute (26.04) workshops (e.g. Renesas resolute)
Resolute ships `rustc 1.93.1` as the default `rustc` package. No versioned
packages or `update-alternatives` are needed. The `resolute-build/hooks/setup-base`
installs `rustc`, `rust-src`, `rustfmt`, and `bindgen` directly.

### Ubuntu release matching
**Always use the workshop variant that matches `ubuntu.release` in config.**
If `config/workshop.yaml` says `release: resolute`, use `workshop launch <vendor>-resolute`.
Using the wrong variant (e.g. noble for a resolute kernel) causes toolchain
version failures that are hard to debug.

### Private Launchpad repos and SSH
For `git+ssh://` repos, the workshop container's `~/.ssh/config` must have
`User <launchpad-id>` for `git.launchpad.net`. This is NOT forwarded from the
host's `~/.ssh/config` by the ssh-agent plug — only the agent socket is forwarded.
Add a `LAUNCHPAD_USER=<id>` entry to `config/board.env` (gitignored) and ensure
`setup-project` reads it. See the `mediatek-workshop` for the pattern.

### check-config false positives
Some kernels have multi-flavour annotations where one flavour disables Rust
(e.g. `arm64-qcom-rt: '-'`) but another requires it (e.g. `arm64: 'y'`).
If `check-config` fails with `CONFIG_RUST_IS_AVAILABLE changed from y to -`
on the non-RT flavour, the annotation is wrong — update it:
```bash
sed -i "s/'arm64-qcom-rt': '-'/'arm64-qcom-rt': 'y'/" \
  kernel-src/debian.qcom/config/annotations
```

### Validation note
`dpkg-deb -c` lists package contents with a `./` prefix (e.g. `./boot/vmlinuz-...`).
The `sdk/deb/lib/validate.sh` boot-image check uses `\.?/boot/` to match both
`/boot/` and `./boot/` correctly.

## Guardrails

- NEVER embed credentials in `config/workshop.yaml` or `snapcraft.yaml`.
- NEVER modify other existing workshop.
- NEVER modify `workshop-template/` — it is the canonical template.
- Do NOT run any build commands. This skill only creates the workshop scaffold.
- If the user provides ambiguous inputs, ask for clarification before writing files.
- Always run the placeholder check (step 3) before reporting completion.
