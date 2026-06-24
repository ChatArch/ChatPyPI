from pathlib import Path
import sys

import pytest
from click.testing import CliRunner


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def pytest_configure(config):
    config.addinivalue_line("markers", "mock_cli: mock CLI orchestration tests")
    config.addinivalue_line("markers", "e2e: real end-to-end CLI tests")


@pytest.fixture
def runner():
    return CliRunner()
