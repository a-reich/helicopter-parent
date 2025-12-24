"""
Main helicopter-parent controller script

This script:
1. Launches the target process
2. Creates named pipes for communication
3. Listens for ptrace permission requests from client
4. Uses sys.remote_exec() to inject prctl call granting client permission
5. Sends response back to client
"""

import os
import sys
import subprocess
import tempfile
import time
from pathlib import Path
from enum import StrEnum, auto
from textwrap import dedent

if sys.version_info < (3, 14):
    print("Error: Python 3.14+ required for remote debugging; current is {sys.version}")
    sys.exit(1)

# Named pipe paths
PIPE_DIR = Path("/tmp/heliparent_debug")
CONTROL_PIPE = PIPE_DIR / "control"
RESPONSE_PIPE = PIPE_DIR / "response"

# PR_SET_PTRACER constant (got the value from
# https://github.com/torvalds/linux/blob/master/include/uapi/linux/prctl.h)
PR_SET_PTRACER_BINARY = int.from_bytes(b"Yama")  # 0x59616d61


class Command(StrEnum):
    """Recognized commands from client."""

    GET_TARGET_PID = auto()
    GRANT_ACCESS = auto()
    TERMINATE = auto()


class Response(StrEnum):
    """Responses to client."""

    READY = auto()
    ERROR = auto()
    TARGET_PID = auto()


class DebugController:
    """Controller process that manages target and grants ptrace permission."""

    def __init__(self, target_script, target_args=None):
        """Initialize the debug controller.

        Args:
            target_script: Path to the Python script to run as target
            target_args: Optional list of arguments to pass to target script
        """
        self.target_script = target_script
        self.target_args = target_args or []
        self.target_process = None
        self.running = True

    def create_pipes(self):
        """Create the named pipes for communication."""
        PIPE_DIR.mkdir(exist_ok=True, mode=0o700)

        for pipe in (CONTROL_PIPE, RESPONSE_PIPE):
            if pipe.exists():
                pipe.unlink()
            os.mkfifo(pipe, mode=0o600)

        print(f"Created pipes in {PIPE_DIR}")

    def start_target_process(self):
        """Launch the target process (Script B)."""
        cmd = [sys.executable, self.target_script] + self.target_args
        print(f"Starting target process: {' '.join(cmd)}")

        self.target_process = subprocess.Popen(cmd, text=True, bufsize=1)

        print(f"Target process started with PID: {self.target_process.pid}")

    def _send_response(self, message):
        """Send a response message to client (non-blocking).

        Args:
            message: The message to send
        """
        try:
            # Open in non-blocking mode to avoid hanging if no client connected
            fd = os.open(RESPONSE_PIPE, os.O_WRONLY | os.O_NONBLOCK)
            try:
                os.write(fd, (message + "\n").encode())
            finally:
                os.close(fd)
        except (OSError, IOError):
            # No client connected, silently ignore
            pass

    def _create_prctl_script(self, client_pid):
        """Create a temporary Python script that grants ptrace permission.

        Args:
            client_pid: The PID of the client to grant permission to

        Returns:
            Path to the temporary script file
        """
        script_content = dedent(f"""
            import ctypes as _heliparent_ctypes

            _HELIPARENT_PTRACER_BINARY = {PR_SET_PTRACER_BINARY}
            _heliparent_libc = _heliparent_ctypes.CDLL("libc.so.6")

            # Run prctl system call's with PR_SET_PTRACER option to grant ptrace permission to client
            # Result is currently ignored
            _heliparent_libc.prctl(_HELIPARENT_PTRACER_BINARY, {client_pid}, 0, 0, 0)  
            del _heliparent_ctypes, _heliparent_libc
            """)

        # Create temp file in PIPE_DIR for consistency
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, dir=PIPE_DIR
        ) as f:
            f.write(script_content)
            return f.name

    def grant_ptrace_permission(self, client_pid):
        """Grant ptrace permission to client using sys.remote_exec().

        Args:
            client_pid: The PID of the client to grant permission to

        Returns:
            bool: True if successful, False otherwise
        """
        # Check preconditions
        if not self.target_process or self.target_process.poll() is not None:
            print(f"ERROR: Target process not running")
            return False

        print(f"Granting ptrace permission to client PID {client_pid}...")

        script_path = None
        try:
            # Create injection script
            script_path = self._create_prctl_script(client_pid)

            # Inject into target process
            sys.remote_exec(self.target_process.pid, script_path)

            # Wait for execution
            # Note: sys.remote_exec returns immediately, code executes
            # "at next available opportunity"
            time.sleep(0.2)

            print(f"Permission granted to client PID {client_pid}")
            return True

        except Exception as e:
            print(f"Error granting ptrace permission: {e}")
            return False

        finally:
            # Clean up temp file after delay
            if script_path:
                time.sleep(0.3)  # Extra delay to ensure target has read it
                try:
                    os.unlink(script_path)
                except OSError:
                    pass  # Already deleted

    def listen_for_commands(self):
        """Listen on control pipe for commands from client."""
        print("Listening for commands on control pipe...")

        while self.running:
            try:
                # Open control pipe for reading (blocks until client connects)
                with open(CONTROL_PIPE, "r") as pipe:
                    while self.running:
                        line = pipe.readline()
                        if not line:
                            # Client disconnected
                            break

                        command = line.strip()
                        if not command:
                            continue

                        print(f"Received command: {command}")

                        # Parse command
                        parts = command.split()
                        cmd = parts[0]

                        if cmd == Command.GET_TARGET_PID:
                            # Client requests target PID
                            self._send_response(
                                f"{Response.TARGET_PID} {self.target_process.pid}"
                            )

                        elif cmd == Command.GRANT_ACCESS and len(parts) == 2:
                            try:
                                client_pid = int(parts[1])
                                if self.grant_ptrace_permission(client_pid):
                                    self._send_response(Response.READY)
                                else:
                                    self._send_response(
                                        f"{Response.ERROR} : Failed to grant permission"
                                    )
                            except ValueError:
                                print(f"Invalid PID: {parts[1]}")
                                self._send_response(f"{Response.ERROR} : Invalid PID")

                        elif cmd == Command.TERMINATE:
                            self.running = False
                            break

                        else:
                            print(f"Unknown command: {command}")
                            self._send_response(
                                f"{Response.ERROR} : Unknown command: {cmd}"
                            )

            except Exception as e:
                if self.running:
                    print(f"Error in command listener: {e}")
                    time.sleep(1)

    def cleanup(self):
        """Clean up processes and pipes."""
        print("\nCleaning up...")

        self.running = False

        if self.target_process:
            print("Terminating target process...")
            self.target_process.terminate()
            try:
                self.target_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.target_process.kill()

        # Clean up pipes
        try:
            for pipe in (CONTROL_PIPE, RESPONSE_PIPE):
                if os.path.exists(pipe):
                    os.unlink(pipe)
        except OSError:
            pass

        print("Cleanup complete")

    def run(self):
        """Main run loop."""
        try:
            self.create_pipes()
            self.start_target_process()
            self.listen_for_commands()
        except KeyboardInterrupt:
            print("\nController interrupted")
        finally:
            self.cleanup()


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python controller.py <target_script> [args...]")
        print("Example: python controller.py target.py")
        sys.exit(1)

    target_script = sys.argv[1]
    target_args = sys.argv[2:] if len(sys.argv) > 2 else []

    controller = DebugController(target_script, target_args)
    controller.run()


if __name__ == "__main__":
    main()
