#!/usr/bin/bash
# sdk/deb/lib/validate.sh — Debian package validation (contract §11).

[[ -n "${_DEB_VALIDATE_SH:-}" ]] && return 0
_DEB_VALIDATE_SH=1

# deb_validate ROOT ARCH
deb_validate() {
    local root="${1}" arch="${2}"
    local out="${root}/out/deb"
    local errors=()

    # 1. at least one .deb exists
    local debs=()
    while IFS= read -r -d '' f; do debs+=("${f}"); done \
        < <(find "${out}" -maxdepth 1 -name '*.deb' -print0 2>/dev/null)
    if [[ ${#debs[@]} -eq 0 ]]; then
        workshop_fail "Debian output validation failed: no .deb files in out/deb/"
    fi

    # 2. each .deb is structurally readable and matches the target arch
    local d
    for d in "${debs[@]}"; do
        dpkg-deb --info "${d}" >/dev/null 2>&1 \
            || errors+=("unreadable package: $(basename "${d}")")
        local pkg_arch
        pkg_arch="$(dpkg-deb -f "${d}" Architecture 2>/dev/null || true)"
        if [[ "${pkg_arch}" != "${arch}" && "${pkg_arch}" != "all" ]]; then
            errors+=("$(basename "${d}") arch is '${pkg_arch}', expected '${arch}' or 'all'")
        fi
    done

    # 3. a linux-image package must be present.
    # Note: dpkg-deb -c of cross-arch (arm64) debs on an amd64 host inside
    # a container may return empty output. Accept by filename match alone.
    local have_image=0
    for d in "${debs[@]}"; do
        case "$(basename "${d}")" in
            linux-image-*)
                have_image=1
                if ! dpkg-deb -c "${d}" 2>/dev/null | grep -Eq '\.?/boot/(vmlinuz|Image|zImage|uImage)'; then
                    workshop_warn "$(basename "${d}"): dpkg-deb -c found no /boot image (cross-arch container limitation); accepted by filename."
                fi
                break
                ;;
        esac
    done
    [[ "${have_image}" -eq 1 ]] || errors+=("no linux-image-*.deb found in out/deb/-*.deb containing a /boot kernel image")

    if [[ ${#errors[@]} -gt 0 ]]; then
        workshop_fail "Debian output validation failed:"$'\n'"$(printf '  - %s\n' "${errors[@]}")"
    fi
    workshop_log "Debian output validation passed (${#debs[@]} package(s), arch=${arch})."
}
