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
import logging

# Named pipe paths
PIPE_DIR = Path("/tmp/heliparent_debug")
CONTROL_PIPE = PIPE_DIR / "control"
RESPONSE_PIPE = PIPE_DIR / "response"

# PR_SET_PTRACER constant (got the value from
# https://github.com/torvalds/linux/blob/master/include/uapi/linux/prctl.h)
PR_SET_PTRACER_BINARY = int.from_bytes(b"Yama")  # 0x59616d61

logger = logging.getLogger(__name__)

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

def ensure_platform_support():
    """Check if the current platform / Python is supported."""
    if sys.platform != "linux":
        raise RuntimeError("helicopter-parent only supports Linux.")
    if sys.version_info < (3, 14):
        raise RuntimeError("Error: Python 3.14+ required for remote debugging; current is {sys.version}")


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
        self._clients_granted = set()

    def create_pipes(self):
        """Create the named pipes for communication."""
        PIPE_DIR.mkdir(exist_ok=True, mode=0o700)

        for pipe in (CONTROL_PIPE, RESPONSE_PIPE):
            pipe.unlink(missing_ok=True)
            os.mkfifo(pipe, mode=0o600)

        logger.info(f"Created pipes in {PIPE_DIR}")

    def start_target_process(self):
        """Launch the target process (Script B)."""
        cmd = [sys.executable, self.target_script] + self.target_args
        logger.debug(f"Starting target process: {' '.join(cmd)}")

        self.target_process = subprocess.Popen(cmd, text=True, bufsize=1)

        logger.info(f"Target process started with PID: {self.target_process.pid}")

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
        # We use prefixed symbols to avoid overwriting ones in the target,
        # and delete them at the end to not pollute the namespace
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
            return Path(f.name)

    def grant_ptrace_permission(self, client_pid):
        """Grant ptrace permission to client using sys.remote_exec().

        Tracks PIDs granted; if the same one is requested again, skip.

        Args:
            client_pid: The PID of the client to grant permission to

        Returns:
            bool: True if successful or skipped, False otherwise
        """
        # Check preconditions
        if client_pid in self._clients_granted:
            # TODO: make the check robust to PID recycling by getting create time of process?
            logger.debug("Already granted client PID {client_pid}, skipping")
            return True
        if not self.target_process or self.target_process.poll() is not None:
            logger.error("Target process not running")
            return False

        logger.info(f"Granting ptrace permission to client PID {client_pid}...")

        try:
            script_path = self._create_prctl_script(client_pid)

            # Execute in target process
            sys.remote_exec(self.target_process.pid, str(script_path))
            logger.debug(f"Scheduled permission grant to client PID {client_pid}")
            self._clients_granted.add(client_pid)

            # Note: sys.remote_exec returns immediately, code executes
            # "at next available opportunity", so wait a short time
            time.sleep(0.2)

            return True

        except Exception as e:
            logger.error(f"Error granting ptrace permission: {e}")
            return False

    def listen_for_commands(self):
        """Listen on control pipe for commands from client."""
        logger.info("Listening for commands on control pipe...")

        while self.running:
            try:
                # Note: pipe opening blocks until client connects
                with open(CONTROL_PIPE, "r") as pipe:
                    while self.running:
                        line = pipe.readline()
                        if not line:
                            # Client disconnected
                            break

                        command = line.strip()
                        if not command:
                            continue

                        logger.debug(f"Received command: {command}")
                        parts = command.split()
                        cmd = parts[0]

                        if cmd == Command.GET_TARGET_PID:
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
                                logger.warning(f"Invalid PID: {parts[1]}")
                                self._send_response(f"{Response.ERROR} : Invalid PID")

                        elif cmd == Command.TERMINATE:
                            self.running = False
                            break

                        else:
                            logger.warning(f"Unknown command: {command}")
                            self._send_response(
                                f"{Response.ERROR} : Unknown command: {cmd}"
                            )

            except Exception as e:
                if self.running:
                    logger.error(f"Error in command listener: {e}")
                    time.sleep(1)

    def cleanup(self):
        """Clean up processes and pipes."""
        logger.debug("Cleaning up...")

        self.running = False

        if self.target_process:
            logger.info("Terminating target process...")
            self.target_process.terminate()
            try:
                self.target_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.target_process.kill()

        # Clean up pipes
        for pipe in (CONTROL_PIPE, RESPONSE_PIPE):
            pipe.unlink(missing_ok=True)


    def run(self):
        """Main run loop."""
        try:
            self.create_pipes()
            self.start_target_process()
            self.listen_for_commands()
        except KeyboardInterrupt:
            logger.info("Controller interrupted")
        finally:
            self.cleanup()


def main():
    """Main entry point."""
    logging.basicConfig(format="%(levelname)s:%(asctime)s:%(name)s:%(message)s", level=logging.INFO)

    ensure_platform_support()

    if len(sys.argv) < 2:
        print("Usage: helicopter-parent <target_script> [args...]")
        sys.exit(1)

    target_script = sys.argv[1]
    target_args = sys.argv[2:] if len(sys.argv) > 2 else []

    controller = DebugController(target_script, target_args)
    controller.run()


if __name__ == "__main__":
    main()
