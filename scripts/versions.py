"""
Keep the workflow's version the same in pyproject.toml, the CWL `s:softwareVersion`, and the
CWL `dockerPull` tag.

    python scripts/versions.py check [--tag vX.Y.Z]   fail if the versions (and the git tag) differ
    python scripts/versions.py bump X.Y.Z             set all three
    python scripts/versions.py image                  print the dockerPull image
    python scripts/versions.py workflow-id            print the CWL Workflow id
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
CWL_FILES = sorted((ROOT / "cwl").glob("*.cwl"))

PYPROJECT_VERSION = re.compile(r'^version = "([^"]+)"', re.MULTILINE)
SOFTWARE_VERSION = re.compile(r"^s:softwareVersion: *(\S+)", re.MULTILINE)
DOCKER_PULL = re.compile(r"^( *dockerPull: *)(\S+):([^\s:]+)$", re.MULTILINE)
WORKFLOW_ID = re.compile(r"class: Workflow\s*\n\s*id: *(\S+)")
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def versions() -> dict:
    found = {"pyproject.toml version": PYPROJECT_VERSION.search(PYPROJECT.read_text()).group(1)}
    for cwl in CWL_FILES:
        text = cwl.read_text()
        name = cwl.relative_to(ROOT)
        found[f"{name} s:softwareVersion"] = SOFTWARE_VERSION.search(text).group(1)
        for match in DOCKER_PULL.finditer(text):
            found[f"{name} dockerPull tag ({match.group(2)})"] = match.group(3)
    return found


def check(tag=None) -> int:
    found = versions()
    if tag is not None:
        found["git tag"] = tag.removeprefix("v")
    for name, value in found.items():
        print(f"{value:>12}  {name}")
    if len(set(found.values())) != 1:
        print("Versions differ. Run `make bump VERSION=x.y.z`.", file=sys.stderr)
        return 1
    return 0


def bump(version: str) -> int:
    if not SEMVER.match(version):
        print(f"{version!r} is not x.y.z", file=sys.stderr)
        return 1
    PYPROJECT.write_text(PYPROJECT_VERSION.sub(f'version = "{version}"', PYPROJECT.read_text(), count=1))
    for cwl in CWL_FILES:
        text = SOFTWARE_VERSION.sub(f"s:softwareVersion: {version}", cwl.read_text())
        cwl.write_text(DOCKER_PULL.sub(rf"\g<1>\g<2>:{version}", text))
    return check()


def main(argv) -> int:
    if argv[:1] == ["check"] and len(argv) in (1, 3) and argv[1:2] in ([], ["--tag"]):
        return check(argv[2] if len(argv) == 3 else None)
    if argv[:1] == ["bump"] and len(argv) == 2:
        return bump(argv[1])
    if argv == ["image"]:
        print(DOCKER_PULL.search(CWL_FILES[0].read_text()).group(2) + ":" + versions()["pyproject.toml version"])
        return 0
    if argv == ["workflow-id"]:
        print(WORKFLOW_ID.search(CWL_FILES[0].read_text()).group(1))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
