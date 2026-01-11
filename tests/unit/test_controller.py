"""Unit tests for helicopter_parent.controller module."""

import os
import sys
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import Mock, MagicMock, mock_open, call
import pytest

from helicopter_parent.controller import (
    DebugController,
    PR_SET_PTRACER_BINARY,
)


class TestDebugControllerInit:
    """Tests for DebugController initialization."""

    def test_init_with_script_only(self):
        """Test initialization with target script only."""
        controller = DebugController("test_script.py")
        assert controller.target_script == "test_script.py"
        assert controller.target_args == []
        assert controller.target_process is None
        assert controller.running is True

    def test_init_with_script_and_args(self):
        """Test initialization with target script and arguments."""
        controller = DebugController("test_script.py", ["arg1", "arg2"])
        assert controller.target_script == "test_script.py"
        assert controller.target_args == ["arg1", "arg2"]
        assert controller.target_process is None
        assert controller.running is True


class TestCreatePipes:
    """Tests for pipe creation."""

    def test_create_pipes(self, mock_pipe_dir, monkeypatch):
        """Test pipe creation with correct permissions."""
        mkdir_mock = Mock()
        mkfifo_mock = Mock()
        unlink_mock = Mock()

        monkeypatch.setattr(Path, "mkdir", mkdir_mock)
        monkeypatch.setattr(os, "mkfifo", mkfifo_mock)
        monkeypatch.setattr(Path, "unlink", unlink_mock)

        controller = DebugController("test.py")
        controller.create_pipes()

        mkdir_mock.assert_called_with(exist_ok=True, mode=0o700)

        assert mkfifo_mock.call_count == 2
        mkfifo_mock.assert_has_calls(
            [
                call(mock_pipe_dir / "control", mode=0o600),
                call(mock_pipe_dir / "response", mode=0o600),
            ]
        )

        assert unlink_mock.call_count == 2


class TestStartTargetProcess:
    """Tests for target process launching."""

    def test_start_target_process_no_args(self, mock_subprocess_popen):
        """Test starting target process without arguments."""
        controller = DebugController("target.py")
        controller.start_target_process()

        mock_subprocess_popen.assert_called_once_with(
            [sys.executable, "target.py"], text=True, bufsize=1
        )
        assert controller.target_process is not None
        assert controller.target_process.pid == 12345

    def test_start_target_process_with_args(self, mock_subprocess_popen):
        """Test starting target process with arguments."""
        controller = DebugController("target.py", ["--verbose", "--debug"])
        controller.start_target_process()

        mock_subprocess_popen.assert_called_once_with(
            [sys.executable, "target.py", "--verbose", "--debug"],
            text=True,
            bufsize=1,
        )


class TestSendResponse:
    """Tests for sending responses to client."""

    def test_send_response_success(self, mock_pipe_dir, monkeypatch):
        """Test successful response sending."""
        open_mock = Mock(return_value=42)
        write_mock = Mock(return_value=10)
        close_mock = Mock()

        monkeypatch.setattr(os, "open", open_mock)
        monkeypatch.setattr(os, "write", write_mock)
        monkeypatch.setattr(os, "close", close_mock)

        controller = DebugController("test.py")
        controller._send_response("TEST MESSAGE")

        # Verify non-blocking open
        open_mock.assert_called_once_with(
            mock_pipe_dir / "response", os.O_WRONLY | os.O_NONBLOCK
        )

        # Verify message written with newline
        write_mock.assert_called_once_with(42, b"TEST MESSAGE\n")

        # Verify fd closed
        close_mock.assert_called_once_with(42)

    def test_send_response_no_client_oserror(self, mock_pipe_dir, monkeypatch):
        """Test graceful handling when no client connected (OSError)."""
        open_mock = Mock(side_effect=OSError("No client"))
        monkeypatch.setattr(os, "open", open_mock)

        controller = DebugController("test.py")
        # Should not raise exception
        controller._send_response("TEST MESSAGE")


class TestCreatePrctlScript:
    """Tests for prctl script creation."""

    def test_create_prctl_script(self, mock_pipe_dir, monkeypatch):
        """Test creation of prctl script with correct content."""
        mock_file = MagicMock()
        mock_file.name = "/tmp/test_script.py"

        mock_named_temp = Mock(return_value=mock_file)
        mock_named_temp.__enter__ = Mock(return_value=mock_file)
        mock_named_temp.__exit__ = Mock(return_value=False)
        mock_file.__enter__ = Mock(return_value=mock_file)
        mock_file.__exit__ = Mock(return_value=False)

        monkeypatch.setattr(
            tempfile, "NamedTemporaryFile", Mock(return_value=mock_file)
        )

        controller = DebugController("test.py")
        result = controller._create_prctl_script(67890)

        # Verify temp file created in PIPE_DIR
        tempfile.NamedTemporaryFile.assert_called_once_with(
            mode="w", suffix=".py", delete=False, dir=mock_pipe_dir
        )

        # Verify script content used in write
        script_content = mock_file.write.call_args[0][0]
        assert str(PR_SET_PTRACER_BINARY) in script_content
        assert "67890" in script_content
        assert "_heliparent_ctypes" in script_content
        assert "prctl" in script_content
        assert "del _heliparent_ctypes" in script_content

        # Verify path returned
        assert result == Path("/tmp/test_script.py")


class TestGrantPtracePermission:
    """Tests for granting ptrace permission."""

    def test_grant_permission_success(
        self, mock_pipe_dir, mock_subprocess_popen, mock_sys_remote_exec, monkeypatch
    ):
        """Test successful permission granting."""
        sleep_mock = Mock()
        monkeypatch.setattr("time.sleep", sleep_mock)

        # Mock _create_prctl_script
        script_path = mock_pipe_dir / "test_script.py"
        create_script_mock = Mock(return_value=script_path)

        controller = DebugController("test.py")
        controller.start_target_process()
        controller._create_prctl_script = create_script_mock

        result = controller.grant_ptrace_permission(67890)

        assert result is True
        create_script_mock.assert_called_once_with(67890)
        mock_sys_remote_exec.assert_called_once_with(12345, str(script_path))
        sleep_mock.assert_called_once()

    def test_grant_permission_no_target_process(self):
        """Test permission grant fails when no target process."""
        controller = DebugController("test.py")
        # Don't start target process
        result = controller.grant_ptrace_permission(67890)

        assert result is False

    def test_grant_permission_target_exited(self, mock_subprocess_popen):
        """Test permission grant fails when target has exited."""
        controller = DebugController("test.py")
        controller.start_target_process()

        # Mock process as exited
        controller.target_process.poll.return_value = 1

        result = controller.grant_ptrace_permission(67890)

        assert result is False

    def test_grant_permission_exception(
        self, mock_pipe_dir, mock_subprocess_popen, mock_sys_remote_exec, monkeypatch
    ):
        """Test permission grant handles exceptions."""
        mock_sys_remote_exec.side_effect = RuntimeError("Remote exec failed")

        script_path = mock_pipe_dir / "test_script.py"
        create_script_mock = Mock(return_value=script_path)

        controller = DebugController("test.py")
        controller.start_target_process()
        controller._create_prctl_script = create_script_mock

        result = controller.grant_ptrace_permission(67890)

        assert result is False


class TestListenForCommands:
    """Tests for command listening."""

    @pytest.fixture(autouse=True)
    def patch_send_response(self, mocker):
        """Setup mock for controller._send_response that stops further iterations"""

        # use different name for instance param to avoid confusion with test class's self
        def side_effect_stop_running(controller, message):
            controller.running = False

        mocked = mocker.patch(
            "tests.unit.test_controller.DebugController._send_response", autospec=True
        )
        mocked.side_effect = side_effect_stop_running

    def test_listen_get_target_pid(
        self, mock_pipe_dir, mock_subprocess_popen, monkeypatch
    ):
        """Test GET_TARGET_PID command handling."""
        # Mock pipe reading
        mock_pipe = MagicMock()
        mock_pipe.readline.side_effect = ["get_target_pid\n", ""]
        # the listening tests have to be told to exit or they'll hang
        # mock_pipe.readline.side_effect.append("terminate\n")
        mock_open_func = mock_open()
        mock_open_func.return_value.__enter__.return_value = mock_pipe

        controller = DebugController("test.py")
        controller.start_target_process()

        monkeypatch.setattr("builtins.open", mock_open_func)

        # Run one iteration
        controller.listen_for_commands()

        # Verify response sent
        controller._send_response.assert_called_with(controller, "target_pid 12345")

    def test_listen_grant_access_success(
        self, mock_pipe_dir, mock_subprocess_popen, monkeypatch
    ):
        """Test GRANT_ACCESS command with successful permission grant."""
        mock_pipe = MagicMock()
        mock_pipe.readline.side_effect = ["grant_access 67890\n", ""]

        mock_open_func = mock_open()
        mock_open_func.return_value.__enter__.return_value = mock_pipe

        grant_permission_mock = Mock(return_value=True)

        controller = DebugController("test.py")
        controller.start_target_process()
        controller.grant_ptrace_permission = grant_permission_mock

        monkeypatch.setattr("builtins.open", mock_open_func)

        controller.listen_for_commands()

        grant_permission_mock.assert_called_once_with(67890)
        controller._send_response.assert_called_with(controller, "ready")

    def test_listen_grant_access_failure(
        self, mock_pipe_dir, mock_subprocess_popen, monkeypatch
    ):
        """Test GRANT_ACCESS command with failed permission grant."""
        mock_pipe = MagicMock()
        mock_pipe.readline.side_effect = ["grant_access 67890\n", ""]

        mock_open_func = mock_open()
        mock_open_func.return_value.__enter__.return_value = mock_pipe

        grant_permission_mock = Mock(return_value=False)

        controller = DebugController("test.py")
        controller.start_target_process()
        controller.grant_ptrace_permission = grant_permission_mock

        monkeypatch.setattr("builtins.open", mock_open_func)

        controller.listen_for_commands()

        grant_permission_mock.assert_called_once_with(67890)
        controller._send_response.assert_called_with(
            controller, "error : Failed to grant permission"
        )

    def test_listen_grant_access_invalid_pid(
        self, mock_pipe_dir, mock_subprocess_popen, monkeypatch
    ):
        """Test GRANT_ACCESS command with invalid PID."""
        mock_pipe = MagicMock()
        mock_pipe.readline.side_effect = ["grant_access notanumber\n", ""]

        mock_open_func = mock_open()
        mock_open_func.return_value.__enter__.return_value = mock_pipe

        controller = DebugController("test.py")
        controller.start_target_process()

        monkeypatch.setattr("builtins.open", mock_open_func)

        controller.listen_for_commands()

        controller._send_response.assert_called_with(controller, "error : Invalid PID")

    def test_listen_terminate_command(
        self, mock_pipe_dir, mock_subprocess_popen, monkeypatch
    ):
        """Test TERMINATE command."""
        mock_pipe = MagicMock()
        mock_pipe.readline.return_value = "terminate\n"

        mock_open_func = mock_open()
        mock_open_func.return_value.__enter__.return_value = mock_pipe
        monkeypatch.setattr("builtins.open", mock_open_func)

        controller = DebugController("test.py")
        controller.run()
        controller.target_process.terminate.assert_called_once()

    def test_listen_unknown_command(
        self, mock_pipe_dir, mock_subprocess_popen, monkeypatch
    ):
        """Test unknown command handling."""
        mock_pipe = MagicMock()
        mock_pipe.readline.side_effect = ["unknown_command arg1\n", ""]

        mock_open_func = mock_open()
        mock_open_func.return_value.__enter__.return_value = mock_pipe

        controller = DebugController("test.py")
        controller.start_target_process()

        monkeypatch.setattr("builtins.open", mock_open_func)

        controller.listen_for_commands()

        controller._send_response.assert_called_with(
            controller, "error : Unknown command: unknown_command"
        )

    def test_listen_empty_lines_ignored(
        self, mock_pipe_dir, mock_subprocess_popen, monkeypatch
    ):
        """Test empty lines are ignored."""
        mock_pipe = MagicMock()
        mock_pipe.readline.side_effect = ["\n", "  \n", "get_target_pid\n", ""]

        mock_open_func = mock_open()
        mock_open_func.return_value.__enter__.return_value = mock_pipe

        controller = DebugController("test.py")
        controller.start_target_process()

        monkeypatch.setattr("builtins.open", mock_open_func)

        controller.listen_for_commands()

        controller._send_response.assert_called_once()

    def test_listen_client_disconnect(
        self, mock_pipe_dir, mock_subprocess_popen, monkeypatch
    ):
        """Test handling client disconnect (empty readline)."""
        mock_pipe = MagicMock()
        # First readline returns command, second returns empty (disconnect), then new connection
        mock_pipe.readline.side_effect = ["get_target_pid\n", ""]

        mock_open_func = mock_open()
        mock_open_func.return_value.__enter__.return_value = mock_pipe

        controller = DebugController("test.py")
        controller.start_target_process()

        monkeypatch.setattr("builtins.open", mock_open_func)

        # Should handle disconnect gracefully (will try to reconnect)
        controller.running = False  # Set to false to exit after first iteration
        controller.listen_for_commands()


class TestCleanup:
    """Tests for cleanup operations."""

    def test_cleanup_running_process(self, mock_subprocess_popen, monkeypatch):
        """Test cleanup terminates running target process."""
        unlink_mock = Mock()
        monkeypatch.setattr(Path, "unlink", unlink_mock)

        controller = DebugController("test.py")
        controller.start_target_process()

        assert controller.running is True
        controller.cleanup()

        assert controller.running is False

        controller.target_process.terminate.assert_called_once()
        controller.target_process.wait.assert_called_once()

        assert unlink_mock.call_count == 2

    def test_cleanup_process_timeout(self, mock_subprocess_popen, monkeypatch):
        """Test cleanup kills process on timeout."""
        unlink_mock = Mock()
        monkeypatch.setattr(Path, "unlink", unlink_mock)

        controller = DebugController("test.py")
        controller.start_target_process()

        controller.target_process.wait.side_effect = subprocess.TimeoutExpired("cmd", 2)

        controller.cleanup()

        controller.target_process.terminate.assert_called_once()
        controller.target_process.kill.assert_called_once()

    def test_cleanup_no_process(self, monkeypatch):
        """Test cleanup works when no target process."""
        unlink_mock = Mock()
        monkeypatch.setattr(Path, "unlink", unlink_mock)

        controller = DebugController("test.py")
        # Don't start process

        controller.cleanup()

        assert controller.running is False
        assert unlink_mock.call_count == 2
