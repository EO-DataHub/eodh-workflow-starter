import json
from pathlib import Path

import pytest

from eodh_workflow.testing import stage_item

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def input_item() -> dict:
    """One real item from the input collection. Its assets are replaced by synthetic rasters when staged."""
    return json.loads((FIXTURES / "input_item.json").read_text())


@pytest.fixture
def staged(tmp_path, input_item) -> Path:
    """A directory laid out the way ADES stage-in writes it, for `input_item`."""
    return stage_item(input_item, tmp_path / "staged")
