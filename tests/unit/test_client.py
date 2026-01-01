"""Unit tests for helicopter_parent.client module."""

import os
import pdb
import select
from unittest.mock import Mock, MagicMock, mock_open, patch
import pytest

from helicopter_parent.client import DebugClient, DEFAULT_TIMEOUT
from helicopter_parent import controller


class TestDebugClientInit:
    """Tests for DebugClient initialization."""

    def test_init(self, monkeypatch):
        """Test client initialization."""
        monkeypatch.setattr(os, "getpid", lambda: 99999)

        client = DebugClient()
        assert client.running is True
        assert client.target_pid is None
        assert client.client_pid == 99999


class TestCheckControllerRunning:
    """Tests for controller running check."""

    def test_controller_running_both_pipes_exist(self, mock_pipe_dir, monkeypatch):
        """Test returns True when both pipes exist."""
        # Create mock Path objects that exist
        control_pipe_mock = Mock()
        response_pipe_mock = Mock()
        control_pipe_mock.exists.return_value = True
        response_pipe_mock.exists.return_value = True

        monkeypatch.setattr(controller, "CONTROL_PIPE", control_pipe_mock)
        monkeypatch.setattr(controller, "RESPONSE_PIPE", response_pipe_mock)

        client = DebugClient()
        result = client.check_controller_running()

        assert result is True

    def test_controller_not_running_control_pipe_missing(
        self, mock_pipe_dir, monkeypatch
    ):
        """Test returns False when control pipe missing."""
        control_pipe_mock = Mock()
        response_pipe_mock = Mock()
        control_pipe_mock.exists.return_value = False
        response_pipe_mock.exists.return_value = True

        monkeypatch.setattr(controller, "CONTROL_PIPE", control_pipe_mock)
        monkeypatch.setattr(controller, "RESPONSE_PIPE", response_pipe_mock)

        client = DebugClient()
        result = client.check_controller_running()

        assert result is False

    def test_controller_not_running_response_pipe_missing(
        self, mock_pipe_dir, monkeypatch
    ):
        """Test returns False when response pipe missing."""
        control_pipe_mock = Mock()
        response_pipe_mock = Mock()
        control_pipe_mock.exists.return_value = True
        response_pipe_mock.exists.return_value = False

        monkeypatch.setattr(controller, "CONTROL_PIPE", control_pipe_mock)
        monkeypatch.setattr(controller, "RESPONSE_PIPE", response_pipe_mock)

        client = DebugClient()
        result = client.check_controller_running()

        assert result is False


class TestSendCommand:
    """Tests for sending commands."""

    def test_send_command_success(self, mock_pipe_dir, monkeypatch):
        """Test successful command sending."""
        mock_pipe = MagicMock()
        mock_open_func = mock_open()
        mock_open_func.return_value.__enter__.return_value = mock_pipe

        monkeypatch.setattr("builtins.open", mock_open_func)

        client = DebugClient()
        result = client.send_command("test_command")

        assert result is True
        mock_pipe.write.assert_called_once_with("test_command\n")
        mock_pipe.flush.assert_called_once()

    def test_send_command_exception(self, mock_pipe_dir, monkeypatch):
        """Test command sending handles exceptions."""
        mock_open_func = Mock(side_effect=Exception("Pipe error"))
        monkeypatch.setattr("builtins.open", mock_open_func)

        client = DebugClient()
        result = client.send_command("test_command")

        assert result is False


class TestReadResponse:
    """Tests for reading responses."""

    def test_read_response_success(self, mock_pipe_dir, monkeypatch):
        """Test successful response reading."""
        mock_pipe = MagicMock()
        mock_pipe.readline.return_value = "test_response\n"

        mock_open_func = mock_open()
        mock_open_func.return_value.__enter__.return_value = mock_pipe

        # Mock select to indicate data is ready
        select_mock = Mock(return_value=([mock_pipe], [], []))
        monkeypatch.setattr(select, "select", select_mock)
        monkeypatch.setattr("builtins.open", mock_open_func)

        client = DebugClient()
        result = client.read_response(timeout=2.0)

        assert result == "test_response"
        select_mock.assert_called_once_with([mock_pipe], [], [], 2.0)

    def test_read_response_timeout(self, mock_pipe_dir, monkeypatch):
        """Test response reading timeout."""
        mock_pipe = MagicMock()

        mock_open_func = mock_open()
        mock_open_func.return_value.__enter__.return_value = mock_pipe

        # Mock select to indicate timeout (no data ready)
        select_mock = Mock(return_value=([], [], []))
        monkeypatch.setattr(select, "select", select_mock)
        monkeypatch.setattr("builtins.open", mock_open_func)

        client = DebugClient()
        result = client.read_response(timeout=2.0)

        assert result is None

    def test_read_response_exception(self, mock_pipe_dir, monkeypatch):
        """Test response reading handles exceptions."""
        mock_open_func = Mock(side_effect=Exception("Pipe error"))
        monkeypatch.setattr("builtins.open", mock_open_func)

        client = DebugClient()
        result = client.read_response()

        assert result is None

    def test_read_response_default_timeout(self, mock_pipe_dir, monkeypatch):
        """Test default timeout is used."""
        mock_pipe = MagicMock()
        mock_pipe.readline.return_value = "response\n"

        mock_open_func = mock_open()
        mock_open_func.return_value.__enter__.return_value = mock_pipe

        select_mock = Mock(return_value=([mock_pipe], [], []))
        monkeypatch.setattr(select, "select", select_mock)
        monkeypatch.setattr("builtins.open", mock_open_func)

        client = DebugClient()
        client.read_response()  # No timeout specified

        # Check default timeout was used
        select_mock.assert_called_once_with([mock_pipe], [], [], DEFAULT_TIMEOUT)


class TestGetTargetPid:
    """Tests for getting target PID."""

    def test_get_target_pid_success(self, monkeypatch):
        """Test successful target PID retrieval."""
        send_command_mock = Mock(return_value=True)
        read_response_mock = Mock(return_value="target_pid 12345")

        client = DebugClient()
        client.send_command = send_command_mock
        client.read_response = read_response_mock

        result = client.get_target_pid()

        assert result == 12345
        send_command_mock.assert_called_once_with(controller.Command.GET_TARGET_PID)
        read_response_mock.assert_called_once()

    def test_get_target_pid_send_failure(self, monkeypatch):
        """Test get target PID when send fails."""
        send_command_mock = Mock(return_value=False)

        client = DebugClient()
        client.send_command = send_command_mock

        result = client.get_target_pid()

        assert result is None

    def test_get_target_pid_invalid_response_format(self, monkeypatch):
        """Test get target PID with malformed response."""
        send_command_mock = Mock(return_value=True)
        read_response_mock = Mock(return_value="target_pid")

        client = DebugClient()
        client.send_command = send_command_mock
        client.read_response = read_response_mock

        result = client.get_target_pid()

        assert result is None

    def test_get_target_pid_invalid_pid_value(self, monkeypatch):
        """Test get target PID with non-numeric PID."""
        send_command_mock = Mock(return_value=True)
        read_response_mock = Mock(return_value="target_pid notanumber")

        client = DebugClient()
        client.send_command = send_command_mock
        client.read_response = read_response_mock

        result = client.get_target_pid()

        assert result is None

    def test_get_target_pid_wrong_response_type(self, monkeypatch):
        """Test get target PID with wrong response type."""
        send_command_mock = Mock(return_value=True)
        read_response_mock = Mock(return_value="error Something went wrong")

        client = DebugClient()
        client.send_command = send_command_mock
        client.read_response = read_response_mock

        result = client.get_target_pid()

        assert result is None

    def test_get_target_pid_none_response(self, monkeypatch):
        """Test get target PID when response is None."""
        send_command_mock = Mock(return_value=True)
        read_response_mock = Mock(return_value=None)

        client = DebugClient()
        client.send_command = send_command_mock
        client.read_response = read_response_mock

        result = client.get_target_pid()

        assert result is None


class TestRequestPermission:
    """Tests for requesting ptrace permission."""

    def test_request_permission_success(self, monkeypatch):
        """Test successful permission request."""
        monkeypatch.setattr(os, "getpid", lambda: 67890)

        send_command_mock = Mock(return_value=True)
        read_response_mock = Mock(return_value="ready")

        client = DebugClient()
        client.send_command = send_command_mock
        client.read_response = read_response_mock

        result = client.request_permission()

        assert result is True
        send_command_mock.assert_called_once_with("grant_access 67890")
        read_response_mock.assert_called_once()

    def test_request_permission_send_failure(self, monkeypatch):
        """Test permission request when send fails."""
        send_command_mock = Mock(return_value=False)

        client = DebugClient()
        client.send_command = send_command_mock

        result = client.request_permission()

        assert result is False

    def test_request_permission_error_response(self, monkeypatch):
        """Test permission request with error response."""
        send_command_mock = Mock(return_value=True)
        read_response_mock = Mock(return_value="error : Failed to grant permission")

        client = DebugClient()
        client.send_command = send_command_mock
        client.read_response = read_response_mock

        result = client.request_permission()

        assert result is False

    def test_request_permission_unexpected_response(self, monkeypatch):
        """Test permission request with unexpected response."""
        send_command_mock = Mock(return_value=True)
        read_response_mock = Mock(return_value="unknown_response")

        client = DebugClient()
        client.send_command = send_command_mock
        client.read_response = read_response_mock

        result = client.request_permission()

        assert result is False

    def test_request_permission_none_response(self, monkeypatch):
        """Test permission request when response is None."""
        send_command_mock = Mock(return_value=True)
        read_response_mock = Mock(return_value=None)

        client = DebugClient()
        client.send_command = send_command_mock
        client.read_response = read_response_mock

        result = client.request_permission()

        assert result is False


class TestAttachDebugger:
    """Tests for attaching debugger."""

    def test_attach_debugger_success(self, monkeypatch):
        """Test successful debugger attachment."""
        pdb_attach_mock = Mock()
        monkeypatch.setattr(pdb, "attach", pdb_attach_mock)

        client = DebugClient()
        client.target_pid = 12345

        result = client.attach_debugger()

        assert result is True
        pdb_attach_mock.assert_called_once_with(12345)

    def test_attach_debugger_no_target_pid(self):
        """Test attach debugger when target PID not set."""
        client = DebugClient()
        client.target_pid = None

        result = client.attach_debugger()

        assert result is False

    def test_attach_debugger_permission_error(self, monkeypatch):
        """Test attach debugger with permission error."""
        pdb_attach_mock = Mock(side_effect=PermissionError("Access denied"))
        monkeypatch.setattr(pdb, "attach", pdb_attach_mock)

        client = DebugClient()
        client.target_pid = 12345

        result = client.attach_debugger()

        assert result is False

    def test_attach_debugger_process_not_found(self, monkeypatch):
        """Test attach debugger when process not found."""
        pdb_attach_mock = Mock(side_effect=ProcessLookupError("Process not found"))
        monkeypatch.setattr(pdb, "attach", pdb_attach_mock)

        client = DebugClient()
        client.target_pid = 12345

        result = client.attach_debugger()

        assert result is False

    def test_attach_debugger_generic_exception(self, monkeypatch):
        """Test attach debugger with generic exception."""
        pdb_attach_mock = Mock(side_effect=Exception("Unknown error"))
        monkeypatch.setattr(pdb, "attach", pdb_attach_mock)

        client = DebugClient()
        client.target_pid = 12345

        result = client.attach_debugger()

        assert result is False


class TestRunInteractive:
    """Tests for interactive command loop."""

    def test_run_interactive_attach_command(self, monkeypatch):
        """Test 'attach' command in interactive loop."""
        input_mock = Mock(side_effect=["attach", "quit"])
        request_permission_mock = Mock(return_value=True)
        attach_debugger_mock = Mock(return_value=True)

        monkeypatch.setattr("builtins.input", input_mock)

        client = DebugClient()
        client.request_permission = request_permission_mock
        client.attach_debugger = attach_debugger_mock

        client.run_interactive()

        request_permission_mock.assert_called_once()
        attach_debugger_mock.assert_called_once()

    def test_run_interactive_attach_permission_denied(self, monkeypatch):
        """Test 'attach' command when permission denied."""
        input_mock = Mock(side_effect=["attach", "quit"])
        request_permission_mock = Mock(return_value=False)
        attach_debugger_mock = Mock()

        monkeypatch.setattr("builtins.input", input_mock)

        client = DebugClient()
        client.request_permission = request_permission_mock
        client.attach_debugger = attach_debugger_mock

        client.run_interactive()

        request_permission_mock.assert_called_once()
        # Should not call attach_debugger when permission denied
        attach_debugger_mock.assert_not_called()

    @pytest.mark.parametrize("command", ["quit", "exit"])
    def test_run_interactive_quit_command(self, monkeypatch, command):
        """Test 'quit' command exits loop."""
        input_mock = Mock(return_value=command)
        monkeypatch.setattr("builtins.input", input_mock)

        client = DebugClient()
        assert client.running is True

        client.run_interactive()

        assert client.running is False

    def test_run_interactive_terminate_command(self, monkeypatch):
        """Test 'terminate' command."""
        input_mock = Mock(return_value="terminate")
        send_command_mock = Mock(return_value=True)

        monkeypatch.setattr("builtins.input", input_mock)

        client = DebugClient()
        client.send_command = send_command_mock

        client.run_interactive()

        send_command_mock.assert_called_once_with(controller.Command.TERMINATE)
        assert client.running is False

    def test_run_interactive_help_command(self, monkeypatch):
        """Test 'help' command displays help."""
        input_mock = Mock(side_effect=["help", "quit"])
        monkeypatch.setattr("builtins.input", input_mock)

        client = DebugClient()
        # Should not raise exception
        client.run_interactive()

    def test_run_interactive_unknown_command(self, monkeypatch):
        """Test unknown command handling."""
        input_mock = Mock(side_effect=["unknown", "quit"])
        monkeypatch.setattr("builtins.input", input_mock)

        client = DebugClient()
        # Should not raise exception
        client.run_interactive()

    def test_run_interactive_empty_input(self, monkeypatch):
        """Test empty input is ignored."""
        input_mock = Mock(side_effect=["", "  ", "quit"])
        monkeypatch.setattr("builtins.input", input_mock)

        client = DebugClient()
        client.run_interactive()

    def test_run_interactive_eof_error(self, monkeypatch):
        """Test EOFError handling."""
        input_mock = Mock(side_effect=EOFError())
        monkeypatch.setattr("builtins.input", input_mock)

        client = DebugClient()
        # Should not raise exception
        client.run_interactive()

    def test_run_interactive_keyboard_interrupt(self, monkeypatch):
        """Test KeyboardInterrupt handling."""
        input_mock = Mock(side_effect=KeyboardInterrupt())
        monkeypatch.setattr("builtins.input", input_mock)

        client = DebugClient()
        # Should not raise exception
        client.run_interactive()


class TestRun:
    """Tests for main run method."""

    def test_run_success(self, monkeypatch):
        """Test successful run."""
        check_controller_mock = Mock(return_value=True)
        get_target_pid_mock = Mock(return_value=12345)
        run_interactive_mock = Mock()

        monkeypatch.setattr(os, "getpid", lambda: 99999)

        client = DebugClient()
        client.check_controller_running = check_controller_mock
        client.get_target_pid = get_target_pid_mock
        client.run_interactive = run_interactive_mock

        client.run()

        check_controller_mock.assert_called_once()
        get_target_pid_mock.assert_called_once()
        run_interactive_mock.assert_called_once()
        assert client.running is False

    def test_run_controller_not_running(self, monkeypatch):
        """Test run when controller not running."""
        check_controller_mock = Mock(return_value=False)

        client = DebugClient()
        client.check_controller_running = check_controller_mock

        with pytest.raises(RuntimeError, match="Controller not running"):
            client.run()

    def test_run_get_target_pid_failed(self, monkeypatch):
        """Test run when getting target PID fails."""
        check_controller_mock = Mock(return_value=True)
        get_target_pid_mock = Mock(return_value=None)
        run_interactive_mock = Mock()

        client = DebugClient()
        client.check_controller_running = check_controller_mock
        client.get_target_pid = get_target_pid_mock
        client.run_interactive = run_interactive_mock

        result = client.run()

        assert result == 1
        run_interactive_mock.assert_not_called()

    def test_run_cleanup_on_exception(self, monkeypatch):
        """Test running flag set to False even on exception."""
        check_controller_mock = Mock(return_value=True)
        get_target_pid_mock = Mock(return_value=12345)
        run_interactive_mock = Mock(side_effect=Exception("Test exception"))

        client = DebugClient()
        client.check_controller_running = check_controller_mock
        client.get_target_pid = get_target_pid_mock
        client.run_interactive = run_interactive_mock

        with pytest.raises(Exception, match="Test exception"):
            client.run()

        assert client.running is False


class TestMain:
    """Tests for main entry point."""

    def test_main_success(self, monkeypatch):
        """Test main with successful run."""
        run_mock = Mock(return_value=None)

        with patch("helicopter_parent.client.DebugClient") as client_class_mock:
            client_instance = Mock()
            client_instance.run = run_mock
            client_class_mock.return_value = client_instance

            with pytest.raises(SystemExit) as exc_info:
                from helicopter_parent.client import main

                main()

            assert exc_info.value.code == 0

    def test_main_controller_not_running(self, monkeypatch):
        """Test main when controller not running."""
        run_mock = Mock(side_effect=RuntimeError("Controller not running"))

        with patch("helicopter_parent.client.DebugClient") as client_class_mock:
            client_instance = Mock()
            client_instance.run = run_mock
            client_class_mock.return_value = client_instance

            with pytest.raises(SystemExit) as exc_info:
                from helicopter_parent.client import main

                main()

            assert exc_info.value.code == 1

    def test_main_other_runtime_error(self, monkeypatch):
        """Test main with other RuntimeError."""
        run_mock = Mock(side_effect=RuntimeError("Some other error"))

        with patch("helicopter_parent.client.DebugClient") as client_class_mock:
            client_instance = Mock()
            client_instance.run = run_mock
            client_class_mock.return_value = client_instance

            # Should re-raise other RuntimeErrors
            with pytest.raises(RuntimeError, match="Some other error"):
                from helicopter_parent.client import main

                main()
