"""End-to-end tests for helicopter-parent system.

These tests run the full system with real processes, real pipes, and real
sys.remote_exec(). Only pdb.attach() is mocked since it's interactive.
"""

import os
import sys
import time
import signal
import threading
from pathlib import Path
from unittest.mock import Mock, patch
import pytest

from helicopter_parent.controller import DebugController, Command, Response
from helicopter_parent.client import DebugClient


class TestFullSystem:
    """End-to-end tests with real processes and communication."""

    # @pytest.fixture
    # def temp_pipe_dir_e2e(self, tmp_path):
    #     """Create a unique temporary pipe directory for each test."""
    #     pipe_dir = tmp_path / "heliparent_debug"
    #     pipe_dir.mkdir(mode=0o700)
    #     return pipe_dir

    # @pytest.fixture
    # def patch_pipe_paths(self, monkeypatch, temp_pipe_dir_e2e):
    #     """Patch pipe paths to use temporary directory."""
    #     from helicopter_parent import controller, client

    #     monkeypatch.setattr(controller, "PIPE_DIR", temp_pipe_dir_e2e)
    #     monkeypatch.setattr(controller, "CONTROL_PIPE", temp_pipe_dir_e2e / "control")
    #     monkeypatch.setattr(controller, "RESPONSE_PIPE", temp_pipe_dir_e2e / "response")

    #     # Also patch client's reference to controller pipes
    #     yield temp_pipe_dir_e2e



    def test_controller_starts_and_stops_target(
        self, simple_target_script, mock_pipe_dir
    ):
        """Test controller can start and stop target process."""
        controller = DebugController(simple_target_script)

        # Create pipes
        controller.create_pipes()
        assert (mock_pipe_dir / "control").exists()
        assert (mock_pipe_dir / "response").exists()

        # Start target
        controller.start_target_process()
        assert controller.target_process is not None
        assert controller.target_process.poll() is None  # Still running

        target_pid = controller.target_process.pid

        # Give it a moment to start
        time.sleep(0.2)

        # Verify process is actually running
        try:
            os.kill(target_pid, 0)  # Signal 0 just checks if process exists
        except OSError:
            pytest.fail("Target process not running")

        # Cleanup
        controller.cleanup()

        # Verify process terminated
        time.sleep(0.2)
        with pytest.raises(OSError):
            os.kill(target_pid, 0)

    @pytest.mark.flaky(retries=5)
    @pytest.mark.timeout(3)
    def test_client_can_get_target_pid(
        self, simple_target_script, mock_pipe_dir, monkeypatch
    ):
        """Test client can connect and get target PID from controller."""
        controller = DebugController(simple_target_script)
        controller.create_pipes()
        controller.start_target_process()

        expected_pid = controller.target_process.pid

        # Run controller in background thread
        controller_thread = threading.Thread(
            target=controller.listen_for_commands, daemon=True
        )
        controller_thread.start()

        # Give controller time to start listening
        time.sleep(0.5)

        try:
            # Create client and get PID
            client = DebugClient()
            received_pid = client.get_target_pid()

            assert received_pid == expected_pid

        finally:
            # Send terminate to stop controller
            client.send_command(Command.TERMINATE)
            controller_thread.join(timeout=2.0)
            controller.cleanup()

    def test_full_permission_grant_flow(
        self, simple_target_script, mock_pipe_dir, monkeypatch
    ):
        """Test full permission grant flow with real sys.remote_exec."""
        controller = DebugController(simple_target_script)
        controller.create_pipes()
        controller.start_target_process()

        target_pid = controller.target_process.pid
        client_pid = os.getpid()

        # Give target process time to actually start the interpreter
        # sys.remote_exec requires the interpreter to be running
        time.sleep(0.2)

        # Grant permission using real sys.remote_exec
        result = controller.grant_ptrace_permission(client_pid)

        assert result is True

        # The permission was granted - we can't easily verify the prctl call worked
        # without actually trying to ptrace, but we can verify no errors occurred
        assert controller.target_process.poll() is None  # Target still running

        # Cleanup
        controller.cleanup()
    
    @pytest.mark.flaky(retries=5)
    @pytest.mark.timeout(10)
    def test_full_debugging_session_without_attach(
        self, simple_target_script, mock_pipe_dir, monkeypatch
    ):
        """Test complete debugging session flow, mocking only pdb.attach."""
        # Mock pdb.attach since it's interactive
        pdb_attach_mock = Mock()

        controller = DebugController(simple_target_script)
        controller.create_pipes()
        controller.start_target_process()

        target_pid = controller.target_process.pid

        # Run controller in background
        controller_thread = threading.Thread(
            target=controller.listen_for_commands, daemon=True
        )
        controller_thread.start()

        time.sleep(0.2)

        try:
            # Create client
            client = DebugClient()
            client.target_pid = client.get_target_pid()

            assert client.target_pid == target_pid

            # Request and verify permission
            permission_granted = client.request_permission()
            assert permission_granted is True

            # Mock pdb.attach and simulate attach
            with patch('pdb.attach', pdb_attach_mock):
                result = client.attach_debugger()
                assert result is True

                # Verify pdb.attach was called with correct PID
                pdb_attach_mock.assert_called_once_with(target_pid)

        finally:
            # Cleanup
            client.send_command(Command.TERMINATE)
            controller_thread.join(timeout=2.0)
            controller.cleanup()

    def test_graceful_shutdown(
        self, simple_target_script, mock_pipe_dir, monkeypatch
    ):
        """Test system shuts down gracefully."""
        controller = DebugController(simple_target_script)
        controller.create_pipes()
        controller.start_target_process()

        target_pid = controller.target_process.pid

        # Run controller in background
        controller_thread = threading.Thread(
            target=controller.listen_for_commands, daemon=True
        )
        controller_thread.start()

        time.sleep(0.2)

        # Send terminate command
        client = DebugClient()
        client.send_command(Command.TERMINATE)

        # Wait for controller to stop
        controller_thread.join(timeout=2.0)

        # Cleanup
        controller.cleanup()

        # Verify target process terminated
        time.sleep(0.1)
        with pytest.raises(OSError):
            os.kill(target_pid, 0)

        # Verify pipes cleaned up
        assert not (mock_pipe_dir / "control").exists()
        assert not (mock_pipe_dir / "response").exists()

    def test_client_handles_controller_not_running(self, mock_pipe_dir):
        """Test client gracefully handles controller not running."""
        # Don't start controller
        client = DebugClient()

        # Check should fail
        result = client.check_controller_running()
        assert result is False

    def test_error_handling_invalid_command(
        self, simple_target_script, mock_pipe_dir, capsys
    ):
        """Test controller handles invalid commands gracefully."""
        controller = DebugController(simple_target_script)
        controller.create_pipes()
        controller.start_target_process()

        # Run controller in background
        controller_thread = threading.Thread(
            target=controller.listen_for_commands, daemon=True
        )
        controller_thread.start()

        time.sleep(0.2)

        try:
            client = DebugClient()

            # Send invalid command
            client.send_command("INVALID_COMMAND arg1 arg2")

            # Give time for controller to process
            time.sleep(0.2)

            # Controller should have printed error message
            # We can't reliably read the pipe response due to timing,
            # but we can verify the controller didn't crash
            assert controller_thread.is_alive()

        finally:
            client.send_command(Command.TERMINATE)
            controller_thread.join(timeout=2.0)
            controller.cleanup()

        # Check that error was logged
        captured = capsys.readouterr()
        assert "Unknown command: INVALID_COMMAND" in captured.out

    def test_target_process_actually_runs(
        self, simple_target_script, mock_pipe_dir
    ):
        """Test that target process actually executes and produces output."""
        controller = DebugController(simple_target_script)
        controller.create_pipes()

        # Start target with captured output
        import subprocess
        cmd = [sys.executable, simple_target_script]
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        # Give it time to start and print
        time.sleep(0.2)

        # Terminate
        process.terminate()
        stdout, stderr = process.communicate(timeout=2.0)

        # Verify it actually ran and printed expected output
        assert "Test target started" in stdout
        assert "Iteration" in stdout  # Should have printed at least one iteration
