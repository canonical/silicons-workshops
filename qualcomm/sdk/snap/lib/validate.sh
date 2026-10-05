#!/usr/bin/bash
# sdk/snap/lib/validate.sh — kernel snap validation (contract §11 / §8.3).

[[ -n "${_SNAP_VALIDATE_SH:-}" ]] && return 0
_SNAP_VALIDATE_SH=1

# snap_validate ROOT
snap_validate() {
    local root="${1}"
    local out="${root}/out/snap"
    local errors=()

    # 1. a .snap exists
    local snaps=()
    while IFS= read -r -d '' f; do snaps+=("${f}"); done \
        < <(find "${out}" -maxdepth 1 -name '*.snap' -print0 2>/dev/null)
    [[ ${#snaps[@]} -gt 0 ]] || workshop_fail "Snap output validation failed: no .snap in out/snap/"

    local s="${snaps[0]}"

    # 2. snap metadata is readable and of type: kernel
    if command -v unsquashfs >/dev/null 2>&1; then
        local meta
        meta="$(unsquashfs -cat "${s}" meta/snap.yaml 2>/dev/null || true)"
        if [[ -z "${meta}" ]]; then
            errors+=("cannot read meta/snap.yaml from $(basename "${s}")")
        else
            grep -Eq '^type:[[:space:]]*kernel' <<<"${meta}" \
                || errors+=("$(basename "${s}") is not type: kernel")
        fi
        # 3. expected kernel + initrd content present
        local listing
        listing="$(unsquashfs -l "${s}" 2>/dev/null || true)"
        grep -Eq '(kernel\.img|Image|vmlinuz)' <<<"${listing}" \
            || errors+=("no kernel image found inside $(basename "${s}")")
        grep -Eq 'initrd\.img' <<<"${listing}" \
            || errors+=("no initrd.img found inside $(basename "${s}") (deb → initrd plugin path must produce one)")
        grep -Eq 'modules' <<<"${listing}" \
            || workshop_warn "no 'modules' entry visible in snap listing"
    else
        workshop_warn "unsquashfs not available — skipping snap content validation (install squashfs-tools)"
    fi

    if [[ ${#errors[@]} -gt 0 ]]; then
        workshop_fail "Snap output validation failed:"$'\n'"$(printf '  - %s\n' "${errors[@]}")"
    fi
    workshop_log "Snap output validation passed ($(basename "${s}"))."
}
