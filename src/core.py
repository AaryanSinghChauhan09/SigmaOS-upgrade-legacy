"""Upgrade planner for SigmaOS-upgrade / upgrade-info / upgrade-legacy (inspired by mintupgrade).

Principles: plan before apply, fail-fast requirement gates, deterministic
risk scoring. The pure plan/validate layer is fully tested; the thin
execute layer only runs commands after explicit --yes confirmation.
"""
import argparse, json, sys

ENGINE = {
    "name": "sigma-upgrade",
    "summary": "Plan and risk-assess distribution upgrades",
    "language": "python",
    "verbs": ["check-requirements", "plan", "risks", "apply-plan"],
    "principles": ["Plan Before Apply", "Fail-Fast", "Defensive Programming",
                   "Separation of Concerns", "KISS", "Deterministic Testing"],
}

cli_doc = """\
$ sigma-upgrade check-requirements --facts system.json
$ sigma-upgrade plan --packages packages.json --target 22.3
$ sigma-upgrade risks --packages packages.json
$ sigma-upgrade apply-plan --plan upgrade-plan.json           # dry-run
$ sigma-upgrade apply-plan --plan upgrade-plan.json --yes     # execute
"""

MIN_RAM_MB = 2048
MIN_FREE_GB = 5


class UpgradeError(Exception):
    pass


def parse_version(v):
    """Loose version -> comparable int tuple ('1:5.9rc2-3' -> (1,5,9,2,3))."""
    parts = []
    for chunk in str(v).replace("-", ".").replace(":", ".").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def check_requirements(facts):
    """Return list of failure strings against a fake/injected system dict."""
    fails = []
    if facts.get("ram_mb", 0) < MIN_RAM_MB:
        fails.append(f"need >= {MIN_RAM_MB} MB RAM, have {facts.get('ram_mb', 0)} MB")
    if facts.get("free_gb", 0) < MIN_FREE_GB:
        fails.append(f"need >= {MIN_FREE_GB} GB free disk, have {facts.get('free_gb', 0)} GB")
    if not facts.get("network"):
        fails.append("no network connection")
    if facts.get("pkg_manager_locked"):
        fails.append("package manager is locked (another apt/dpkg is running)")
    if facts.get("on_battery") and facts.get("battery_percent", 100) < 50:
        fails.append(f"on battery with {facts.get('battery_percent')}%; plug in (need >= 50%)")
    if facts.get("eol"):
        fails.append("current release is EOL; use the upgrade-legacy flow")
    return fails


def build_plan(packages, target):
    """Build an upgrade plan from package dicts. Fail-fast on held upgrades."""
    upgrades, held_blocked, download_kb = [], [], 0
    for p in packages:
        name, cur, cand = p["name"], p.get("current", ""), p.get("candidate", "")
        if parse_version(cand) <= parse_version(cur):
            continue
        if p.get("held"):
            held_blocked.append(name)
            continue
        upgrades.append({"name": name, "current": cur, "candidate": cand,
                         "size_kb": p.get("size_kb", 100)})
        download_kb += p.get("size_kb", 100)
    if held_blocked:
        raise UpgradeError("held package(s) with upgrades pending: "
                           + ", ".join(sorted(held_blocked)))
    upgrades.sort(key=lambda u: u["name"])
    return {"target": target, "count": len(upgrades), "download_kb": download_kb,
            "packages": upgrades}


def assess_risks(packages):
    """Classify each upgradable package; return overall + per-item risks."""
    items = []
    for p in packages:
        cur, cand = p.get("current", ""), p.get("candidate", "")
        if parse_version(cand) <= parse_version(cur):
            continue
        name = p["name"]
        if name.startswith(("linux-image", "linux-headers")):
            cat, level, why = "kernel", "high", "new kernel may break boot/hardware"
        elif "nvidia" in name or name.startswith("xserver-xorg-video"):
            cat, level, why = "driver", "high", "graphics driver change may break X/Wayland"
        elif name in ("libc6", "libc-bin"):
            cat, level, why = "core-library", "high", "C library update affects every binary"
        elif parse_version(cand)[0] != parse_version(cur)[0]:
            cat, level, why = "major-bump", "medium", "major version change may alter behaviour"
        else:
            cat, level, why = "routine", "low", "minor update"
        items.append({"name": name, "category": cat, "level": level, "reason": why})
    order = {"low": 0, "medium": 1, "high": 2}
    overall = max((i["level"] for i in items), key=order.get, default="low")
    return {"level": overall, "items": items}


def build_commands(plan):
    """Pure: turn a plan dict into the exact shell commands an admin would run."""
    names = [u["name"] for u in plan["packages"]]
    cmds = ["apt-get update"]
    if names:
        cmds.append("apt-get install -y " + " ".join(names))
    cmds.append("apt-get autoremove -y")
    return cmds


def execute(commands, yes=False):
    """Thin side-effecting layer. Never called by self_test."""
    if not yes:
        raise UpgradeError("refusing to execute without --yes")
    import subprocess
    for c in commands:
        subprocess.run(c.split(), check=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=ENGINE["name"], description=ENGINE["summary"])
    sub = p.add_subparsers(dest="cmd", required=True)
    cr = sub.add_parser("check-requirements", help="gate an upgrade on system facts")
    cr.add_argument("--facts", required=True, help="JSON file with system facts")
    pl = sub.add_parser("plan", help="compute an upgrade plan")
    pl.add_argument("--packages", required=True, help="JSON file with package dicts")
    pl.add_argument("--target", required=True, help="target release, e.g. 22.3")
    rk = sub.add_parser("risks", help="classify upgrade risks")
    rk.add_argument("--packages", required=True)
    ap = sub.add_parser("apply-plan", help="dry-run (default) or execute a plan")
    ap.add_argument("--plan", required=True, help="JSON plan from `plan` verb")
    ap.add_argument("--yes", action="store_true", help="actually execute commands")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "check-requirements":
            with open(args.facts) as fh:
                facts = json.load(fh)
            fails = check_requirements(facts)
            for f in fails:
                print(f"FAIL: {f}")
            if fails:
                return 1
            print("all requirements met")
        elif args.cmd == "plan":
            with open(args.packages) as fh:
                pkgs = json.load(fh)
            print(json.dumps(build_plan(pkgs, args.target), indent=2))
        elif args.cmd == "risks":
            with open(args.packages) as fh:
                pkgs = json.load(fh)
            print(json.dumps(assess_risks(pkgs), indent=2))
        elif args.cmd == "apply-plan":
            with open(args.plan) as fh:
                plan = json.load(fh)
            cmds = build_commands(plan)
            if args.yes:
                execute(cmds, yes=True)
                print("executed")
            else:
                for c in cmds:
                    print("DRY-RUN: " + c)
        return 0
    except (UpgradeError, OSError, KeyError, json.JSONDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def self_test() -> None:
    good = {"ram_mb": 8192, "free_gb": 42, "network": True,
            "pkg_manager_locked": False, "on_battery": False, "eol": False}
    assert check_requirements(good) == []
    bad = {"ram_mb": 1024, "free_gb": 2, "network": False,
           "pkg_manager_locked": True, "on_battery": True,
           "battery_percent": 20, "eol": True}
    fails = check_requirements(bad)
    assert len(fails) == 6, fails
    assert any("RAM" in f for f in fails)
    assert any("EOL" in f for f in fails)

    pkgs = [
        {"name": "vim", "current": "2:8.2", "candidate": "2:9.0", "size_kb": 4000},
        {"name": "linux-image-6.8.0-31-generic", "current": "6.8.0-31.31",
         "candidate": "6.8.0-40.40", "size_kb": 140000},
        {"name": "nvidia-driver-535", "current": "535.129.03-1",
         "candidate": "535.154.02-1", "size_kb": 90000},
        {"name": "libc6", "current": "2.35-0ubuntu3", "candidate": "2.39-4",
         "size_kb": 13000},
        {"name": "firefox", "current": "1:1snap1", "candidate": "1:1snap1",
         "size_kb": 0},  # unchanged: excluded
    ]
    plan = build_plan(pkgs, "22.3")
    assert plan["count"] == 4
    assert plan["download_kb"] == 4000 + 140000 + 90000 + 13000
    assert plan["packages"][0]["name"] == "libc6"  # sorted
    assert "firefox" not in [u["name"] for u in plan["packages"]]

    risks = assess_risks(pkgs)
    assert risks["level"] == "high"
    by_name = {i["name"]: i for i in risks["items"]}
    assert by_name["linux-image-6.8.0-31-generic"]["category"] == "kernel"
    assert by_name["nvidia-driver-535"]["category"] == "driver"
    assert by_name["libc6"]["category"] == "core-library"
    assert by_name["vim"]["level"] == "low"

    try:
        build_plan([{"name": "bash", "current": "5.1", "candidate": "5.2",
                     "held": True}], "22.3")
    except UpgradeError:
        pass
    else:
        raise AssertionError("held package not caught")

    cmds = build_commands(plan)
    assert cmds[0] == "apt-get update"
    assert cmds[1].startswith("apt-get install -y ")
    assert "libc6" in cmds[1]
    assert parse_version("2:8.2") < parse_version("2:9.0")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
