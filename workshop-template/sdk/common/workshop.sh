#!/usr/bin/bash
# sdk/common/workshop.sh — Renesas Silicon Workshop shared helpers
#
# Sourced by every SDK (deb / snap) and by the out-of-scope gadget tool.
# Provides:
#   - logging (workshop_log / workshop_warn / workshop_fail)
#   - workshop root detection
#   - declarative config parsing from config/workshop.yaml (CFG_* variables)
#   - config validation
#   - toolchain / arch resolution
#   - board resolution
#   - job count
#
# The declarative config (config/workshop.yaml) says WHAT to build; this
# library and the SDK stage scripts say HOW. No credentials are read from
# configuration (contract §14): private-repo auth is supplied via ssh-agent.

set -euo pipefail

# Guard against double-sourcing.
[[ -n "${_WORKSHOP_COMMON_SH:-}" ]] && return 0
_WORKSHOP_COMMON_SH=1

# ---------------------------------------------------------------------------
# Logging. WORKSHOP_LOG_TAG lets each SDK label its output.
# ---------------------------------------------------------------------------

: "${WORKSHOP_LOG_TAG:=workshop}"

workshop_log()  { echo "[${WORKSHOP_LOG_TAG}] $*" >&2; }
workshop_warn() { echo "[${WORKSHOP_LOG_TAG}] WARNING: $*" >&2; }
workshop_fail() { echo "[${WORKSHOP_LOG_TAG}] ERROR: $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Workshop root detection (directory containing config/workshop.yaml).
# ---------------------------------------------------------------------------

workshop_find_root() {
    if [[ -n "${WORKSHOP_ROOT:-}" ]]; then
        echo "${WORKSHOP_ROOT}"
        return
    fi
    local dir
    dir="$(cd "$(dirname "${BASH_SOURCE[1]}")" && pwd)"
    while [[ "${dir}" != "/" ]]; do
        if [[ -f "${dir}/config/workshop.yaml" ]]; then
            echo "${dir}"
            return
        fi
        dir="$(dirname "${dir}")"
    done
    workshop_fail "Cannot locate workshop root (config/workshop.yaml not found). Set WORKSHOP_ROOT or run from within the workshop tree."
}

# ---------------------------------------------------------------------------
# Declarative config parsing → CFG_* variables.
# ---------------------------------------------------------------------------

workshop_read_config() {
    local root="${1}"
    local config="${root}/config/workshop.yaml"
    [[ -f "${config}" ]] || workshop_fail "Config not found: ${config}"

    local parsed
    parsed="$(python3 - "${config}" <<'PYEOF'
import sys, yaml
cfg = yaml.safe_load(open(sys.argv[1])) or {}

def get(d, *keys, default=''):
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return default
        d = d[k]
    return d if d is not None else default

print(f"CFG_SCHEMA_VERSION={get(cfg,'schema_version',default='1')}")
print(f"CFG_SILICON_VENDOR={get(cfg,'silicon','vendor')}")
print(f"CFG_SILICON_SOC={get(cfg,'silicon','soc')}")
print(f"CFG_SILICON_BOARD={get(cfg,'silicon','board')}")
print(f"CFG_UBUNTU_RELEASE={get(cfg,'ubuntu','release')}")
print(f"CFG_UBUNTU_CORE_BASE={get(cfg,'ubuntu','core_base',default='core24')}")
print(f"CFG_KERNEL_REPOSITORY={get(cfg,'kernel','repository')}")
print(f"CFG_KERNEL_REF_TYPE={get(cfg,'kernel','ref','type')}")
print(f"CFG_KERNEL_REF_VALUE={get(cfg,'kernel','ref','value')}")
print(f"CFG_KERNEL_CONFIG_TYPE={get(cfg,'kernel','config','type',default='flavour')}")
print(f"CFG_KERNEL_CONFIG_VALUE={get(cfg,'kernel','config','value')}")
print(f"CFG_TOOLCHAIN_ARCH={get(cfg,'toolchain','arch',default='arm64')}")
print(f"CFG_TOOLCHAIN_CROSS_COMPILE={get(cfg,'toolchain','cross_compile')}")

dtbs = get(cfg,'kernel','device_trees',default=[])
if not isinstance(dtbs, list):
    dtbs = [dtbs]
print("CFG_KERNEL_DTBS=" + "|".join(str(d) for d in dtbs))

patches = get(cfg,'patches',default=[])
if not isinstance(patches, list):
    patches = [patches]
print("CFG_PATCHES=" + "|".join(str(p) for p in patches))

oot = get(cfg,'drivers','out_of_tree',default=[])
if not isinstance(oot, list):
    oot = [oot]
print("CFG_DRIVERS_OOT=" + "|".join(str(o) for o in oot))

ppas = get(cfg,'archives','ppas',default=[])
if not isinstance(ppas, list):
    ppas = [ppas]
print("CFG_ARCHIVES_PPAS=" + "|".join(str(p) for p in ppas))
PYEOF
)"

    while IFS='=' read -r key val; do
        [[ -n "${key}" ]] || continue
        export "${key}=${val}"
    done <<< "${parsed}"

    # Allow runtime overrides for the two fields users commonly flip per-run.
    [[ -n "${WORKSHOP_ARCH:-}"  ]] && export CFG_TOOLCHAIN_ARCH="${WORKSHOP_ARCH}"
    [[ -n "${WORKSHOP_BOARD:-}" ]] && export CFG_SILICON_SOC="${WORKSHOP_BOARD}"
    return 0
}

# ---------------------------------------------------------------------------
# Config validation.
# ---------------------------------------------------------------------------

workshop_validate_config() {
    local errors=()

    [[ -n "${CFG_SCHEMA_VERSION:-}"     ]] || errors+=("schema_version is missing")
    [[ -n "${CFG_SILICON_VENDOR:-}"     ]] || errors+=("silicon.vendor is missing")
    [[ -n "${CFG_SILICON_SOC:-}"        ]] || errors+=("silicon.soc is missing")
    [[ -n "${CFG_SILICON_BOARD:-}"      ]] || errors+=("silicon.board is missing")
    [[ -n "${CFG_UBUNTU_RELEASE:-}"     ]] || errors+=("ubuntu.release is missing")
    [[ -n "${CFG_KERNEL_REPOSITORY:-}"  ]] || errors+=("kernel.repository is missing")
    [[ -n "${CFG_KERNEL_REF_TYPE:-}"    ]] || errors+=("kernel.ref.type is missing")
    [[ -n "${CFG_KERNEL_REF_VALUE:-}"   ]] || errors+=("kernel.ref.value is missing")
    [[ -n "${CFG_KERNEL_CONFIG_VALUE:-}" ]] || errors+=("kernel.config.value (flavour) is missing")
    [[ -n "${CFG_TOOLCHAIN_ARCH:-}"     ]] || errors+=("toolchain.arch is missing")

    case "${CFG_KERNEL_REF_TYPE:-}" in
        tag|branch|commit) ;;
        *) errors+=("kernel.ref.type must be one of: tag branch commit") ;;
    esac

    case "${CFG_TOOLCHAIN_ARCH:-}" in
        arm64|armhf|amd64) ;;
        *) errors+=("toolchain.arch must be one of: arm64 armhf amd64") ;;
    esac

    if [[ ${#errors[@]} -gt 0 ]]; then
        workshop_fail "Configuration validation failed:"$'\n'"$(printf '  - %s\n' "${errors[@]}")"
    fi

    workshop_log "Configuration valid: ${CFG_SILICON_VENDOR}/${CFG_SILICON_SOC}/${CFG_SILICON_BOARD} ubuntu=${CFG_UBUNTU_RELEASE} arch=${CFG_TOOLCHAIN_ARCH} ref=${CFG_KERNEL_REF_TYPE}:${CFG_KERNEL_REF_VALUE} flavour=${CFG_KERNEL_CONFIG_VALUE}"
}

# ---------------------------------------------------------------------------
# Toolchain / arch resolution. Sets and exports:
#   KERNEL_ARCH   — dpkg/kernel arch (arm64|armhf|amd64)
#   CROSS_COMPILE — compiler prefix ('' for native)
# ---------------------------------------------------------------------------

workshop_resolve_toolchain() {
    KERNEL_ARCH="${CFG_TOOLCHAIN_ARCH}"

    local cross="${CFG_TOOLCHAIN_CROSS_COMPILE:-}"
    if [[ -z "${cross}" ]]; then
        case "${KERNEL_ARCH}" in
            arm64) cross="aarch64-linux-gnu-" ;;
            armhf) cross="arm-linux-gnueabihf-" ;;
            amd64) cross="" ;;
        esac
    fi

    # Native build on a matching host needs no cross prefix.
    local host_arch; host_arch="$(uname -m)"
    if [[ "${KERNEL_ARCH}" == "arm64" && "${host_arch}" == "aarch64" ]]; then
        cross=""
    fi

    CROSS_COMPILE="${cross}"
    export KERNEL_ARCH CROSS_COMPILE
    workshop_log "Toolchain: ARCH=${KERNEL_ARCH} CROSS_COMPILE=${CROSS_COMPILE:-<native>} (host: ${host_arch})"
}

# ---------------------------------------------------------------------------
# qemu binfmt registration for foreign-arch chroots (initrd part).
# The binfmt_misc mount is not persistent across workshop invocations.
# ---------------------------------------------------------------------------

workshop_register_binfmt() {
    local arch="${1:-arm64}"
    [[ "${arch}" == "arm64" || "${arch}" == "armhf" ]] || return 0
    sudo mount -t binfmt_misc binfmt_misc /proc/sys/fs/binfmt_misc 2>/dev/null || true
    if [[ ! -e /proc/sys/fs/binfmt_misc/qemu-aarch64 && ! -e /proc/sys/fs/binfmt_misc/qemu-arm ]]; then
        workshop_log "Registering qemu binfmt handlers via systemd-binfmt..."
        sudo /usr/lib/systemd/systemd-binfmt 2>/dev/null \
            || sudo systemctl restart systemd-binfmt 2>/dev/null \
            || true
    fi
    if [[ "${arch}" == "arm64" && ! -e /proc/sys/fs/binfmt_misc/qemu-aarch64 ]]; then
        workshop_warn "qemu-aarch64 binfmt handler not registered; initrd chroot may fail."
    fi
}

# ---------------------------------------------------------------------------
# Concurrency.
# ---------------------------------------------------------------------------

workshop_jobs() { echo "${WORKSHOP_JOBS:-$(nproc)}"; }
