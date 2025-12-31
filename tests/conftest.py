"""Shared pytest fixtures for helicopter-parent tests."""

import tempfile
from pathlib import Path
import sys
from unittest.mock import Mock
from textwrap import dedent 

import pytest

@pytest.fixture
def temp_pipe_dir():
    """Create temporary directory for pipes.

    Yields:
        Path: Temporary directory path
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_pipe_dir(monkeypatch, temp_pipe_dir):
    """Monkeypatch PIPE_DIR to use temp directory.

    This fixture redirects all pipe operations to a temporary directory
    to avoid conflicts with real debugging sessions.

    Args:
        monkeypatch: pytest monkeypatch fixture
        temp_pipe_dir: Temporary directory fixture

    Yields:
        Path: Temporary pipe directory
    """
    from helicopter_parent import controller

    monkeypatch.setattr(controller, "PIPE_DIR", temp_pipe_dir)
    monkeypatch.setattr(controller, "CONTROL_PIPE", temp_pipe_dir / "control")
    monkeypatch.setattr(controller, "RESPONSE_PIPE", temp_pipe_dir / "response")
    yield temp_pipe_dir


@pytest.fixture(scope="session")
def simple_target_script(tmp_path_factory):
    """Create minimal target script for testing.

    Args:
        tmp_path: pytest temporary path fixture

    Returns:
        str: Path to the test target script
    """
    script = tmp_path_factory.mktemp("target_script") / "test_target.py"
    script.write_text(dedent("""
        import time
        print("Test target started", flush=True)
        counter = 0
        while True:
            print(f"Iteration {counter}", flush=True)
            counter += 1
            time.sleep(0.1)
        """))
    return str(script)


@pytest.fixture
def mock_sys_remote_exec(monkeypatch):
    """Mock sys.remote_exec since we can't actually use it in tests.

    Args:
        monkeypatch: pytest monkeypatch fixture

    Returns:
        Mock: The mock function that was installed
    """
    mock = Mock()
    monkeypatch.setattr(sys, "remote_exec", mock)
    return mock


@pytest.fixture
def mock_subprocess_popen(monkeypatch):
    """Mock subprocess.Popen for controller tests.

    Returns:
        Mock: Mock Popen class with a configured mock process
    """
    import subprocess

    mock_process = Mock()
    mock_process.pid = 12345
    mock_process.poll.return_value = None  # Process is running
    mock_process.wait.return_value = 0
    mock_process.terminate.return_value = None
    mock_process.kill.return_value = None

    mock_popen = Mock(return_value=mock_process)
    monkeypatch.setattr(subprocess, "Popen", mock_popen)

    return mock_popen
