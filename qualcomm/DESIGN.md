# Qualcomm Silicon Workshop — Design & Contract Divergences

This workshop follows the shared silicon-workshop contract
(`SILICON_WORKSHOP_CONTRACT.md`) and mirrors the renesas reference layout
(config = WHAT, `sdk/` = HOW, `.workshop/` = thin dispatch + provisioning).
This file records where Qualcomm **diverges** from the renesas reference and
why. Each divergence is deliberate and, where the contract offers a choice,
uses a contract-sanctioned path.

---

## 1. Snap is built deb → plugin:kernel, not from source (contract §8 alt path)

**renesas:** builds the kernel snap from the kernel *source* tree's own
`snap/snapcraft.yaml` (`snapcraft pack` in `kernel-src/`).

**qualcomm:** builds the snap the contract's **alternative deb → plugin:kernel
path**. `kernel-build-snap` reuses the deb-SDK output (`linux-image` +
`linux-modules`) and assembles an Ubuntu Core initrd with snapcraft's `initrd`
plugin. The recipe lives in the contract-reserved `sdk/snap/snapcraft/` slot.

**Why:**
- The reference Rubik Pi 3 `linux-debian` tree does not ship a Core
  `snap/snapcraft.yaml`, so the from-source path is not available as-is.
- Reusing the validated `.deb`s means **no second kernel compile** for the snap.
- This is exactly the path the contract reserves (§8), and the path the
  renesas `sdk/snap/snapcraft/README.md` documents as the reserved slot.

**Consequence:** `kernel-build-snap` requires `kernel-build-debs` to have run
first (it consumes `out/deb/`). The snap-SDK reads the source only for
identity/version.

---

## 2. Vendor config block: fragments / disable (contract §4)

**renesas:** `kernel.config` is just `{type: flavour, value: renesas}`.

**qualcomm:** adds a vendor block under `kernel`:

| Key | Purpose |
|-----|---------|
| `kernel.config.fragments` | kconfig fragments merged onto the flavour via `annotations --update` (Ubuntu Core snapd baseline + customer delta) |
| `kernel.config.disable`   | kconfig symbols to force-off (e.g. `CORESIGHT_DUMMY`/`CORESIGHT_TPDM`, which break `-Werror` on this BSP) |

**Why:** Qualcomm BSPs need a customer kconfig delta and a snapd baseline merged
in, plus a couple of tree-specific build-break workarounds. Keeping them as
declarative data (not script edits) preserves the "an agent edits only the
config" contract principle. These are additive keys; a workshop that ignores
them still builds.

---

## 3. Kconfig injected via Ubuntu annotations, verified in /boot/config

The snapd baseline (`config/canonical-snapd.config`) and customer delta
(`config/customer.config`) are merged with
`debian/scripts/misc/annotations --update` (the cranky-correct mechanism), then
reconciled with `debian/rules updateconfigs`. `deb_validate` additionally checks
the packaged `/boot/config` carries the snapd baseline
(`SQUASHFS`/`APPARMOR`/`USER_NS`/`OVERLAY_FS`/`SECCOMP_FILTER`) — a stronger
output check than the renesas deb validator.

---

## 4. No bare-make image path (packaging-only deliverables)

The native Ubuntu `debian/rules` build handles the vendor techpack dirs
(`ubuntu/qcom/<dir>`) correctly, so `kernel-build-debs` does **not** edit
`ubuntu/qcom/Makefile`. The original bare-`make Image.gz` "Goal 1" path from the
source workshop (which needed per-dir techpack skips) is **not** exposed here:
the contract's deliverables are the `.deb` and the `.snap`, both of which come
from packaging, not a bare image build.

---

## 5. Single-config, not per-board kit (contract §2.4)

The source workshop this was derived from was board-*parametrized* (a
`board-input/<board>/` kit per board, selected by a command argument, with a
per-goal `check-manifest` gate). To match the contract's single declarative
`config/workshop.yaml` model (as renesas does), this workshop describes **one
board at a time** in the config. Adding another board = editing the config (or
`WORKSHOP_BOARD`), not adding a kit.

The dropped `check-manifest` goal-gate is replaced by ordinary config
validation (`workshop_validate_config`) plus each command's input preconditions
(`kernel-build-snap` requires `out/deb/`). If the contract later calls for an
explicit multi-board/goal gate, it can be reintroduced as a `common/` helper
without disturbing the SDK shape.

---

## 6. One release variant (noble / 24.04)

**renesas:** ships two variants (noble 24.04 + resolute 26.04).

**qualcomm:** ships one, `qcom-noble` (24.04), matching the validated Rubik Pi 3
kernel (`linux-debian` 6.8.12, noble-based). A resolute variant can be added the
same way renesas does it — a second `.workshop/qcom-resolute.yaml` + a
`resolute-build` provisioning SDK — with all `sdk/` scripts shared unchanged.

---

## 7. Status / known limitations

- **Snap not yet booted on hardware.** The snap is structurally complete
  (`type: kernel` + kernel + initrd + modules + dtb); an on-device boot needs a
  full Ubuntu Core image + gadget snap + signed model assertion on a real
  Rubik Pi 3.
- **snapcraft nesting is a one-time manual step** (README §3b): snapcraft is a
  classic snap needing `snapd` + `security.nesting=true`, which a container-side
  hook cannot set.
- **Reference board doubles as BSP.** The Rubik Pi 3 `linux-debian` tree is
  already noble-based, so it is both the example and the stand-in "BSP".
