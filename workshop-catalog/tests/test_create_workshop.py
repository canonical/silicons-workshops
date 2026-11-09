#!/usr/bin/env python3
"""Offline tests for the create-workshop skill scripts.

No network and no real `workshop` tool: a stub `workshop` executable on PATH
plays the part of the workshop CLI. Run with:

    python3 -m unittest discover -s workshop-catalog/tests -v
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "create-workshop"
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))
import check_workshop  # noqa: E402
import wslib  # noqa: E402

FAKE_WORKSHOP = textwrap.dedent('''\
    #!/usr/bin/env python3
    """Stub of the `workshop` CLI. Behaviour is scripted through ./.fake/ files."""
    import os, re, subprocess, sys
    from pathlib import Path
    fake = Path(".fake"); fake.mkdir(exist_ok=True)
    a = sys.argv[1:]

    def pop(name):
        f = fake / name
        if not f.exists():
            return None
        lines = f.read_text().splitlines()
        if not lines:
            return None
        f.write_text("\\n".join(lines[1:]))
        return lines[0]

    if a[0] == "info":
        sys.exit(0 if (fake / "launched").exists() else 1)
    if a[0] in ("launch", "refresh"):
        d = next(Path(".workshop").glob("*.yaml")).read_text()
        if re.search(r"(?m)^(summary|description):", d):
            print('error: workshop definition: unknown fields "summary", "description"'); sys.exit(1)
        msg = pop("launch_messages")
        if msg:
            print(msg); sys.exit(1)
        (fake / "launched").write_text("1"); sys.exit(0)
    if a[0] == "run":
        action = a[-1]
        if action == "clone-kernel":
            msg = pop("clone_messages")
            if msg:
                print(msg); sys.exit(1)
            k = Path("kernel-src"); (k / "debian").mkdir(parents=True, exist_ok=True)
            (k / "debian" / "rules").write_text("#!/usr/bin/make -f\\n")
            ctrl = fake / "control"
            (k / "debian" / "control").write_text(ctrl.read_text() if ctrl.exists() else "Source: linux\\n")
            (k / "Makefile").write_text("all:\\n")
            subprocess.run(["git", "init", "-q", str(k)], check=True)
            subprocess.run(["git", "-C", str(k), "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(k), "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-qm", "x"], check=True)
            sys.exit(0)
        if action in ("kernel-build-debs", "kernel-build-snap"):
            key = "deb_messages" if action.endswith("debs") else "snap_messages"
            msg = pop(key)
            if msg:
                print(msg); sys.exit(1)
            out = Path("out") / ("deb" if action.endswith("debs") else "snap"); out.mkdir(parents=True, exist_ok=True)
            (out / ("x.deb" if action.endswith("debs") else "x.snap")).write_text("x")
            sys.exit(0)
    print("stub: unhandled", a); sys.exit(3)
''')


def run(cmd, cwd=None, env=None, check=False):
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, check=check)


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cw-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        stub = self.bin / "workshop"
        stub.write_text(FAKE_WORKSHOP)
        stub.chmod(0o755)
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}")
        self.proj = self.tmp / "project"
        self.proj.mkdir()

    def make(self, vendor="xilinx", soc="zynqmp", evk="zcu104", series="jammy",
             flavour="xilinx-zynqmp", ref_type="tag", ref="Ubuntu-xilinx-zynqmp-5.15.0-1082.86",
             extra=()):
        r = run([sys.executable, str(SCRIPTS / "instantiate.py"),
                 "--vendor", vendor, "--vendor-display", vendor.title(), "--soc", soc,
                 "--evk-board", evk, "--ubuntu-release", series,
                 "--kernel-repo", f"https://git.launchpad.net/~canonical-kernel/ubuntu/+source/linux-{flavour}/+git/{series}",
                 "--ref-type", ref_type, "--ref", ref, "--flavour", flavour, *extra], cwd=self.proj)
        return r

    def ws(self, name="xilinx-workshop") -> Path:
        return self.proj / name

    def stages(self, *args):
        r = run([sys.executable, str(SCRIPTS / "run_stages.py"), *args], cwd=self.proj, env=self.env)
        try:
            return r, json.loads(r.stdout)
        except ValueError:
            return r, {}

    def fake(self, name, *lines):
        d = self.ws() / ".fake"
        d.mkdir(exist_ok=True)
        (d / name).write_text("\n".join(lines))


class InstantiateTests(Base):
    def test_every_series_produces_a_workshop_that_passes_its_checks(self):
        for series, tool in (("focal", "none"), ("jammy", "none"), ("noble", "clang18"), ("resolute", "clang21")):
            with self.subTest(series=series):
                shutil.rmtree(self.proj)
                self.proj.mkdir()
                r = self.make(series=series, vendor="acme", soc="soc1", evk="evk1", flavour="acme")
                self.assertEqual(r.returncode, 0, r.stderr)
                out = json.loads(r.stdout)
                self.assertEqual(out["toolchain"], tool)
                ws = self.proj / "acme-workshop"
                f = check_workshop.run_checks(ws)
                self.assertEqual(f.errors, [], f.errors)
                snap = (ws / "sdk/snap/snapcraft/snapcraft.yaml").read_text()
                core = wslib.SERIES[series][2]
                self.assertIn(f"build-base: {core}", snap)
                self.assertNotRegex(snap, r"(?m)^base:")
                self.assertIn("source: ../../../kernel-src", snap)
                self.assertEqual(bool(re.search(r"(?m)^architectures:", snap)), core in ("core20", "core22"))
                self.assertEqual(bool(re.search(r"(?m)^platforms:", snap)), core in ("core24", "core26"))
                self.assertTrue((ws / f".workshop/acme-{series}.yaml").is_file())
                self.assertTrue((ws / f".workshop/{series}-build").is_dir())

    def test_definition_has_no_summary_or_description(self):
        self.assertEqual(self.make().returncode, 0)
        d = (self.ws() / ".workshop/xilinx-jammy.yaml").read_text()
        self.assertNotRegex(d, r"(?m)^(summary|description):")

    def test_jammy_installs_no_clang_or_rust(self):
        self.make()
        hook = (self.ws() / ".workshop/jammy-build/hooks/setup-base").read_text()
        self.assertIn("TOOLCHAIN_PACKAGES=(dwarfdump)", hook)
        self.assertNotIn("clang-21", hook)
        self.assertNotIn(">>> toolchain", hook)

    def test_toolchain_override_from_the_flag(self):
        r = self.make(series="noble", vendor="renesas", soc="rz", evk="rz-evk", flavour="renesas",
                      extra=("--toolchain", "clang21"))
        self.assertEqual(r.returncode, 0, r.stderr)
        hook = (self.proj / "renesas-workshop/.workshop/noble-build/hooks/setup-base").read_text()
        self.assertIn("clang-21", hook)

    def test_credentials_in_url_are_rejected(self):
        r = run([sys.executable, str(SCRIPTS / "instantiate.py"), "--vendor", "a", "--vendor-display", "A",
                 "--soc", "s", "--evk-board", "e", "--ubuntu-release", "jammy",
                 "--kernel-repo", "https://user:tok@git.example.com/x", "--ref-type", "tag", "--ref", "t",
                 "--flavour", "f"], cwd=self.proj)
        self.assertEqual(r.returncode, 1)
        self.assertIn("Credentials", r.stderr)
        self.assertFalse((self.proj / "a-workshop").exists())

    def test_second_workshop_of_a_vendor_gets_a_qualified_name(self):
        self.assertEqual(self.make().returncode, 0)
        r = self.make(soc="versal", evk="vck190")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.proj / "xilinx-versal-workshop").is_dir())
        cat = (self.proj / "catalog.yaml").read_text()
        self.assertEqual(cat.count("- name:"), 2)

    def test_commit_ref_must_be_a_full_sha(self):
        r = self.make(ref_type="commit", ref="abc123")
        self.assertEqual(r.returncode, 1)

    def test_snap_name_comes_from_the_flavour(self):
        self.make()
        self.assertRegex((self.ws() / "sdk/snap/snapcraft/snapcraft.yaml").read_text(), r"(?m)^name: linux-xilinx-zynqmp\b")

    def test_scripts_keep_their_executable_bit(self):
        self.make()
        for rel in ("sdk/common/bin/clone-kernel", "sdk/deb/bin/kernel-build-debs",
                    "sdk/snap/bin/kernel-build-snap", ".workshop/jammy-build/hooks/setup-base"):
            self.assertTrue(os.access(self.ws() / rel, os.X_OK), rel)


class ReportRegressionTests(Base):
    """Each defect from the Xilinx ZCU104 handoff report is caught and repaired."""

    def setUp(self):
        super().setUp()
        self.assertEqual(self.make().returncode, 0)

    def codes(self):
        return {e["code"] for e in check_workshop.run_checks(self.ws()).errors}

    def test_definition_summary_description(self):
        p = self.ws() / ".workshop/xilinx-jammy.yaml"
        p.write_text(p.read_text().replace("name: xilinx-jammy", "name: xilinx-jammy\nsummary: x\ndescription: |\n  y\n  z\n"))
        self.assertIn("definition-unknown-field", self.codes())

    def test_pack_project_dir_and_missing_experimental_flag(self):
        p = self.ws() / "sdk/snap/lib/pack.sh"
        p.write_text(p.read_text().replace("--enable-experimental-plugins", '--project-dir="${project}"'))
        self.assertTrue({"pack-bad-flag", "pack-experimental"} <= self.codes())

    def test_snapcraft_base_platforms_source(self):
        p = self.ws() / "sdk/snap/snapcraft/snapcraft.yaml"
        t = p.read_text().replace("build-base: core22", "base: core22")
        t = t.replace("architectures:\n  - build-on: amd64\n    build-for: arm64", "platforms:\n  arm64:")
        t = t.replace("source: ../../../kernel-src", "source: .")
        p.write_text(t)
        self.assertTrue({"snapcraft-base", "snapcraft-build-base", "snapcraft-architectures", "snapcraft-source"} <= self.codes())

    def test_fix_snapcraft_repairs_all_of_it_and_is_idempotent(self):
        p = self.ws() / "sdk/snap/snapcraft/snapcraft.yaml"
        t = p.read_text().replace("build-base: core22", "base: core22")
        t = t.replace("architectures:\n  - build-on: amd64\n    build-for: arm64", "platforms:\n  arm64:")
        p.write_text(t.replace("source: ../../../kernel-src", "source: ."))
        fixed = wslib.fix_snapcraft(p.read_text(), "core22", "arm64")
        p.write_text(fixed)
        self.assertEqual(self.codes(), set())
        self.assertEqual(wslib.fix_snapcraft(fixed, "core22", "arm64"), fixed)

    def test_fix_snapcraft_core24_uses_platforms(self):
        p = self.ws() / "sdk/snap/snapcraft/snapcraft.yaml"
        fixed = wslib.fix_snapcraft(p.read_text(), "core24", "arm64")
        self.assertRegex(fixed, r"(?m)^platforms:")
        self.assertNotRegex(fixed, r"(?m)^architectures:")
        self.assertIn("build-base: core24", fixed)

    def test_apt_lock_guard_is_in_the_hook_and_checked(self):
        hook = self.ws() / ".workshop/jammy-build/hooks/setup-base"
        self.assertEqual(self.codes(), set())
        text = hook.read_text()
        self.assertIn("DPkg::Lock::Timeout", text)
        self.assertIn("unattended-upgrades.service", text)
        # Removing the guard (the 2026-11-05 snap failure) is caught statically.
        start = text.index("# Keep background apt jobs away")
        end = text.index("# Install snapcraft.")
        hook.write_text(text[:start] + text[end:])
        self.assertIn("apt-lock-unguarded", self.codes())

    def test_deb_boot_check_has_no_pipefail_race(self):
        text = (self.ws() / "sdk/deb/lib/validate.sh").read_text()
        self.assertNotRegex(text, r"dpkg-deb -c[^\n]*\|\s*grep")

    def test_gitignore_covers_snapcraft_work_dirs(self):
        g = (self.ws() / ".gitignore").read_text()
        for d in ("parts/", "stage/", "prime/", "overlay/"):
            self.assertIn(f"sdk/snap/snapcraft/{d}", g)

    def test_clone_uses_shallow_tag_and_http11(self):
        s = (self.ws() / "sdk/common/source.sh").read_text()
        self.assertIn("--depth 1 --branch", s)
        self.assertIn("http.version=HTTP/1.1", s)

    def test_kernel_dependency_gap_is_reported(self):
        k = self.ws() / "kernel-src/debian"
        k.mkdir(parents=True)
        (k / "control").write_text("Source: linux\nBuild-Depends:\n debhelper,\n clang-18 [amd64 arm64],\n bindgen-0.65,\n rustc,\n\nPackage: x\n")
        (self.ws() / "kernel-src/rust").mkdir()
        f = check_workshop.run_checks(self.ws(), kernel_src=True)
        missing = {e["message"].split("'")[1] for e in f.errors if e["code"] == "kernel-dep-missing"}
        self.assertEqual(missing, {"clang-18", "bindgen-0.65", "rustc"})


class RepairLoopTests(Base):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.make().returncode, 0)

    def run_all(self):
        return self.stages("run", "--workshop", "xilinx-workshop")

    def test_clean_workshop_passes_every_stage(self):
        r, out = self.run_all()
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(out["verdict"], "continue")
        self.assertTrue(all(out["stages"].values()))
        self.assertEqual(out["attempts_used"], 0)

    def test_known_fix_is_applied_and_the_run_resumes(self):
        p = self.ws() / ".workshop/xilinx-jammy.yaml"
        p.write_text(p.read_text().replace("name: xilinx-jammy", "name: xilinx-jammy\nsummary: x\ndescription: |\n  y\n"))
        r, out = self.run_all()
        self.assertEqual((out["verdict"], out["fix"]), ("fix-available", "definition-unknown-fields"))
        r, out = self.stages("apply-fix", "--workshop", "xilinx-workshop", "--fix", "definition-unknown-fields")
        self.assertTrue(out["applied"])
        self.assertEqual(out["attempts_used"], 1)
        r, out = self.run_all()
        self.assertEqual(out["verdict"], "continue", out)
        log = (self.ws() / "REPAIR-LOG.md").read_text()
        self.assertIn("definition-unknown-fields", log)
        self.assertIn("Result: stage `check` passed", log)

    def test_pack_sh_regression_is_restored_from_the_template(self):
        p = self.ws() / "sdk/snap/lib/pack.sh"
        p.write_text(p.read_text().replace("--enable-experimental-plugins", "--project-dir=x"))
        r, out = self.run_all()
        self.assertEqual(out["fix"], "snapcraft-project-dir")
        r, out = self.stages("apply-fix", "--workshop", "xilinx-workshop", "--fix", "snapcraft-project-dir")
        self.assertEqual(out["files"], ["sdk/snap/lib/pack.sh"])
        r, out = self.run_all()
        self.assertEqual(out["verdict"], "continue", out)

    def test_runtime_snapcraft_error_maps_to_a_fix(self):
        self.fake("snap_messages", "pydantic: union_tag_not_found 'build_base' | 'build-base'")
        r, out = self.run_all()
        self.assertEqual((out["stage"], out["fix"]), ("snap", "snapcraft-yaml-shape"))
        self.assertTrue(out["stages_ok"] if "stages_ok" in out else True)

    def test_environment_failure_stops_without_spending_an_attempt(self):
        self.fake("clone_messages", "fatal: Could not resolve host: git.launchpad.net")
        r, out = self.run_all()
        self.assertEqual((out["verdict"], out["stop_reason"]), ("stop", "environment"))
        self.assertEqual(out["attempts_used"], 0)

    def test_kernel_compile_error_stops_and_is_never_repaired(self):
        self.fake("deb_messages", "drivers/net/foo/bar.c:120:9: error: implicit declaration of function 'x'")
        r, out = self.run_all()
        self.assertEqual((out["verdict"], out["stop_reason"]), ("stop", "kernel-or-patch"))
        self.assertEqual(out["attempts_used"], 0)
        r, out = self.stages("apply-fix", "--workshop", "xilinx-workshop", "--fix", "kernel-compile-error")
        self.assertEqual(r.returncode, 2)

    def test_dependency_gap_after_clone_is_fixed_in_extra_packages(self):
        self.fake("control", "Source: linux", "Build-Depends:", " debhelper,", " clang-18 [amd64],", " bindgen-0.65,", "")
        r, out = self.run_all()
        self.assertEqual((out["stage"], out["fix"]), ("deps", "kernel-dep-missing"))
        pkgs = out["next"].split("--packages ")[1].split(",")
        self.assertEqual(sorted(pkgs), ["bindgen-0.65", "clang-18"])
        r, out = self.stages("apply-fix", "--workshop", "xilinx-workshop", "--fix", "kernel-dep-missing",
                             "--packages", "clang-18,bindgen-0.65")
        self.assertEqual(out["restart_from"], "launch")
        hook = (self.ws() / ".workshop/jammy-build/hooks/setup-base").read_text()
        block = hook.split("# @EXTRA-PACKAGES-BEGIN")[1].split("# @EXTRA-PACKAGES-END")[0]
        self.assertIn("clang-18", block)
        self.assertIn("bindgen-0.65", block)
        r, out = self.run_all()
        self.assertEqual(out["verdict"], "continue", out)

    def test_unknown_failure_goes_to_the_agent_and_a_tooling_edit_is_accepted(self):
        self.fake("deb_messages", "ERROR: something odd in the packaging step", "")
        r, out = self.run_all()
        self.assertEqual(out["verdict"], "diagnose")
        hook = self.ws() / "sdk/deb/lib/package.sh"
        hook.write_text(hook.read_text() + "\n# tweak\n")
        r, out = self.stages("record-fix", "--workshop", "xilinx-workshop", "--note", "tweaked package.sh")
        self.assertTrue(out["recorded"], r.stderr)
        self.assertEqual(out["restart_from"], "deb")
        r, out = self.run_all()
        self.assertEqual(out["verdict"], "continue", out)

    def test_edit_outside_the_allowlist_is_refused_and_reverted(self):
        self.fake("deb_messages", "ERROR: something odd in the packaging step")
        self.run_all()
        cfg = self.ws() / "config/workshop.yaml"
        before = cfg.read_text()
        cfg.write_text(before.replace("Ubuntu-xilinx-zynqmp-5.15.0-1082.86", "Ubuntu-xilinx-zynqmp-5.15.0-1100.99"))
        r, out = self.stages("record-fix", "--workshop", "xilinx-workshop", "--note", "bump the ref")
        self.assertEqual(r.returncode, 2)
        self.assertIn("forbidden", r.stderr)
        self.assertEqual(cfg.read_text(), before)

    def test_editing_the_kernel_tree_is_refused(self):
        self.fake("deb_messages", "ERROR: something odd in the packaging step")
        self.run_all()
        (self.ws() / "kernel-src/Makefile").write_text("all:\n\techo patched\n")
        hook = self.ws() / "sdk/deb/lib/package.sh"
        hook.write_text(hook.read_text() + "\n# tweak\n")
        r, out = self.stages("record-fix", "--workshop", "xilinx-workshop", "--note", "patch the kernel")
        self.assertEqual(r.returncode, 2)
        self.assertIn("kernel-src", r.stderr)
        self.assertNotIn("# tweak", hook.read_text())

    def test_same_failure_after_a_repair_stops(self):
        self.fake("deb_messages", *(["ERROR: something odd in the packaging step"] * 4))
        self.run_all()
        hook = self.ws() / "sdk/deb/lib/package.sh"
        hook.write_text(hook.read_text() + "\n# one\n")
        self.stages("record-fix", "--workshop", "xilinx-workshop", "--note", "one")
        r, out = self.run_all()
        self.assertEqual((out["verdict"], out["stop_reason"]), ("stop", "repeated-failure"))

    def test_the_budget_is_five_repair_iterations(self):
        words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf"]
        self.fake("deb_messages", *[f"ERROR: {w} blew up" for w in words])
        r, out = self.run_all()
        for i in range(5):
            self.assertEqual(out["verdict"], "diagnose", (i, out))
            hook = self.ws() / "sdk/deb/lib/package.sh"
            hook.write_text(hook.read_text() + f"\n# try {i}\n")
            r, rec = self.stages("record-fix", "--workshop", "xilinx-workshop", "--note", f"try {i}")
            self.assertTrue(rec["recorded"], r.stderr)
            r, out = self.run_all()
        self.assertEqual((out["verdict"], out["stop_reason"]), ("stop", "attempts-exhausted"), out)
        self.assertEqual(out["attempts_used"], 5)
        hook = self.ws() / "sdk/deb/lib/package.sh"
        hook.write_text(hook.read_text() + "\n# one too many\n")
        r, _ = self.stages("record-fix", "--workshop", "xilinx-workshop", "--note", "6th")
        self.assertEqual(r.returncode, 2)
        self.assertIn("budget", r.stderr)

    def test_fix_that_changes_nothing_is_a_stop(self):
        self.fake("clone_messages", "error: RPC failed; curl 18 transfer closed", "")
        r, out = self.run_all()
        self.assertEqual(out["fix"], "clone-transfer-dropped")
        r, out = self.stages("apply-fix", "--workshop", "xilinx-workshop", "--fix", "clone-transfer-dropped")
        self.assertEqual((out["verdict"], out["stop_reason"]), ("stop", "fix-noop"))

    def test_apt_lock_failure_is_repaired_by_inserting_the_guard(self):
        hook = self.ws() / ".workshop/jammy-build/hooks/setup-base"
        text = hook.read_text()
        hook.write_text(text[:text.index("# Keep background apt jobs away")] + text[text.index("# Install snapcraft."):])
        r, out = self.run_all()
        self.assertEqual(out["stage"], "check")  # the static check sees it before any build starts
        self.assertEqual(out["fix"], "apt-lock-held")
        r, out = self.stages("apply-fix", "--workshop", "xilinx-workshop", "--fix", "apt-lock-held")
        self.assertEqual(out["files"], [".workshop/jammy-build/hooks/setup-base"])
        self.assertEqual(hook.read_text().count("DPkg::Lock::Timeout"), 2)  # comment + the setting
        r, out = self.run_all()
        self.assertEqual(out["verdict"], "continue", out)

    def test_pending_launch_is_a_wait_not_a_relaunch(self):
        self.fake("launch_messages", "error: workshop exists")
        r, out = self.run_all()
        self.assertEqual(out["verdict"], "wait")


class SourceShTests(unittest.TestCase):
    """The shallow clone path of sdk/common/source.sh against a local repo."""

    def test_shallow_tag_clone_and_checkout(self):
        tmp = Path(tempfile.mkdtemp(prefix="cw-src-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        up = tmp / "up"
        up.mkdir()
        g = lambda *a: run(["git", "-c", "user.email=a@b", "-c", "user.name=t", *a], cwd=up, check=True)  # noqa: E731
        g("init", "-q")
        (up / "debian").mkdir()
        (up / "debian/rules").write_text("x")
        g("add", "-A")
        g("commit", "-qm", "one")
        (up / "f").write_text("2")
        g("add", "-A")
        g("commit", "-qm", "two")
        g("tag", "Ubuntu-test-1.0")
        root = tmp / "ws"
        root.mkdir()
        script = (
            f'source "{SKILL}/assets/workshop-template/sdk/common/workshop.sh"; '
            f'source "{SKILL}/assets/workshop-template/sdk/common/source.sh"; '
            f'workshop_clone_source "{root}" "file://{up}" tag Ubuntu-test-1.0'
        )
        r = run(["bash", "-c", script])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(r.stdout.strip()), 40)
        depth = run(["git", "-C", str(root / "kernel-src"), "rev-list", "--count", "HEAD"]).stdout.strip()
        self.assertEqual(depth, "1")  # shallow: the history was not downloaded

    def test_failed_clone_leaves_no_partial_directory(self):
        tmp = Path(tempfile.mkdtemp(prefix="cw-src-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        script = (
            f'source "{SKILL}/assets/workshop-template/sdk/common/workshop.sh"; '
            f'source "{SKILL}/assets/workshop-template/sdk/common/source.sh"; '
            f'sleep() {{ :; }}; workshop_clone_source "{tmp}" "file:///nonexistent/repo" tag v1'
        )
        r = run(["bash", "-c", script])
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((tmp / "kernel-src").exists())


class TemplateTests(unittest.TestCase):
    def test_every_toolchain_block_is_paired_in_both_hooks(self):
        for hook in ("setup-base", "check-health"):
            text = (wslib.TEMPLATE_DIR / ".workshop/series-build/hooks" / hook).read_text()
            _, blocks = wslib.select_profile(text, "none")
            self.assertEqual(sorted(blocks), sorted(wslib.TOOLCHAINS), hook)

    def test_kernel_sources_toolchain_values_are_known(self):
        data = json.loads((SKILL / "references/kernel-sources.json").read_text())
        for vendor, v in data["vendors"].items():
            for series, row in v["series"].items():
                if "toolchain" in row:
                    self.assertIn(row["toolchain"], wslib.TOOLCHAINS, f"{vendor}/{series}")
                bv = row.get("build_validated")
                self.assertIsInstance(bv, dict, f"{vendor}/{series} build_validated must be {{deb, snap}}")
                self.assertEqual(set(bv), {"deb", "snap"})


if __name__ == "__main__":
    unittest.main()
