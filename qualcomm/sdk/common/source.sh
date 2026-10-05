#!/usr/bin/bash
# sdk/common/source.sh — shared kernel source acquisition.
#
# Source acquisition is a SEPARATE, explicit step (the clone-kernel command),
# not part of the build. The build commands (kernel-build-debs /
# kernel-build-snap) only require that kernel-src/ already exists — they never
# clone or fetch. This lets you clone once and rebuild repeatedly (and inspect
# or hand-patch the tree before building) without re-hitting the network.
#
# Public https:// repos need no auth. Private git+ssh:// repos authenticate via
# the forwarded ssh-agent; Launchpad login mapping comes from
# identity.launchpad_user in config/workshop.yaml (applied by the setup hooks).

[[ -n "${_WORKSHOP_SOURCE_SH:-}" ]] && return 0
_WORKSHOP_SOURCE_SH=1

# workshop_clone_source ROOT REPO REF_TYPE REF_VALUE
# Explicit clone/checkout (used by the clone-kernel command).
# If kernel-src already exists, updates it (fetch) and re-checks-out the ref.
# Echoes the resolved commit SHA on stdout.
workshop_clone_source() {
    local root="${1}" repo="${2}" ref_type="${3}" ref_value="${4}"
    local src="${root}/kernel-src"

    if [[ -d "${src}/.git" ]]; then
        workshop_log "kernel-src already present — updating (git fetch)..."
        git -C "${src}" fetch --tags --prune origin >&2 \
            || workshop_warn "git fetch failed; using existing checkout"
    else
        workshop_log "Cloning ${repo} → kernel-src ..."
        git clone "${repo}" "${src}" >&2 \
            || workshop_fail "git clone failed for ${repo}"
    fi

    local target=""
    case "${ref_type}" in
        tag)    target="refs/tags/${ref_value}" ;;
        branch) target="origin/${ref_value}" ;;
        commit) target="${ref_value}" ;;
    esac

    workshop_log "Checking out ${ref_type}: ${ref_value}"
    git -C "${src}" checkout -f -q "${target}" 2>/dev/null \
        || git -C "${src}" checkout -f -q "${ref_value}" 2>/dev/null \
        || workshop_fail "Cannot check out ${ref_type} '${ref_value}'"

    local sha
    sha="$(git -C "${src}" rev-parse HEAD)" \
        || workshop_fail "Cannot resolve HEAD after checkout"

    [[ -f "${src}/debian/rules" ]] \
        || workshop_fail "${src}/debian/rules not found — not an Ubuntu kernel packaging tree?"

    echo "${sha}"
}

# workshop_require_source ROOT
# Assert kernel-src exists (build commands call this). Never clones/fetches.
# Echoes the current HEAD SHA on stdout.
workshop_require_source() {
    local root="${1}"
    local src="${root}/kernel-src"

    [[ -d "${src}/.git" ]] || workshop_fail \
        "kernel-src not found. Clone it first: workshop run -- clone-kernel"
    [[ -f "${src}/debian/rules" ]] || workshop_fail \
        "kernel-src/debian/rules not found — not an Ubuntu kernel packaging tree? Re-run clone-kernel."

    git -C "${src}" rev-parse HEAD 2>/dev/null || echo "unknown"
}

# workshop_apply_patches ROOT PATCHES(|-separated)
workshop_apply_patches() {
    local root="${1}" patches="${2:-}"
    local src="${root}/kernel-src"
    [[ -n "${patches}" ]] || { workshop_log "No patches configured."; return 0; }
    local IFS='|' p
    for p in ${patches}; do
        [[ -n "${p}" ]] || continue
        local abs="${root}/${p}"
        [[ -f "${abs}" ]] || workshop_fail "Patch not found: ${abs}"
        workshop_log "Applying patch: ${p}"
        git -C "${src}" apply --index "${abs}" \
            || workshop_fail "Patch failed to apply: ${p}"
    done
    return 0
}
