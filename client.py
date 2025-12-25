"""
client.py - V2: Client that directly attaches pdb to target

This script:
1. Connects to the controller via named pipes
2. Requests ptrace permission for its PID
3. Directly calls pdb.attach() to debug target
4. No I/O redirection needed - native pdb experience!
"""

import os
import sys
import pdb
import select
from textwrap import dedent

import controller

# Check Python version
if sys.version_info < (3, 14):
    print("Error: Python 3.14+ required for remote debugging")
    print(f"Current version: {sys.version}")
    sys.exit(1)

# Same pipe paths as controller
PIPE_DIR = "/tmp/heli_debug"

DEFAULT_TIMEOUT = 2.0  # seconds


class DebugClient:
    """Interactive client for remote debugging via direct pdb.attach()."""

    def __init__(self):
        """Initialize the debug client."""
        self.running = True
        self.target_pid = None
        self.client_pid = os.getpid()

    def check_controller_running(self):
        """Check if controller is running by verifying pipes exist.

        Returns:
            bool: True if controller is running, False otherwise
        """
        if not (controller.CONTROL_PIPE.exists() & controller.RESPONSE_PIPE.exists()):
            CONTROLLER_NOT_RUNNING_MSG = dedent(
                """Error: Controller not running (pipes not found)
                Start controller first: python controller.py <script>
                """
            )
            print(CONTROLLER_NOT_RUNNING_MSG)
            return False

        return True

    def send_command(self, command):
        """Send a command to the controller.

        Args:
            command: The command string to send

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            with open(controller.CONTROL_PIPE, "w") as pipe:
                pipe.write(command + "\n")
                pipe.flush()
            return True
        except Exception as e:
            print(f"Error sending command: {e}")
            return False

    def read_response(self, timeout=DEFAULT_TIMEOUT):
        """Read a response from the controller.

        Args:
            timeout: Maximum time to wait for response (seconds)

        Returns:
            str: The response message, or None if timeout/error
        """
        try:
            # Open response pipe for reading
            with open(controller.RESPONSE_PIPE, "r") as pipe:
                # Use select to wait for data with timeout
                ready, _, _ = select.select([pipe], [], [], timeout)
                if ready:
                    return pipe.readline().strip()
                else:
                    print("Timeout waiting for response")
                    return None
        except Exception as e:
            print(f"Error reading response: {e}")
        return None

    def get_target_pid(self):
        """Get the target PID from controller.

        Returns:
            int: Target PID, or None if failed
        """
        # Request target PID from controller
        if not self.send_command(controller.Command.GET_TARGET_PID):
            return None

        # Read response
        response = self.read_response()

        if response and response.startswith(controller.Response.TARGET_PID):
            try:
                pid = int(response.split()[1])
                print(f"Target PID: {pid}")
                return pid
            except (IndexError, ValueError):
                print(f"Invalid TARGET_PID response: {response}")

        return None

    def request_permission(self):
        """Request ptrace permission from controller.

        Returns:
            bool: True if permission granted, False otherwise
        """
        print(f"Requesting ptrace permission for client PID {self.client_pid}...")

        if not self.send_command(
            f"{controller.Command.GRANT_ACCESS} {self.client_pid}"
        ):
            return False

        # Wait for READY response
        response = self.read_response()

        if response == controller.Response.READY:
            print("✅ Permission granted")
            return True
        elif response and response.startswith(controller.Response.ERROR):
            print(f"❌ {response}")
            return False
        else:
            print(f"❌ Unexpected response: {response}")
            return False

    def attach_debugger(self):
        """Attach pdb directly to target process."""
        if not self.target_pid:
            print("Error: Target PID not known")
            return False

        ATTACH_MSG = dedent("""
            Attaching pdb to target PID {}...
            Type pdb commands (list, next, print, etc.) or 'quit' to detach
            """)
        print(ATTACH_MSG.format(self.target_pid))

        try:
            pdb.attach(self.target_pid)

            # When pdb.attach() returns, user has quit the debugger
            print("\nDebugger detached")
            return True

        except PermissionError as exc:
            DENIED_ERR_MSG = dedent("""
                ❌ Permission denied: {}
                This usually means:
                1. ptrace_scope is set too restrictively
                    (check: cat /proc/sys/kernel/yama/ptrace_scope)
                2. Permission was not granted by controller
                3. Target hasn't yet run pending call (can try again)
                """)
            print(DENIED_ERR_MSG.format(exc))
            return False

        except ProcessLookupError:
            PROCESS_NOT_FOUND_MSG = dedent("""
                ❌ Target process {} not found
                The target may have crashed or exited
                """)
            print(PROCESS_NOT_FOUND_MSG.format(self.target_pid))
            return False

        except Exception as e:
            print(f"❌ Error attaching debugger: {e}")
            return False

    def run_interactive(self):
        """Run the interactive command loop."""
        BANNER = dedent("""
            Helicopter Parent - Debug Client
            ==================================================
            Commands: attach, quit, terminate
            --------------------------------------------------
            """)
        print(BANNER)

        while self.running:
            try:
                # Get command from user
                command = input(">>> ").strip().lower()

                if not command:
                    continue

                if command == "attach":
                    # Request permission and attach
                    if self.request_permission():
                        self.attach_debugger()
                    else:
                        print(
                            "Failed to get permission. Try again or check controller."
                        )

                elif command in ("quit", "exit"):
                    # Just exit client, leave controller and target running
                    print("Exiting client (controller and target still running)")
                    self.running = False
                    break

                elif command == "terminate":
                    # Terminate controller and target, then exit client
                    print("Terminating controller and target...")
                    self.send_command(controller.Command.TERMINATE)
                    self.running = False
                    break

                elif command == "help":
                    HELP_MSG = dedent("""
                        Available commands:
                          attach    - Request permission and attach debugger to target
                          quit      - Exit client (leave controller running)
                          terminate - Terminate controller, target, and exit client
                          help      - Show this help message
                        """)
                    print(HELP_MSG)

                else:
                    UNKNOWN_CMD_MSG = dedent("""
                        Unknown command: {}
                        Available commands: attach, quit, terminate, help
                        """)
                    print(UNKNOWN_CMD_MSG.format(command))

            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print("\nInterrupted")
                break

    def run(self):
        """Main run method."""
        if not self.check_controller_running():
            raise RuntimeError("Controller not running")

        print(f"Client PID: {self.client_pid}")

        # Connect to both pipes to trigger controller to send TARGET_PID
        # We need to connect to response pipe first, then controller will send
        print("Connecting to controller...")

        # Get target PID from controller
        self.target_pid = self.get_target_pid()
        if not self.target_pid:
            print("Failed to get target PID from controller")
            return 1

        try:
            self.run_interactive()
        finally:
            self.running = False

        return


def main():
    """Main entry point."""
    client = DebugClient()
    try:
        client.run()
    except RuntimeError as e:
        if "not running" in str(e):
            print("Error: Controller not running. Start controller first.")
            sys.exit(1)
        else:
            raise
    sys.exit(0)


if __name__ == "__main__":
    main()
