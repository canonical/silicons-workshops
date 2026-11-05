#!/usr/bin/env python3
"""Static checks for a generated Silicon Workshop. No network, no build.

Catches, in under a second, the defects that otherwise cost a failed launch or
a failed multi-hour kernel build: a definition the workshop tool rejects, a
snapcraft.yaml snapcraft refuses, a pack.sh using a flag that does not exist,
leftover placeholders, credentials in the kernel URL, a toolchain block that
does not match, and (with --kernel-src) kernel Build-Depends that the build
host does not install.

Usage:
  python3 scripts/check_workshop.py <workshop-dir> [--kernel-src]

Prints JSON: {"ok": bool, "errors": [...], "warnings": [...]}.
Exit status 0 when there are no errors, 1 otherwise, 2 on bad usage.
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wslib  # noqa: E402

# Top-level keys the workshop tool rejects in a workshop definition.
FORBIDDEN_DEFINITION_KEYS = ("summary", "description")
# Regex pieces of flags/forms known not to work, with the reason.
FORBIDDEN_PACK = (
    (r"--project-dir", "snapcraft has no --project-dir; cd into the project directory instead"),
)
EXECUTABLE_GLOBS = ("sdk/*/bin/*", ".workshop/*-build/hooks/*", ".workshop/*/hooks/*")
SYNTAX_GLOBS = ("sdk/**/*.sh", "sdk/*/bin/*", ".workshop/*/hooks/*")

# Build-Depends names that need a matching package on the build host.
WATCHED_DEP_RE = re.compile(
    r"^(clang-\d+|llvm-\d+-dev|libclang-\d+-dev|bindgen(-[\d.]+)?|rustc(-[\d.]+)?|"
    r"rust-src|rust-[\d.]+-src|rustfmt(-[\d.]+)?|dwarfdump)$"
)


class Findings:
    def __init__(self) -> None:
        self.errors: list[dict] = []
        self.warnings: list[dict] = []
        self.info: dict = {}

    def error(self, code: str, message: str, file: str = "") -> None:
        self.errors.append({"code": code, "message": message, "file": file})

    def warn(self, code: str, message: str, file: str = "") -> None:
        self.warnings.append({"code": code, "message": message, "file": file})


def top_level_keys(text: str) -> list[str]:
    return re.findall(r"(?m)^([A-Za-z_][A-Za-z0-9_-]*):", text)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------
# Individual checks
# --------------------------------------------------------------------------

def check_config(ws: Path, f: Findings) -> dict:
    path = ws / "config" / "workshop.yaml"
    if not path.is_file():
        f.error("config-missing", "config/workshop.yaml not found", "config/workshop.yaml")
        return {}
    cfg = wslib.load_config(ws)
    g = lambda *k: str(wslib.cfg_get(cfg, *k))  # noqa: E731

    for keys in (
        ("silicon", "vendor"), ("silicon", "soc"), ("silicon", "board"),
        ("ubuntu", "release"), ("ubuntu", "core_base"),
        ("kernel", "repository"), ("kernel", "ref", "type"), ("kernel", "ref", "value"),
        ("kernel", "config", "value"), ("toolchain", "arch"),
    ):
        if not g(*keys):
            f.error("config-missing-key", f"config/workshop.yaml: {'.'.join(keys)} is empty", "config/workshop.yaml")

    repo = g("kernel", "repository")
    if wslib.CRED_RE.search(repo):
        f.error("credentials-in-url", "kernel.repository embeds credentials; use git+ssh:// and ssh-agent", "config/workshop.yaml")

    ref_type, ref = g("kernel", "ref", "type"), g("kernel", "ref", "value")
    if ref_type not in ("tag", "commit", "branch"):
        f.error("bad-ref-type", f"kernel.ref.type is '{ref_type}', expected tag|commit|branch", "config/workshop.yaml")
    elif ref_type == "commit" and not re.fullmatch(r"[0-9a-f]{40}", ref):
        f.error("bad-commit", "kernel.ref.value must be a full 40-character commit SHA for type: commit", "config/workshop.yaml")
    elif ref_type == "branch":
        f.warn("moving-ref", "kernel.ref is a branch: the build is not reproducible", "config/workshop.yaml")

    release = g("ubuntu", "release")
    if release and release not in wslib.SERIES:
        f.error("bad-series", f"ubuntu.release '{release}' is not one of {', '.join(wslib.SERIES)}", "config/workshop.yaml")
    elif release and g("ubuntu", "core_base") != wslib.SERIES[release][2]:
        f.warn("core-base-mismatch", f"core_base {g('ubuntu', 'core_base')} is unusual for {release} (expected {wslib.SERIES[release][2]})", "config/workshop.yaml")
    return cfg


def check_placeholders(ws: Path, f: Findings) -> None:
    for root in wslib.SUBSTITUTE_ROOTS:
        base = ws / root
        files = [base] if base.is_file() else sorted(p for p in base.rglob("*") if p.is_file()) if base.is_dir() else []
        for p in files:
            for n, line in enumerate(read(p).splitlines(), 1):
                m = wslib.PLACEHOLDER_RE.search(line)
                if m:
                    rel = p.relative_to(ws).as_posix()
                    f.error("placeholder-left", f"unreplaced placeholder {m.group(0)} at line {n}", rel)
                    break


def check_definition(ws: Path, cfg: dict, f: Findings) -> str:
    defs = sorted((ws / ".workshop").glob("*.yaml")) if (ws / ".workshop").is_dir() else []
    if not defs:
        f.error("definition-missing", "no .workshop/<vendor>-<series>.yaml found", ".workshop")
        return ""
    if len(defs) > 1:
        f.warn("multiple-definitions", "several workshop definitions: " + ", ".join(d.name for d in defs), ".workshop")
    d = defs[0]
    text = read(d)
    rel = d.relative_to(ws).as_posix()
    for key in FORBIDDEN_DEFINITION_KEYS:
        if key in top_level_keys(text):
            f.error("definition-unknown-field", f"top-level '{key}:' is rejected by the workshop tool (unknown fields); keep prose in comments", rel)
    m = re.search(r"(?m)^name:\s*(\S+)", text)
    name = m.group(1) if m else ""
    vendor, release = str(wslib.cfg_get(cfg, "silicon", "vendor")), str(wslib.cfg_get(cfg, "ubuntu", "release"))
    if name and vendor and release and name != f"{vendor}-{release}":
        f.warn("definition-name", f"definition name '{name}' differs from {vendor}-{release}", rel)
    if release and not (ws / ".workshop" / f"{release}-build").is_dir():
        f.error("series-build-missing", f".workshop/{release}-build/ not found (ubuntu.release is {release})", ".workshop")
    return name


def check_snapcraft(ws: Path, cfg: dict, f: Findings) -> None:
    path = ws / "sdk" / "snap" / "snapcraft" / "snapcraft.yaml"
    rel = "sdk/snap/snapcraft/snapcraft.yaml"
    if not path.is_file():
        f.error("snapcraft-missing", f"{rel} not found", rel)
        return
    text = read(path)
    core = str(wslib.cfg_get(cfg, "ubuntu", "core_base"))
    flavour = str(wslib.cfg_get(cfg, "kernel", "config", "value"))

    if re.search(r"(?m)^base:", text):
        f.error("snapcraft-base", "`base:` is not allowed for type: kernel; use `build-base:`", rel)
    m = re.search(r"(?m)^build-base:\s*(\S+)", text)
    if not m:
        f.error("snapcraft-build-base", "`build-base:` is missing (a type: kernel snap needs it)", rel)
    elif core and m.group(1) != core:
        f.error("snapcraft-build-base", f"build-base is {m.group(1)}, config core_base is {core}", rel)
    if not re.search(r"(?m)^type:\s*kernel\b", text):
        f.error("snapcraft-type", "`type: kernel` is missing", rel)

    has_arch, has_platforms = "architectures" in top_level_keys(text), "platforms" in top_level_keys(text)
    if core in ("core20", "core22") and not has_arch:
        f.error("snapcraft-architectures", f"{core} needs an `architectures:` stanza with build-on/build-for (found {'platforms' if has_platforms else 'neither'})", rel)
    elif core in ("core24", "core26") and not has_platforms:
        f.error("snapcraft-platforms", f"{core} needs a `platforms:` stanza (found {'architectures' if has_arch else 'neither'})", rel)
    if re.search(r"(?m)^\s*build-for:\s*\[?\s*(\w+)", text) is None and (has_arch or has_platforms):
        f.error("snapcraft-build-for", "no build-for entry: the cross build target is undefined", rel)

    if not re.search(r"(?m)^\s*source:\s*\.\./\.\./\.\./kernel-src\s*$", text):
        f.error("snapcraft-source", "parts.kernel.source must be ../../../kernel-src (a '.' points at the SDK directory, not the kernel)", rel)
    if not re.search(r"(?m)^\s*plugin:\s*kernel\s*$", text):
        f.error("snapcraft-plugin", "`plugin: kernel` is missing", rel)
    if not re.search(r"(?m)^\s*kernel-ubuntu-debian-package:\s*true\s*$", text):
        f.error("snapcraft-debian-package", "`kernel-ubuntu-debian-package: true` is missing", rel)
    fm = re.search(r"(?m)^\s*kernel-ubuntu-kconfigflavour:\s*(\S+)", text)
    if not fm or (flavour and fm.group(1) != flavour):
        f.error("snapcraft-flavour", f"kernel-ubuntu-kconfigflavour is '{fm.group(1) if fm else ''}', config flavour is '{flavour}'", rel)
    nm = re.search(r"(?m)^name:\s*(\S+)", text)
    if nm and not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", nm.group(1)):
        f.error("snapcraft-name", f"snap name '{nm.group(1)}' must be lowercase letters, digits and single hyphens", rel)
    elif nm and len(nm.group(1)) > 40:
        f.error("snapcraft-name", f"snap name '{nm.group(1)}' is longer than 40 characters", rel)


def check_pack(ws: Path, f: Findings) -> None:
    path = ws / "sdk" / "snap" / "lib" / "pack.sh"
    rel = "sdk/snap/lib/pack.sh"
    if not path.is_file():
        f.error("pack-missing", f"{rel} not found", rel)
        return
    text = "\n".join(ln for ln in read(path).splitlines() if not ln.lstrip().startswith("#"))
    for pattern, why in FORBIDDEN_PACK:
        if re.search(pattern, text):
            f.error("pack-bad-flag", why, rel)
    if "--enable-experimental-plugins" not in text:
        f.error("pack-experimental", "snapcraft pack needs --enable-experimental-plugins for the kernel plugin", rel)
    if not re.search(r'cd\s+"?\$\{?project', text):
        f.error("pack-cwd", "snap_build must cd into the snapcraft project directory before `snapcraft pack`", rel)


def check_toolchain(ws: Path, f: Findings) -> str:
    """Hooks must have exactly one resolved toolchain block, and agree."""
    chosen = {}
    for name in ("setup-base", "check-health"):
        for p in sorted((ws / ".workshop").glob(f"*-build/hooks/{name}")):
            text = read(p)
            rel = p.relative_to(ws).as_posix()
            if re.search(r"(?m)^\s*#\s*[<>]{3}\s*toolchain:", text):
                f.error("toolchain-unresolved", "unresolved '# >>> toolchain:' markers: instantiate.py was not run", rel)
                continue
            if name == "setup-base":
                # The clang21 block assigns in two branches (indented); take both.
                found = re.findall(r"(?m)^[ \t]*TOOLCHAIN_PACKAGES=\((.*?)\)", text)
                if not found:
                    f.error("toolchain-packages", "TOOLCHAIN_PACKAGES=( ... ) is missing", rel)
                else:
                    chosen["setup-base"] = [p for group in found for p in group.split()]
            else:
                found = re.findall(r"(?m)^[ \t]*TOOLCHAIN_TOOLS=\((.*?)\)", text)
                if found:
                    chosen["check-health"] = [p for group in found for p in group.split()]
    packages, tools = chosen.get("setup-base", []), chosen.get("check-health", [])
    for t in tools:
        # A tool name usually equals its package; bindgen-0.65 / clang-18 do.
        if t not in packages and t != "bindgen" and t != "rustc" and t != "rustfmt":
            f.warn("toolchain-health-mismatch", f"check-health expects '{t}' but setup-base TOOLCHAIN_PACKAGES does not install it", ".workshop")
    clang = [p for p in packages if p.startswith("clang-")]
    return clang[0] if clang else ("no-clang" if packages else "")


def check_modes_and_syntax(ws: Path, f: Findings) -> None:
    for pattern in EXECUTABLE_GLOBS:
        for p in sorted(ws.glob(pattern)):
            if p.is_file() and not os.access(p, os.X_OK):
                f.error("not-executable", "script is not executable", p.relative_to(ws).as_posix())
    bash = shutil.which("bash")
    if not bash:
        f.warn("no-bash", "bash not found: skipped shell syntax checks")
        return
    seen = set()
    for pattern in SYNTAX_GLOBS:
        for p in sorted(ws.glob(pattern)):
            if not p.is_file() or p in seen:
                continue
            seen.add(p)
            head = read(p).splitlines()[:1]
            if head and ("bash" not in head[0] and "sh" not in head[0]):
                continue
            r = subprocess.run([bash, "-n", str(p)], capture_output=True, text=True)
            if r.returncode != 0:
                f.error("shell-syntax", r.stderr.strip().splitlines()[0] if r.stderr else "bash -n failed", p.relative_to(ws).as_posix())


def parse_build_depends(control: str) -> list[str]:
    """Package names from every Build-Depends* field of a debian/control."""
    names: list[str] = []
    for m in re.finditer(r"(?ms)^Build-Depends(?:-Indep|-Arch)?:\s*(.*?)(?=^\S)", control + "\nX:"):
        for part in re.split(r"[,\n]", m.group(1)):
            for alt in part.split("|"):
                alt = re.sub(r"[\[<(].*", "", alt.strip()).strip()
                alt = alt.split(":")[0].strip()
                if alt:
                    names.append(alt)
    return names


def rust_norm(name: str) -> str:
    """rustc-1.91 satisfies rustc, rust-1.91-src satisfies rust-src; clang-18 does not satisfy clang-21."""
    return re.sub(r"-\d[\d.]*", "", name) if name.startswith("rust") else name


def installed_packages(ws: Path) -> set[str]:
    """Package names the build-host hook installs: toolchain list, extra list, apt-get install body."""
    names: set[str] = set()
    for p in (ws / ".workshop").glob("*-build/hooks/setup-base"):
        text = read(p)
        for group in re.findall(r"(?m)^[ \t]*TOOLCHAIN_PACKAGES=\((.*?)\)", text):
            names.update(group.split())
        extra = text.split("# @EXTRA-PACKAGES-BEGIN")[-1].split("# @EXTRA-PACKAGES-END")[0] if "# @EXTRA-PACKAGES-BEGIN" in text else ""
        names.update(re.findall(r"(?m)^\s*([a-z0-9][a-z0-9+.-]*)\s*$", extra))
        m = re.search(r"apt-get install -y((?:[^\n]*\\\n)+[^\n]*)", text)
        if m:
            for ln in m.group(1).splitlines():
                if not ln.lstrip().startswith("`#"):
                    names.update(t for t in re.split(r"[\s\\]+", ln) if re.fullmatch(r"[a-z0-9][a-z0-9+.-]*", t))
    return names


def check_kernel_deps(ws: Path, f: Findings) -> None:
    """Compare the cloned kernel's toolchain Build-Depends with the hooks."""
    src = ws / "kernel-src"
    # debian/control is generated by `debian/rules clean`; a fresh clone has only
    # the stub of the flavour tree named in debian/debian.env (DEBIAN=debian.<x>).
    candidates = [src / "debian" / "control"]
    env = src / "debian" / "debian.env"
    if env.is_file():
        m = re.search(r"(?m)^\s*DEBIAN\s*=\s*(\S+)", read(env))
        if m:
            candidates += [src / m.group(1) / "control.stub.in", src / m.group(1) / "control.stub"]
    candidates += [src / "debian.master" / "control.stub.in", src / "debian.master" / "control.stub"]
    candidates += sorted(src.glob("debian.*/control.stub*"))
    control = next((p for p in candidates if p.is_file()), None)
    if control is None:
        f.warn("kernel-deps-skipped", "no debian/control or control.stub* found in kernel-src: the kernel Build-Depends were NOT compared with the build host")
        return
    f.info = {"deps_source": control.relative_to(src).as_posix()}
    wanted = sorted({n for n in parse_build_depends(read(control)) if WATCHED_DEP_RE.match(n)})
    installed = installed_packages(ws)
    for n in wanted:
        if rust_norm(n) not in {rust_norm(i) for i in installed}:
            f.error(
                "kernel-dep-missing",
                f"kernel Build-Depends lists '{n}' but setup-base does not install it "
                f"(add it to EXTRA_PACKAGES, or pick the matching toolchain profile)",
                ".workshop",
            )
    # The reverse is only a warning: extra toolchain packages are harmless but slow.
    has_rust = (src / "rust").is_dir()
    if not has_rust and any(i.startswith(("rustc", "clang-")) for i in installed):
        f.warn("toolchain-unneeded", "the kernel tree has no rust/ directory but the build host installs clang/rustc (harmless, slower launch)")


def run_checks(ws: Path, kernel_src: bool = False) -> Findings:
    f = Findings()
    if not ws.is_dir():
        f.error("no-workshop", f"{ws} is not a directory")
        return f
    cfg = check_config(ws, f)
    check_placeholders(ws, f)
    check_definition(ws, cfg, f)
    check_snapcraft(ws, cfg, f)
    check_pack(ws, f)
    check_toolchain(ws, f)
    check_modes_and_syntax(ws, f)
    if kernel_src:
        check_kernel_deps(ws, f)
    return f


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workshop", help="workshop directory")
    ap.add_argument("--kernel-src", action="store_true", help="also compare kernel-src/debian/control Build-Depends with the hooks")
    args = ap.parse_args()
    f = run_checks(Path(args.workshop).resolve(), args.kernel_src)
    print(json.dumps({"ok": not f.errors, "errors": f.errors, "warnings": f.warnings, "info": f.info}, indent=2))
    return 0 if not f.errors else 1


if __name__ == "__main__":
    sys.exit(main())
