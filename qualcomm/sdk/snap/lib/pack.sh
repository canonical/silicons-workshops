#!/usr/bin/bash
# sdk/snap/lib/pack.sh — Ubuntu Core kernel snap build (deb → initrd plugin).
#
# Qualcomm builds the kernel snap the contract's "deb → plugin:kernel" way
# (contract §8 alternative path; see DESIGN.md § Divergences): it reuses the
# Goal/deb-SDK Ubuntu debs (linux-image + linux-modules) rather than
# recompiling, and assembles an Ubuntu Core initrd with snapcraft's `initrd`
# plugin. The recipe lives in sdk/snap/snapcraft/ (the contract-reserved slot).
#
# Requirements (provisioned by .workshop/noble-build): a snapcraft with the
# initrd plugin (latest/edge) and an arm64 binfmt/qemu-user handler for the
# initrd chroot.

[[ -n "${_SNAP_PACK_SH:-}" ]] && return 0
_SNAP_PACK_SH=1

# snap_recipe_dir ROOT — echoes the snapcraft recipe dir (has snap/snapcraft.yaml).
snap_recipe_dir() {
    local root="${1}"
    echo "${root}/sdk/snap/snapcraft"
}

# snap_build ROOT ARCH — stage the deb-SDK debs + dtb, then snapcraft pack.
snap_build() {
    local root="${1}" arch="${2}"
    local recipe; recipe="$(snap_recipe_dir "${root}")"
    local debs="${root}/out/deb"

    [[ -f "${recipe}/snap/snapcraft.yaml" ]] \
        || workshop_fail "snap recipe missing: ${recipe}/snap/snapcraft.yaml"

    # Inputs: the deb-SDK image + modules debs must exist.
    local img mods
    img="$(ls "${debs}"/linux-image-*_"${arch}".deb 2>/dev/null | head -1 || true)"
    mods="$(ls "${debs}"/linux-modules-*_"${arch}".deb 2>/dev/null | head -1 || true)"
    [[ -n "${img}" && -n "${mods}" ]] \
        || workshop_fail "missing deb-SDK debs in out/deb — run 'kernel-build-debs' first"

    command -v snapcraft >/dev/null 2>&1 \
        || workshop_fail "snapcraft not installed (snap install snapcraft --classic --channel=latest/edge)"

    workshop_register_binfmt "${arch}"

    # Stage inputs where the (destructive) build reads them.
    local inputs="${recipe}/build-inputs"
    mkdir -p "${inputs}"
    rm -f "${inputs}"/*.deb "${inputs}"/*.dtb 2>/dev/null || true
    cp -f "${img}" "${mods}" "${inputs}/"

    # Best-effort: extract each configured DTB from the debs into build-inputs.
    # The recipe treats the dtb as optional (staged only if present).
    local IFS='|' dtb
    for dtb in ${CFG_KERNEL_DTBS:-}; do
        [[ -n "${dtb}" ]] || continue
        local found
        found="$(dpkg-deb --fsys-tarfile "${img}" 2>/dev/null | tar -tf - 2>/dev/null | grep -E "${dtb}\.dtb$" | head -1 || true)"
        if [[ -n "${found}" ]]; then
            dpkg-deb --fsys-tarfile "${img}" 2>/dev/null | tar -xf - -C "${inputs}" "${found#./}" 2>/dev/null || true
            find "${inputs}" -name "${dtb}.dtb" -exec cp -f {} "${inputs}/${dtb}.dtb" \; 2>/dev/null || true
        else
            workshop_warn "dtb ${dtb}.dtb not found in linux-image deb; snap will ship without it"
        fi
    done
    unset IFS

    workshop_log "Building kernel snap (deb → initrd plugin) for ${arch} via snapcraft..."
    (
        cd "${recipe}"
        sudo --preserve-env=SSH_AUTH_SOCK \
            snapcraft pack --destructive-mode --build-for="${arch}" ${SNAPCRAFT_OPTS:-} >&2 \
            || workshop_fail "snapcraft pack failed"
    )
    return 0
}

# snap_stage ROOT — collect the produced .snap into out/snap/.
snap_stage() {
    local root="${1}"
    local recipe; recipe="$(snap_recipe_dir "${root}")"
    local out="${root}/out/snap"

    mkdir -p "${out}/metadata"
    rm -rf "${out:?}"/* 2>/dev/null || true
    mkdir -p "${out}/metadata"

    local count=0 f
    shopt -s nullglob
    for f in "${recipe}"/*.snap; do
        mv -f "${f}" "${out}/"
        count=$((count+1))
    done
    shopt -u nullglob

    [[ "${count}" -gt 0 ]] || workshop_fail "No .snap file was produced."
    workshop_log "Staged ${count} snap(s) → out/snap/"
    ( cd "${out}" && ls -1 *.snap ) > "${out}/metadata/snaps.txt"
    return 0
}
