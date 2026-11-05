#!/usr/bin/env python3
"""Run a generated workshop stage by stage and keep the repair loop honest.

The skill's agent does the thinking; this script holds the rules that must not
depend on the agent remembering them:

  * the stage order and which stages are already done,
  * the repair budget (default 5 repair iterations per workshop),
  * stop on the same failure twice, on environment failures, and on anything
    that points into the kernel tree or its patches,
  * a path allowlist: a repair may touch only .workshop/, sdk/ and .gitignore,
    never kernel-src/, patches, config/workshop.yaml or the kernel ref,
  * a log of every attempt (REPAIR-LOG.md).

Commands (all print JSON on stdout; progress goes to stderr):

  run        --workshop DIR [--stages check,launch,clone,deps,deb,snap] [--force]
             Runs the stages in order, skipping those already ok, and stops at
             the first failure with a verdict.
  apply-fix  --workshop DIR --fix ID [--packages a,b]
             Applies a known fix from references/known-fixes.json.
  record-fix --workshop DIR --note TEXT
             Checks an edit the agent made by hand against the allowlist; keeps
             it when allowed, reverts it when not. Counts as a repair iteration.
  status     --workshop DIR
  report     --workshop DIR

Verdicts from `run`: continue | fix-available | diagnose | wait | stop.
Standard library only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_workshop  # noqa: E402
import wslib  # noqa: E402

FIXES_FILE = wslib.SKILL_DIR / "references" / "known-fixes.json"
STAGES = ("check", "launch", "clone", "deps", "deb", "snap")
MAX_ATTEMPTS = 5          # repair iterations per workshop (the user's rule)
LOG_SCAN_BYTES = 400_000  # only the end of a build log carries the cause
TAIL_LINES = 40
HEARTBEAT_SECONDS = 120
# Upper bounds passed to `workshop run --timeout`; a kernel build is ~1 h.
RUN_TIMEOUT = {"clone": "2h", "deb": "8h", "snap": "8h"}

# What a repair may change. Everything else is refused and reverted.
ALLOWED_PATHS = (r"^\.workshop/", r"^sdk/", r"^\.gitignore$")
# Never walked or compared: build output, the kernel tree, our own state.
EXCLUDED_DIRS = ("kernel-src", "out", ".repair", ".git", "cache", "build", "gadget-src")
EXCLUDED_PREFIXES = ("sdk/snap/snapcraft/parts", "sdk/snap/snapcraft/stage",
                     "sdk/snap/snapcraft/prime", "sdk/snap/snapcraft/overlay")
PKG_RE = re.compile(r"^[a-z0-9][a-z0-9+.-]*$")
VERSION_RE = re.compile(r"^\d[\d.:~+-]*$")


class Stop(Exception):
    """Fatal usage or safety error: message goes to stderr, exit 2."""


# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------

def now() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


def repair_dir(ws: Path) -> Path:
    return ws / ".repair"


def load_state(ws: Path) -> dict:
    path = repair_dir(ws) / "state.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "max_attempts": MAX_ATTEMPTS,
        "attempts_used": 0,
        "stage_ok": {},
        "last_failure": {},   # stage -> signature of the last failure
        "history": [],
        "pending": None,      # the attempt whose result is not known yet
        "runs": 0,
    }


def save_state(ws: Path, state: dict) -> None:
    repair_dir(ws).mkdir(parents=True, exist_ok=True)
    (repair_dir(ws) / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")


def load_fixes() -> list[dict]:
    return json.loads(FIXES_FILE.read_text(encoding="utf-8"))["fixes"]


def workshop_name(ws: Path) -> str:
    defs = sorted((ws / ".workshop").glob("*.yaml"))
    if not defs:
        raise Stop(f"{ws}: no .workshop/*.yaml definition")
    m = re.search(r"(?m)^name:\s*(\S+)", defs[0].read_text(encoding="utf-8"))
    if not m:
        raise Stop(f"{defs[0]}: no name:")
    return m.group(1)


# --------------------------------------------------------------------------
# Safety: manifest, snapshot, allowlist
# --------------------------------------------------------------------------

def manifest(ws: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for root, dirs, files in os.walk(ws):
        rel_root = Path(root).relative_to(ws).as_posix()
        dirs[:] = [
            d for d in dirs
            if d not in EXCLUDED_DIRS
            and not any(f"{rel_root}/{d}".lstrip("./").startswith(p) for p in EXCLUDED_PREFIXES)
        ]
        for name in files:
            p = Path(root) / name
            if p.is_symlink() or name.endswith(".snap"):
                continue
            rel = p.relative_to(ws).as_posix()
            if rel == "REPAIR-LOG.md":  # written by this script itself
                continue
            out[rel] = hashlib.sha1(p.read_bytes()).hexdigest() + (":x" if os.access(p, os.X_OK) else "")
    return out


def snapshot(ws: Path, tag: str) -> dict:
    """Copy the workshop's own files aside and remember the kernel tree state."""
    files = manifest(ws)
    base = repair_dir(ws) / "snapshots" / tag
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)
    for rel in files:
        dest = base / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ws / rel, dest)
    return {"tag": tag, "files": files, "kernel": kernel_status(ws)}


def kernel_status(ws: Path) -> list[str] | None:
    src = ws / "kernel-src"
    if not (src / ".git").exists():
        return None
    r = subprocess.run(
        ["git", "-C", str(src), "status", "--porcelain", "--untracked-files=no"],
        capture_output=True, text=True,
    )
    return sorted(r.stdout.splitlines()) if r.returncode == 0 else None


def changed_paths(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted({p for p in before.keys() | after.keys() if before.get(p) != after.get(p)})


def is_allowed(rel: str) -> bool:
    return any(re.match(p, rel) for p in ALLOWED_PATHS)


def guard(ws: Path, snap: dict) -> tuple[list[str], list[str]]:
    """Return (allowed_changes, violations); revert the workshop on violation."""
    after = manifest(ws)
    changes = changed_paths(snap["files"], after)
    allowed = [c for c in changes if is_allowed(c)]
    bad = [c for c in changes if not is_allowed(c)]

    kernel_now = kernel_status(ws)
    if snap["kernel"] is not None and kernel_now is not None and kernel_now != snap["kernel"]:
        bad.append("kernel-src/ (tracked files changed)")

    if bad:
        base = repair_dir(ws) / "snapshots" / snap["tag"]
        for rel in changes:  # restore every workshop file, allowed or not
            target = ws / rel
            if rel in snap["files"]:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(base / rel, target)
            elif target.exists():
                target.unlink()
    return allowed, bad


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------

def tail_text(path: Path) -> str:
    size = path.stat().st_size
    with path.open("rb") as fh:
        fh.seek(max(0, size - LOG_SCAN_BYTES))
        return fh.read().decode("utf-8", errors="replace")


def classify(stage: str, text: str, fixes: list[dict]) -> tuple[dict | None, re.Match | None]:
    for fix in fixes:
        if stage not in fix["stages"] and "any" not in fix["stages"]:
            continue
        m = re.search(fix["match"], text, re.MULTILINE)
        if m:
            return fix, m
    return None, None


def extract_packages(text: str, pattern: str) -> list[str]:
    pkgs: list[str] = []
    for m in re.finditer(pattern, text, re.MULTILINE):
        group = m.groupdict().get("pkgs")
        if not group:
            continue
        for tok in re.split(r"[,\s]+", group):
            tok = tok.strip("()'\"")
            if tok and PKG_RE.match(tok) and not VERSION_RE.match(tok) and tok not in pkgs:
                pkgs.append(tok)
    return pkgs[:20]


def generic_signature(text: str) -> str:
    """A stable fingerprint of the last error-looking line, for 'same failure twice'."""
    lines = [ln for ln in text.splitlines() if re.search(r"(?i)error|failed|not found|cannot|unable", ln)]
    last = lines[-1] if lines else (text.splitlines() or [""])[-1]
    norm = re.sub(r"\d+", "N", last)
    norm = re.sub(r"/[\w./-]+", "/P", norm)
    return "unknown:" + hashlib.sha1(norm.strip().encode()).hexdigest()[:12]


# --------------------------------------------------------------------------
# Fix operations
# --------------------------------------------------------------------------

def op_delete_keys(ws: Path, op: dict) -> None:
    for path in sorted(ws.glob(op["file"])):
        lines = path.read_text(encoding="utf-8").split("\n")
        out, skipping = [], False
        for ln in lines:
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):", ln)
            if m:
                skipping = m.group(1) in op["keys"]
            elif ln and ln[0] not in " \t":
                skipping = False  # a column-0 comment ends the removed block
            if not skipping:
                out.append(ln)
        path.write_text("\n".join(out), encoding="utf-8")


def op_restore(ws: Path, op: dict) -> None:
    for rel in op["files"]:
        src = wslib.TEMPLATE_DIR / rel
        if not src.is_file():
            raise Stop(f"template has no {rel}")
        text = src.read_text(encoding="utf-8")
        if wslib.PLACEHOLDER_RE.search(text):
            raise Stop(f"{rel} carries placeholders in the template; it cannot be restored mechanically")
        dest = ws / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def op_fix_snapcraft(ws: Path, op: dict) -> None:
    cfg = wslib.load_config(ws)
    core = str(wslib.cfg_get(cfg, "ubuntu", "core_base"))
    arch = str(wslib.cfg_get(cfg, "toolchain", "arch", default="arm64"))
    path = ws / "sdk" / "snap" / "snapcraft" / "snapcraft.yaml"
    path.write_text(wslib.fix_snapcraft(path.read_text(encoding="utf-8"), core, arch), encoding="utf-8")


def op_add_packages(ws: Path, packages: list[str]) -> None:
    if not packages:
        raise Stop("no package names to add")
    for path in sorted((ws / ".workshop").glob("*-build/hooks/setup-base")):
        text = path.read_text(encoding="utf-8")
        m = re.search(r"(?m)^([ \t]*)# @EXTRA-PACKAGES-END[ \t]*$", text)
        if not m:
            raise Stop(f"{path.relative_to(ws)}: no '# @EXTRA-PACKAGES-END' marker; add the packages by hand and use record-fix")
        have = set(re.findall(r"(?m)^\s*([a-z0-9][a-z0-9+.-]*)\s*$", text.split("# @EXTRA-PACKAGES-BEGIN")[1].split("# @EXTRA-PACKAGES-END")[0]))
        new = [p for p in packages if p not in have]
        if not new:
            continue
        indent = m.group(1)
        block = "".join(f"{indent}{p}\n" for p in new)
        path.write_text(text[:m.start()] + block + text[m.start():], encoding="utf-8")


def apply_ops(ws: Path, fix: dict, packages: list[str]) -> None:
    for op in fix.get("ops", []):
        kind = op["op"]
        if kind == "delete-top-level-keys":
            op_delete_keys(ws, op)
        elif kind == "restore-from-template":
            op_restore(ws, op)
        elif kind == "fix-snapcraft":
            op_fix_snapcraft(ws, op)
        elif kind == "add-apt-packages":
            op_add_packages(ws, op.get("packages") or packages)
        else:
            raise Stop(f"unknown op '{kind}' in known-fixes.json")


# --------------------------------------------------------------------------
# Logging the attempts
# --------------------------------------------------------------------------

def append_log(ws: Path, text: str) -> None:
    path = ws / "REPAIR-LOG.md"
    if not path.exists():
        path.write_text(
            "# Repair log\n\n"
            "Written by the create-workshop skill. Only tooling files were changed "
            "(`.workshop/`, `sdk/`, `.gitignore`); never the kernel tree, patches, "
            "config/workshop.yaml or the kernel ref.\n\n",
            encoding="utf-8",
        )
    with path.open("a", encoding="utf-8") as fh:
        fh.write(text)


def close_pending(ws: Path, state: dict, result: str) -> None:
    pend = state.get("pending")
    if not pend:
        return
    append_log(ws, f"- Result: {result}\n\n")
    pend["result"] = result
    state["history"].append(pend)
    state["pending"] = None


# --------------------------------------------------------------------------
# Running a stage
# --------------------------------------------------------------------------

def run_command(cmd: list[str], cwd: Path, log: Path, label: str) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    with log.open("wb") as fh:
        proc = subprocess.Popen(cmd, cwd=cwd, stdout=fh, stderr=subprocess.STDOUT)
        while True:
            try:
                return proc.wait(timeout=HEARTBEAT_SECONDS)
            except subprocess.TimeoutExpired:
                mins = int((time.time() - started) / 60)
                print(f"[run_stages] {label} still running ({mins} min). log: {log}", file=sys.stderr, flush=True)


def stage_command(ws: Path, stage: str, name: str) -> list[str] | None:
    if stage == "launch":
        info = subprocess.run(["workshop", "info", name], cwd=ws, capture_output=True)
        return ["workshop", "refresh", name] if info.returncode == 0 else ["workshop", "launch", name]
    if stage == "clone":
        return ["workshop", "run", "--timeout", RUN_TIMEOUT["clone"], name, "--", "clone-kernel"]
    if stage == "deb":
        return ["workshop", "run", "--timeout", RUN_TIMEOUT["deb"], name, "--", "kernel-build-debs"]
    if stage == "snap":
        return ["workshop", "run", "--timeout", RUN_TIMEOUT["snap"], name, "--", "kernel-build-snap"]
    return None


def execute_stage(ws: Path, stage: str, state: dict) -> tuple[int, Path]:
    state["runs"] += 1
    log = repair_dir(ws) / "logs" / f"{stage}-{state['runs']}.log"
    if stage in ("check", "deps"):
        f = check_workshop.run_checks(ws, kernel_src=(stage == "deps"))
        lines = [f"{e['code']}: {e['message']} [{e['file']}]" for e in f.errors]
        lines += [f"warning {w['code']}: {w['message']}" for w in f.warnings]
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return (1 if f.errors else 0), log
    cmd = stage_command(ws, stage, workshop_name(ws))
    print(f"[run_stages] {stage}: {' '.join(cmd)}", file=sys.stderr, flush=True)
    return run_command(cmd, ws, log, stage), log


def hint(command: str, ws: Path) -> str:
    """A copy-pasteable command line that works from any directory."""
    return f"python3 {Path(__file__).resolve()} {command} --workshop {ws}"


def budget(state: dict) -> tuple[int, int]:
    return state["attempts_used"], state["max_attempts"] - state["attempts_used"]


def tail(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()[-TAIL_LINES:]


def cmd_run(args: argparse.Namespace) -> dict:
    ws = Path(args.workshop).resolve()
    if not (ws / "config" / "workshop.yaml").is_file():
        raise Stop(f"{ws} is not a workshop (config/workshop.yaml missing)")
    state = load_state(ws)
    fixes = load_fixes()
    wanted = [s for s in (args.stages.split(",") if args.stages else STAGES)]
    for s in wanted:
        if s not in STAGES:
            raise Stop(f"unknown stage '{s}' (use {', '.join(STAGES)})")

    for stage in [s for s in STAGES if s in wanted]:
        if state["stage_ok"].get(stage) and not args.force:
            continue
        code, log = execute_stage(ws, stage, state)
        if code == 0:
            state["stage_ok"][stage] = True
            state["last_failure"].pop(stage, None)
            unverified = state.setdefault("unverified", [])
            if stage == "deps":
                skipped = "kernel-deps-skipped" in log.read_text(encoding="utf-8", errors="replace")
                if skipped and "deps" not in unverified:
                    unverified.append("deps")
                    print("[run_stages] deps: PASSED WITHOUT CHECKING (no kernel control stub found); report it as unverified", file=sys.stderr, flush=True)
                elif not skipped and "deps" in unverified:
                    unverified.remove("deps")
            close_pending(ws, state, f"stage `{stage}` passed.")
            save_state(ws, state)
            print(f"[run_stages] {stage}: ok", file=sys.stderr, flush=True)
            continue

        state["stage_ok"][stage] = False
        # Snapshot AFTER the failure, so build leftovers are not mistaken for an edit.
        snap = snapshot(ws, f"fail-{state['runs']}")
        for old in (repair_dir(ws) / "snapshots").glob("fail-*"):
            if old.name != snap["tag"]:
                shutil.rmtree(old, ignore_errors=True)
        state["snapshot"] = snap["tag"]
        state["kernel_status_at_snapshot"] = snap["kernel"]
        text = tail_text(log)
        fix, match = classify(stage, text, fixes)
        signature = fix["id"] if fix else generic_signature(text)
        cls = fix["class"] if fix else "unknown"
        used, left = budget(state)
        result = {
            "stage": stage, "ok": False, "exit_code": code,
            "log": log.relative_to(ws).as_posix(), "class": cls, "signature": signature,
            "fix": fix["id"] if fix and fix.get("ops") else None,
            "explain": fix["explain"] if fix else None,
            "attempts_used": used, "attempts_left": left,
            "log_tail": tail(log),
        }

        repeated = state["last_failure"].get(stage) == signature and state.get("pending") is not None
        state["last_failure"][stage] = signature
        close_pending(ws, state, f"stage `{stage}` failed again: `{signature}`." if repeated else f"stage `{stage}` still failing: `{signature}`.")

        if cls in ("environment", "kernel"):
            result.update(verdict="stop", stop_reason="environment" if cls == "environment" else "kernel-or-patch",
                          next="Report to the user. This is not a tooling problem; do not edit the kernel tree or patches.")
        elif cls == "wait":
            result.update(verdict="wait", next="Wait for the pending workshop change (`workshop changes`), then run this command again. Do not relaunch.")
        elif repeated:
            result.update(verdict="stop", stop_reason="repeated-failure",
                          next="The same failure came back after a repair. Stop and write the escalation report.")
        elif left <= 0:
            result.update(verdict="stop", stop_reason="attempts-exhausted",
                          next=f"{state['max_attempts']} repair iterations used. Stop and write the escalation report.")
        elif fix and fix.get("ops"):
            pk = extract_packages(text, fix["match"]) if any(o["op"] == "add-apt-packages" and not o.get("packages") for o in fix["ops"]) else []
            extra = f" --packages {','.join(pk)}" if pk else ""
            result.update(verdict="fix-available",
                          next=f"{hint('apply-fix', ws)} --fix {fix['id']}{extra}")
        else:
            result.update(verdict="diagnose",
                          next="Read the log, find a TOOLING cause (hooks, sdk/ scripts, packages), edit only .workshop/ or sdk/, "
                               f"then run: {hint('record-fix', ws)} --note '<cause and change>'")
        save_state(ws, state)
        return result

    save_state(ws, state)
    return {"ok": True, "verdict": "continue", "stages": state["stage_ok"],
            "unverified": state.get("unverified", []),
            "attempts_used": state["attempts_used"], "attempts_left": budget(state)[1]}


# --------------------------------------------------------------------------
# apply-fix / record-fix
# --------------------------------------------------------------------------

def restart_from(ws: Path, state: dict, stage: str) -> None:
    hit = False
    for s in STAGES:
        hit = hit or s == stage
        if not hit:
            continue
        # The clone survives a relaunch: kernel-src is on the host, not in the container.
        if s == "clone" and stage != "clone" and (ws / "kernel-src" / "debian" / "rules").is_file():
            continue
        state["stage_ok"][s] = False


def begin_repair(ws: Path, state: dict) -> None:
    used, left = budget(state)
    if left <= 0:
        raise Stop(f"repair budget exhausted ({state['max_attempts']} iterations): stop and write the escalation report")
    if state.get("pending") is not None:
        raise Stop("the previous repair has not been tested yet: run `run` first")


def cmd_apply_fix(args: argparse.Namespace) -> dict:
    ws = Path(args.workshop).resolve()
    state = load_state(ws)
    begin_repair(ws, state)
    fix = next((f for f in load_fixes() if f["id"] == args.fix and f.get("ops")), None)
    if not fix:
        raise Stop(f"no applicable known fix '{args.fix}'")
    packages = [p for p in (args.packages or "").split(",") if p]
    bad_pkgs = [p for p in packages if not PKG_RE.match(p)]
    if bad_pkgs:
        raise Stop(f"refusing odd package names: {bad_pkgs}")

    snap = snapshot(ws, f"fix-{state['attempts_used'] + 1}")
    apply_ops(ws, fix, packages)
    allowed, bad = guard(ws, snap)
    if bad:
        raise Stop(f"fix '{fix['id']}' touched forbidden paths and was reverted: {bad}")

    state["attempts_used"] += 1
    n = state["attempts_used"]
    stage = fix["restart_from"]
    restart_from(ws, state, stage)
    state["pending"] = {"attempt": n, "fix": fix["id"], "files": allowed, "at": now()}
    if not allowed:
        # Nothing changed: the template already has this fix, so the cause is elsewhere.
        close_pending(ws, state, "no file changed (the fix was already in place), so the cause is not the tooling.")
        save_state(ws, state)
        return {"applied": False, "verdict": "stop", "stop_reason": "fix-noop",
                "message": "The fix changed nothing: the workshop already has it. Treat the failure as environmental and report it.",
                "attempts_used": n, "attempts_left": budget(state)[1]}
    append_log(
        ws,
        f"## Attempt {n}: {fix['id']}\n\n- When: {now()}\n- Cause: {fix['explain']}\n"
        f"- Changed: {', '.join(f'`{p}`' for p in allowed)}\n- Restart from stage: `{stage}`\n",
    )
    save_state(ws, state)
    return {"applied": True, "files": allowed, "restart_from": stage,
            "attempts_used": n, "attempts_left": budget(state)[1],
            "next": hint("run", ws)}


def cmd_record_fix(args: argparse.Namespace) -> dict:
    ws = Path(args.workshop).resolve()
    state = load_state(ws)
    begin_repair(ws, state)
    tag = state.get("snapshot")
    if not tag or not (repair_dir(ws) / "snapshots" / tag).is_dir():
        raise Stop("no snapshot to compare with: record-fix follows a failed `run`")
    base = repair_dir(ws) / "snapshots" / tag
    snap = {"tag": tag, "files": {}, "kernel": state.get("kernel_status_at_snapshot")}
    # Rebuild the manifest from the snapshot copies so the guard compares like with like.
    for p in sorted(base.rglob("*")):
        if p.is_file():
            snap["files"][p.relative_to(base).as_posix()] = (
                hashlib.sha1(p.read_bytes()).hexdigest() + (":x" if os.access(p, os.X_OK) else "")
            )
    allowed, bad = guard(ws, snap)
    if bad:
        raise Stop(f"edit touched forbidden paths and was reverted: {bad}. Repairs may change only .workshop/, sdk/ and .gitignore.")
    if not allowed:
        raise Stop("no change found since the last failed run; edit a tooling file first")

    state["attempts_used"] += 1
    n = state["attempts_used"]
    needs_relaunch = any(p.startswith(".workshop/") for p in allowed)
    failed = next((s for s in STAGES if state["stage_ok"].get(s) is False), "deb")
    stage = "launch" if needs_relaunch else failed
    restart_from(ws, state, stage)
    state["pending"] = {"attempt": n, "fix": "manual", "files": allowed, "note": args.note, "at": now()}
    append_log(
        ws,
        f"## Attempt {n}: manual\n\n- When: {now()}\n- Cause and change: {args.note}\n"
        f"- Changed: {', '.join(f'`{p}`' for p in allowed)}\n- Restart from stage: `{stage}`\n",
    )
    save_state(ws, state)
    return {"recorded": True, "files": allowed, "restart_from": stage,
            "attempts_used": n, "attempts_left": budget(state)[1],
            "next": hint("run", ws)}


def cmd_status(args: argparse.Namespace) -> dict:
    ws = Path(args.workshop).resolve()
    state = load_state(ws)
    return {"stage_ok": state["stage_ok"], "attempts_used": state["attempts_used"],
            "attempts_left": budget(state)[1], "pending": state.get("pending"),
            "last_failure": state["last_failure"]}


def cmd_report(args: argparse.Namespace) -> dict:
    ws = Path(args.workshop).resolve()
    state = load_state(ws)
    def artifacts(sub: str, pattern: str) -> list[dict]:
        out = []
        for p in sorted((ws / "out" / sub).glob(pattern)):
            h = hashlib.sha256()
            with p.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            out.append({"file": p.relative_to(ws).as_posix(), "bytes": p.stat().st_size, "sha256": h.hexdigest()})
        return out

    outputs = {"debs": artifacts("deb", "*.deb"), "snaps": artifacts("snap", "*.snap")}
    return {"workshop": ws.name, "stage_ok": state["stage_ok"], "unverified": state.get("unverified", []),
            "attempts_used": state["attempts_used"], "max_attempts": state["max_attempts"],
            "history": state["history"] + ([state["pending"]] if state.get("pending") else []),
            "last_failure": state["last_failure"], "outputs": outputs,
            "repair_log": "REPAIR-LOG.md" if (ws / "REPAIR-LOG.md").exists() else None}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "apply-fix", "record-fix", "status", "report"):
        p = sub.add_parser(name)
        p.add_argument("--workshop", required=True)
        if name == "run":
            p.add_argument("--stages", default="")
            p.add_argument("--force", action="store_true")
        if name == "apply-fix":
            p.add_argument("--fix", required=True)
            p.add_argument("--packages", default="")
        if name == "record-fix":
            p.add_argument("--note", required=True)
    args = ap.parse_args()
    handlers = {"run": cmd_run, "apply-fix": cmd_apply_fix, "record-fix": cmd_record_fix,
                "status": cmd_status, "report": cmd_report}
    try:
        result = handlers[args.cmd](args)
    except Stop as exc:
        print(f"run_stages: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok", True) and result.get("verdict") != "stop" else 1


if __name__ == "__main__":
    sys.exit(main())
