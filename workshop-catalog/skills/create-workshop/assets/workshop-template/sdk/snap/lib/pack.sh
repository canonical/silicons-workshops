#!/usr/bin/bash
# sdk/snap/lib/pack.sh — Ubuntu Core kernel snap build.
#
# Builds the kernel snap using Snapcraft's Kernel plugin against the
# workshop-owned sdk/snap/snapcraft/snapcraft.yaml. This uses:
#   plugin: kernel
#   kernel-ubuntu-debian-package: true
#
# Snapcraft handles both the kernel .deb build (via debian/rules) and the
# final snap assembly in a single run. The kernel source tree does NOT need
# to ship a snapcraft.yaml; snapcraft.yaml points at ../../../kernel-src.
#
# Snapcraft has no --project-dir option: it always works on the project in the
# current directory, so snap_build changes into the project directory first.
# The kernel plugin is still experimental, hence --enable-experimental-plugins.

[[ -n "${_SNAP_PACK_SH:-}" ]] && return 0
_SNAP_PACK_SH=1

# snap_locate_snapcraft_project ROOT
# Echoes the directory that contains the SDK-owned snapcraft.yaml.
snap_locate_snapcraft_project() {
    local root="${1}"
    local project="${root}/sdk/snap/snapcraft"
    if [[ -f "${project}/snapcraft.yaml" ]]; then
        echo "${project}"
    else
        return 1
    fi
}

# snap_build ROOT ARCH — runs snapcraft pack from the SDK snapcraft project.
snap_build() {
    local root="${1}" arch="${2}"
    local project
    project="$(snap_locate_snapcraft_project "${root}")" || workshop_fail \
        "No sdk/snap/snapcraft/snapcraft.yaml found. Run the create-workshop skill to generate it."

    workshop_register_binfmt "${arch}"

    workshop_log "Building kernel snap via Snapcraft Kernel plugin for ${arch}..."
    (
        cd "${project}"
        # Snapcraft runs as root; --preserve-env forwards ssh-agent for
        # git+ssh:// kernel sources (private repos authenticate this way).
        # SNAPCRAFT_OPTS is intentionally unquoted so it can carry several flags.
        # shellcheck disable=SC2086
        sudo --preserve-env=SSH_AUTH_SOCK \
            snapcraft pack \
                --destructive-mode \
                --enable-experimental-plugins \
                --build-for="${arch}" \
                ${SNAPCRAFT_OPTS:-} >&2 \
            || workshop_fail "snapcraft pack failed"
    )
    return 0
}

# snap_stage ROOT — collect produced .snap into out/snap/.
snap_stage() {
    local root="${1}"
    local project
    project="$(snap_locate_snapcraft_project "${root}")" || workshop_fail \
        "SDK snapcraft project not found for staging"
    local out="${root}/out/snap"

    mkdir -p "${out}/metadata"
    rm -rf "${out:?}"/* 2>/dev/null || true
    mkdir -p "${out}/metadata"

    local count=0 f
    shopt -s nullglob
    # Snapcraft places the .snap in the project directory (sdk/snap/snapcraft/).
    for f in "${project}"/*.snap; do
        mv -f "${f}" "${out}/"
        count=$((count+1))
    done
    shopt -u nullglob
    [[ ${count} -gt 0 ]] || workshop_fail "No .snap found after snapcraft pack"
    workshop_log "Staged ${count} snap(s) to ${out}/"
    ( cd "${out}" && ls -1 ./*.snap ) > "${out}/metadata/snaps.txt"
}
