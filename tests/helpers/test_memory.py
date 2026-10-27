import psutil
import pytest

from eodh_workflow.memory import available_memory_mb

MB = 1024 * 1024


@pytest.fixture
def system_free_mb():
    return psutil.virtual_memory().available / MB


def _write(root, files):
    for name, value in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    return root


def test_cgroup_v2_limit_caps_available_memory(tmp_path):
    root = _write(tmp_path, {"memory.max": str(512 * MB), "memory.current": str(200 * MB)})
    assert available_memory_mb(root) == pytest.approx(312)


def test_cgroup_v1_limit_caps_available_memory(tmp_path):
    root = _write(
        tmp_path,
        {"memory/memory.limit_in_bytes": str(512 * MB), "memory/memory.usage_in_bytes": str(100 * MB)},
    )
    assert available_memory_mb(root) == pytest.approx(412)


@pytest.mark.parametrize(
    "files",
    [
        {},  # not in a container
        {"memory.max": "max", "memory.current": str(100 * MB)},  # cgroup v2, no limit
        {"memory/memory.limit_in_bytes": str(2**63 - 4096), "memory/memory.usage_in_bytes": "0"},  # v1, no limit
    ],
)
def test_no_cgroup_limit_uses_system_free_memory(tmp_path, files, system_free_mb):
    root = _write(tmp_path, files)
    assert available_memory_mb(root) == pytest.approx(system_free_mb, rel=0.05)


def test_usage_over_limit_gives_zero(tmp_path):
    root = _write(tmp_path, {"memory.max": str(100 * MB), "memory.current": str(150 * MB)})
    assert available_memory_mb(root) == 0
