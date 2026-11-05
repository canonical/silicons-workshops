#!/usr/bin/env python3
"""Find which EVKs and Ubuntu kernel releases a Silicon Workshop can be built for.

Combines two public, unauthenticated sources (no credentials, no extra install):

  * Canonical Certification (C3)   https://certification.canonical.com/api/v2
      which EVKs are certified, on which Ubuntu series and kernel version.
  * Launchpad REST API             https://api.launchpad.net/devel
      whether the kernel source for a (vendor, series) exists and what its
      latest release is.

Where each vendor's kernel lives is data, not code:
../references/kernel-sources.json. A (vendor, series) that is not in that file
is never offered.

Commands (all print JSON on stdout; failures go to stderr with exit 1):

  vendors [--ssh]
      Every vendor in the table with its certified-EVK count and the state of
      each series. A vendor is worth offering only if it has certified EVKs
      AND at least one series in state "ok".

  evks --vendor V [--arch arm64]
      Certified EVKs for the vendor: model, certified series, certified kernel.

  series --vendor V [--evk "Model"] [--ssh]
      One entry per series in the table for that vendor, with the kernel ref to
      use. `certified` marks the series C3 certified the EVK on.

Series states:
  ok         kernel source reachable and a release exists          -> buildable
  no-tags    repository reachable, no release tags (tag-source rows)
  no-branch  repository reachable, pinned branch missing (commit-source rows)
  no-repo    Launchpad says the repository does not exist (HTTP 404)
  private    Launchpad says the repository is private (HTTP 401/403); re-run
             with --ssh to check it with the caller's own Launchpad SSH key
  error      the check itself failed (network, timeout); result is UNKNOWN

"error" and "private" are deliberately distinct from "no-repo": a check that
could not run must never be presented as "this release does not exist".
"""

import argparse
import concurrent.futures
import json
import os
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

C3 = "https://certification.canonical.com/api/v2"
LP_API = "https://api.launchpad.net/devel"
LP_GIT = "https://git.launchpad.net"
LP_GIT_SSH = "git+ssh://git.launchpad.net"
HTTP_TIMEOUT = 30
SSH_TIMEOUT = 60
SOURCES_FILE = Path(__file__).resolve().parent.parent / "references" / "kernel-sources.json"

# C3 'release' label -> Ubuntu series. "Core NN" is Ubuntu Core on that base.
# Labels not listed here (e.g. "18.04 LTS") are reported, never guessed.
C3_RELEASE_TO_SERIES = {
    "20.04 LTS": "focal",
    "Core 20": "focal",
    "22.04 LTS": "jammy",
    "Core 22": "jammy",
    "24.04 LTS": "noble",
    "Core 24": "noble",
    "26.04 LTS": "resolute",
    "Core 26": "resolute",
}
SERIES_ORDER = ("focal", "jammy", "noble", "resolute")


class LookupFailed(Exception):
    """A lookup could not be completed. The message is shown to the user."""


def prefer_ipv4() -> None:
    """Resolve IPv4 addresses first; IPv6 stays available as a fallback.

    urllib connects to addresses in resolver order with no fallback race. On
    networks where IPv6 is advertised but broken, the first connect then stalls
    for the whole timeout (observed: ~30s per request to api.launchpad.net)
    before IPv4 is tried. Sorting is stable and keeps every address, so
    IPv6-only hosts still work.
    """
    original = socket.getaddrinfo

    def ordered(*args, **kwargs):
        results = original(*args, **kwargs)
        return sorted(results, key=lambda r: r[0] != socket.AF_INET)

    socket.getaddrinfo = ordered


prefer_ipv4()


# --------------------------------------------------------------------------
# Table
# --------------------------------------------------------------------------


def load_sources(path: Path = SOURCES_FILE) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise LookupFailed(f"cannot read {path}: {exc}")
    vendors = data.get("vendors")
    if not isinstance(vendors, dict) or not vendors:
        raise LookupFailed(f"{path}: no vendors defined")
    for key, vendor in vendors.items():
        for field in ("display", "c3_make", "series"):
            if field not in vendor:
                raise LookupFailed(f"{path}: vendor {key!r} is missing {field!r}")
        for rx in (vendor.get("c3_model_regex"),):
            if rx:
                re.compile(rx)
        for series, row in vendor["series"].items():
            where = f"{key}/{series}"
            for field in ("repo", "tag_prefix", "flavour"):
                if field not in row:
                    raise LookupFailed(f"{path}: {where} is missing {field!r}")
            if series not in SERIES_ORDER:
                raise LookupFailed(f"{path}: {where}: unknown series {series!r}")
            if row.get("release_source", "tag") not in ("tag", "commit"):
                raise LookupFailed(f"{path}: {where}: release_source must be tag or commit")
            if row.get("release_source") == "commit" and not row.get("branch"):
                raise LookupFailed(f"{path}: {where}: release_source commit needs 'branch'")
            if row.get("exclude_tag_regex"):
                re.compile(row["exclude_tag_regex"])
            if row.get("toolchain") not in (None, "none", "clang18", "clang21"):
                raise LookupFailed(f"{path}: {where}: toolchain must be none, clang18 or clang21")
            bv = row.get("build_validated")
            if not isinstance(bv, dict) or set(bv) != {"deb", "snap"}:
                raise LookupFailed(f"{path}: {where}: build_validated must be {{\"deb\": bool, \"snap\": bool}}")
    return data


def validated(row: dict) -> dict:
    """Per-target build validation: a .deb build says nothing about the snap build."""
    bv = row.get("build_validated") or {}
    return {"deb": bool(bv.get("deb", False)), "snap": bool(bv.get("snap", False))}


# --------------------------------------------------------------------------
# Version helpers
# --------------------------------------------------------------------------


def version_key(tag: str, prefix: str = "") -> tuple:
    """Order release tags numerically: 1043.51 > 1041.49 > 998.1 > 1043.9."""
    return tuple(int(n) for n in re.findall(r"\d+", tag[len(prefix):] if tag.startswith(prefix) else tag))


def abi_prefix(kernel_version: str, flavour: str):
    """'5.15.0-1038-mtk' -> '5.15.0-1038'; None if the flavour suffix differs."""
    suffix = f"-{flavour}"
    if kernel_version and kernel_version.endswith(suffix):
        return kernel_version[: -len(suffix)]
    return None


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


def http_json(url: str):
    """Return (status, parsed_json_or_None, network_error_text)."""
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            return response.status, json.load(response), ""
    except urllib.error.HTTPError as exc:
        return exc.code, None, ""
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return None, None, str(getattr(exc, "reason", exc))


# --------------------------------------------------------------------------
# C3
# --------------------------------------------------------------------------


def c3_get_all(path: str, **query: str) -> list:
    """Follow DRF 'next' links; any failure raises LookupFailed."""
    url = f"{C3}/{path}?{urllib.parse.urlencode(query)}"
    results: list = []
    while url:
        status, data, error = http_json(url)
        if status is None:
            raise LookupFailed(f"cannot reach C3 ({error})")
        if status != 200 or not isinstance(data, dict):
            raise LookupFailed(f"C3 returned HTTP {status} for {url}")
        results.extend(data.get("results", []))
        url = data.get("next")
    return results


def c3_evks(vendor: dict, arch: str = "arm64"):
    """Certified EVKs for a vendor -> (entries, unmapped_release_labels).

    Selects on the list endpoint (make__icontains works there). The details
    endpoint silently ignores a 'make' filter and returns every record, so it
    is only ever queried by canonical_id.
    """
    configs = c3_get_all(
        "certified-configurations/",
        make__icontains=vendor["c3_make"],
        arch=arch,
        page_size="200",
    )
    if vendor.get("c3_model_regex"):
        rx = re.compile(vendor["c3_model_regex"], re.IGNORECASE)
        configs = [c for c in configs if rx.search(c["model"])]
    if not configs:
        return [], []

    kernel_by_id: dict = {}
    ids = [c["canonical_id"] for c in configs]
    for start in range(0, len(ids), 40):
        for detail in c3_get_all(
            "certified-configuration-details/",
            canonical_id__in=",".join(ids[start : start + 40]),
        ):
            kernel_by_id[detail["canonical_id"]] = detail.get("kernel_version") or ""

    best: dict = {}
    unmapped: set = set()
    for cfg in configs:
        series = C3_RELEASE_TO_SERIES.get(cfg["release"])
        if series is None:
            unmapped.add((cfg["model"], cfg["release"]))
            continue
        key = (cfg["model"], series)
        completed = cfg.get("completed") or ""
        if key not in best or completed > best[key][0]:
            best[key] = (
                completed,
                {
                    "model": cfg["model"],
                    "series": series,
                    "c3_release": cfg["release"],
                    "category": cfg["category"],
                    "level": cfg["level"],
                    "kernel_version": kernel_by_id.get(cfg["canonical_id"], ""),
                    "canonical_id": cfg["canonical_id"],
                },
            )
    entries = sorted((v[1] for v in best.values()), key=lambda e: (e["model"], SERIES_ORDER.index(e["series"])))
    return entries, sorted({f"{m} ({r})" for m, r in unmapped})


# --------------------------------------------------------------------------
# Launchpad
# --------------------------------------------------------------------------


def fetch_refs(repo: str):
    """Anonymous ref listing via the Launchpad REST API -> (state, refs, detail).

    refs is a list of (ref_path, commit_sha). 404 = no such repository,
    401/403 = private, None status = the check itself failed.
    """
    url = f"{LP_API}/{urllib.parse.quote(repo, safe='/~+')}/refs?ws.size=300"
    refs: list = []
    while url:
        status, data, error = http_json(url)
        if status is None:
            return "error", [], error or "network error"
        if status == 404:
            return "no-repo", [], "no public repository"
        if status in (401, 403):
            return "private", [], "private repository (needs Launchpad access)"
        if status != 200 or not isinstance(data, dict):
            return "error", [], f"Launchpad returned HTTP {status}"
        refs.extend((e.get("path", ""), e.get("commit_sha1", "")) for e in data.get("entries", []))
        url = data.get("next_collection_link")
    return "ok", refs, ""


def ssh_refs(repo: str):
    """Ref listing over the caller's own Launchpad SSH key (opt-in, read-only)."""
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o ConnectTimeout=15",
    }
    try:
        proc = subprocess.run(
            ["git", "ls-remote", "--heads", "--tags", f"{LP_GIT_SSH}/{repo}"],
            capture_output=True,
            text=True,
            timeout=SSH_TIMEOUT,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return "error", [], f"ssh check timed out after {SSH_TIMEOUT}s"
    if proc.returncode == 0:
        refs = []
        for line in proc.stdout.splitlines():
            sha, _, ref = line.partition("\t")
            if ref and not ref.endswith("^{}"):
                refs.append((ref, sha))
        return "ok", refs, ""
    err = (proc.stderr.strip().splitlines() or [""])[-1]
    if "not found" in err.lower():
        return "no-repo", [], "no such repository (checked with your SSH key)"
    return "error", [], err or f"git exited {proc.returncode}"


def evaluate_row(row: dict, refs: list) -> dict:
    """Pick the latest release from a repository's refs."""
    prefix = row["tag_prefix"]
    exclude = re.compile(row["exclude_tag_regex"]) if row.get("exclude_tag_regex") else None
    all_tags = []
    for path, _sha in refs:
        if not path.startswith("refs/tags/"):
            continue
        name = path[len("refs/tags/"):]
        # The character after the prefix must be a digit, so 'Ubuntu-xilinx-'
        # does not also claim 'Ubuntu-xilinx-zynqmp-5.4...'.
        if name.startswith(prefix) and name[len(prefix):][:1].isdigit():
            all_tags.append(name)

    if row.get("release_source", "tag") == "commit":
        want = f"refs/heads/{row['branch']}"
        for path, sha in refs:
            if path == want and sha:
                return {
                    "state": "ok",
                    "all_tags": all_tags,
                    "latest": {"type": "commit", "value": sha, "label": f"{row['branch']} @ {sha[:7]}"},
                }
        return {"state": "no-branch", "all_tags": all_tags, "latest": None, "detail": f"branch {row['branch']} not found"}

    candidates = [t for t in all_tags if not (exclude and exclude.search(t))]
    if not candidates:
        return {"state": "no-tags", "all_tags": all_tags, "latest": None, "detail": "no release tags"}
    top = max(candidates, key=lambda t: version_key(t, prefix))
    return {"state": "ok", "all_tags": all_tags, "latest": {"type": "tag", "value": top, "label": top}}


def probe_row(row: dict, use_ssh: bool) -> dict:
    state, refs, detail = fetch_refs(row["repo"])
    via = "https"
    if state == "private" and use_ssh:
        state, refs, detail = ssh_refs(row["repo"])
        via = "ssh"
    result = {"state": state, "detail": detail, "via": via, "all_tags": [], "latest": None}
    if state == "ok":
        result.update(evaluate_row(row, refs))
    result["repo_url"] = f"{LP_GIT_SSH if (via == 'ssh' or state == 'private') else LP_GIT}/{row['repo']}"
    return result


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def vendor_or_fail(sources: dict, key: str) -> dict:
    vendors = sources["vendors"]
    if key not in vendors:
        raise LookupFailed(f"unknown vendor {key!r}; known: {', '.join(sorted(vendors))}")
    return vendors[key]


def cmd_vendors(sources: dict, use_ssh: bool) -> list:
    vendors = sources["vendors"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        c3_jobs = {k: pool.submit(c3_evks, v) for k, v in vendors.items()}
        lp_jobs = {
            (k, s): pool.submit(probe_row, row, use_ssh)
            for k, v in vendors.items()
            for s, row in v["series"].items()
        }
        c3_results = {k: job.result() for k, job in c3_jobs.items()}  # raises LookupFailed
        lp_results = {ks: job.result() for ks, job in lp_jobs.items()}
    if all(r["state"] == "error" for r in lp_results.values()):
        raise LookupFailed("could not query Launchpad for any series (network?): " + next(iter(lp_results.values()))["detail"])

    out = []
    for key, vendor in vendors.items():
        evks, _unmapped = c3_results[key]
        series = [
            {
                "series": s,
                "state": lp_results[(key, s)]["state"],
                "buildable": lp_results[(key, s)]["state"] == "ok",
                "build_validated": validated(row),
            }
            for s, row in sorted(vendor["series"].items(), key=lambda kv: SERIES_ORDER.index(kv[0]))
        ]
        models = {e["model"] for e in evks}
        out.append(
            {
                "vendor": key,
                "display": vendor["display"],
                "certified_evks": len(models),
                "series": series,
                "offerable": bool(models) and any(s["buildable"] for s in series),
            }
        )
    return out


def cmd_evks(sources: dict, vendor_key: str, arch: str) -> dict:
    vendor = vendor_or_fail(sources, vendor_key)
    evks, unmapped = c3_evks(vendor, arch)
    for entry in evks:
        entry["series_in_table"] = entry["series"] in vendor["series"]
    return {"vendor": vendor_key, "evks": evks, "unmapped_releases": unmapped}


def choose_pin(row: dict, probe: dict, cert: dict):
    """Pin the highest respin of the certified ABI, or explain why not."""
    if row.get("release_source", "tag") == "commit":
        return None, "this repository publishes no release tags; pinned to the branch tip"
    kernel = cert.get("kernel_version") or ""
    if not kernel:
        return None, "C3 has no kernel version for this certificate"
    abi = abi_prefix(kernel, row["flavour"])
    if abi is None:
        return None, f"C3 certified kernel {kernel} has a different flavour than this series' kernel ({row['flavour']}); not pinned"
    prefix = row["tag_prefix"]
    same = [t for t in probe["all_tags"] if t.startswith(f"{prefix}{abi}.")]
    if not same:
        return None, f"C3 certified kernel {kernel}, but no release tag for it exists in this repository"
    top = max(same, key=lambda t: version_key(t, prefix))
    return {"type": "tag", "value": top, "label": top}, None


def cmd_series(sources: dict, vendor_key: str, evk: str, use_ssh: bool) -> dict:
    vendor = vendor_or_fail(sources, vendor_key)
    certified: dict = {}
    certified_series_all: set = set()
    if evk:
        evks, _ = c3_evks(vendor)
        for entry in evks:
            if entry["model"].lower() == evk.lower():
                certified[entry["series"]] = entry
                certified_series_all.add(entry["series"])

    rows = vendor["series"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(rows))) as pool:
        jobs = {s: pool.submit(probe_row, row, use_ssh) for s, row in rows.items()}
        probes = {s: job.result() for s, job in jobs.items()}
    if all(p["state"] == "error" for p in probes.values()):
        raise LookupFailed("could not query Launchpad for any series (network?): " + next(iter(probes.values()))["detail"])

    options = []
    for series, row in rows.items():
        probe = probes[series]
        cert = certified.get(series)
        pin = pin_note = None
        if cert and probe["state"] == "ok":
            pin, pin_note = choose_pin(row, probe, cert)
        ref = pin or probe["latest"]
        options.append(
            {
                "series": series,
                "certified": cert is not None,
                "certified_kernel": cert["kernel_version"] if cert else None,
                "certified_level": cert["level"] if cert else None,
                "state": probe["state"],
                "buildable": probe["state"] == "ok",
                "detail": probe["detail"],
                "repo_url": probe["repo_url"],
                "flavour": row["flavour"],
                "release_source": row.get("release_source", "tag"),
                "build_validated": validated(row),
                "toolchain": row.get("toolchain"),
                "table_note": row.get("note"),
                "pin": pin,
                "pin_note": pin_note,
                "latest": probe["latest"],
                "ref": ref,
                "ref_is_certified_pin": pin is not None,
            }
        )
    options.sort(key=lambda o: (not o["certified"], SERIES_ORDER.index(o["series"])))
    return {
        "vendor": vendor_key,
        "evk": evk or None,
        "evk_in_c3": bool(certified),
        "certified_without_source": sorted(certified_series_all - set(rows), key=SERIES_ORDER.index),
        "series": options,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    vendors = sub.add_parser("vendors", help="vendors with certified EVKs and buildable series")
    vendors.add_argument("--ssh", action="store_true", help="check private repos with your Launchpad SSH key")

    evks = sub.add_parser("evks", help="certified EVKs for a vendor")
    evks.add_argument("--vendor", required=True)
    evks.add_argument("--arch", default="arm64")

    series = sub.add_parser("series", help="series (and kernel ref) for a vendor/EVK")
    series.add_argument("--vendor", required=True)
    series.add_argument("--evk", default="", help='EVK model exactly as returned by `evks`, e.g. "Genio 510 EVK"')
    series.add_argument("--ssh", action="store_true", help="check private repos with your Launchpad SSH key")

    args = parser.parse_args()
    try:
        sources = load_sources()
        if args.command == "vendors":
            result = cmd_vendors(sources, args.ssh)
        elif args.command == "evks":
            result = cmd_evks(sources, args.vendor.lower(), args.arch)
        else:
            result = cmd_series(sources, args.vendor.lower(), args.evk, args.ssh)
    except LookupFailed as exc:
        print(f"c3_lookup: {exc}", file=sys.stderr)
        sys.exit(1)
    json.dump(result, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
