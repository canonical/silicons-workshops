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

    # 3. a linux-image package containing a kernel image must be present
    local have_image=0
    for d in "${debs[@]}"; do
        case "$(basename "${d}")" in
            linux-image-*)
                # grep -q exits on first match and SIGPIPEs dpkg-deb; under
                # pipefail that makes the pipeline fail even on a match, so
                # capture the listing first and grep the saved output.
                local listing
                listing="$(dpkg-deb -c "${d}" 2>/dev/null || true)"
                if grep -Eq '/boot/(vmlinuz|Image|zImage|uImage)' <<<"${listing}"; then
                    have_image=1
                fi
                ;;
        esac
    done
    [[ "${have_image}" -eq 1 ]] || errors+=("no linux-image-*.deb containing a /boot kernel image")

    # 4. the snapd baseline kconfig must be present in the packaged config
    #    (contract §11 verify: SQUASHFS / APPARMOR / USER_NS / OVERLAY_FS / SECCOMP).
    for d in "${debs[@]}"; do
        case "$(basename "${d}")" in
            linux-image-*)
                local cfg
                cfg="$(dpkg-deb --fsys-tarfile "${d}" 2>/dev/null | tar -xO --wildcards './boot/config-*' 2>/dev/null || true)"
                if [[ -n "${cfg}" ]]; then
                    local sym
                    for sym in CONFIG_SQUASHFS=y CONFIG_SECURITY_APPARMOR=y CONFIG_USER_NS=y CONFIG_OVERLAY_FS=y CONFIG_SECCOMP_FILTER=y; do
                        grep -q "^${sym}$" <<<"${cfg}" \
                            || workshop_warn "packaged /boot/config missing ${sym} (snapd baseline)"
                    done
                fi
                ;;
        esac
    done

    if [[ ${#errors[@]} -gt 0 ]]; then
        workshop_fail "Debian output validation failed:"$'\n'"$(printf '  - %s\n' "${errors[@]}")"
    fi
    workshop_log "Debian output validation passed (${#debs[@]} package(s), arch=${arch})."
}
