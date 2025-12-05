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
import time

# Check Python version
if sys.version_info < (3, 14):
    print("Error: Python 3.14+ required for remote debugging")
    print(f"Current version: {sys.version}")
    sys.exit(1)

# Same pipe paths as controller
PIPE_DIR = "/tmp/heli_debug"
CONTROL_PIPE = os.path.join(PIPE_DIR, "control")
RESPONSE_PIPE = os.path.join(PIPE_DIR, "response")


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
        if not os.path.exists(PIPE_DIR):
            print("Error: Controller not running (pipes not found)")
            print(f"Start controller first: python controller.py <script>")
            return False

        if not os.path.exists(CONTROL_PIPE):
            print("Error: Control pipe not found")
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
            with open(CONTROL_PIPE, 'w') as pipe:
                pipe.write(command + '\n')
                pipe.flush()
            return True
        except Exception as e:
            print(f"Error sending command: {e}")
            return False

    def read_response(self, timeout=2.0):
        """Read a response from the controller.

        Args:
            timeout: Maximum time to wait for response (seconds)

        Returns:
            str: The response message, or None if timeout/error
        """
        try:
            # Open response pipe for reading
            # This will block until controller writes
            with open(RESPONSE_PIPE, 'r') as pipe:
                line = pipe.readline()
                if line:
                    return line.strip()
        except Exception as e:
            print(f"Error reading response: {e}")
        return None

    def get_target_pid(self):
        """Get the target PID from controller.

        Returns:
            int: Target PID, or None if failed
        """
        # Request target PID from controller
        if not self.send_command("GET_TARGET_PID"):
            return None

        # Read response
        response = self.read_response(timeout=2.0)

        if response and response.startswith("TARGET_PID "):
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

        # Send GRANT_ACCESS command
        if not self.send_command(f"GRANT_ACCESS {self.client_pid}"):
            return False

        # Wait for READY response
        response = self.read_response(timeout=3.0)

        if response == "READY":
            print("✅ Permission granted")
            return True
        elif response and response.startswith("ERROR"):
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

        print(f"\nAttaching pdb to target PID {self.target_pid}...")
        print("Type pdb commands (list, next, print, etc.) or 'quit' to detach\n")

        try:
            # Direct pdb.attach - no I/O redirection!
            pdb.attach(self.target_pid)

            # When pdb.attach() returns, user has quit the debugger
            print("\nDebugger detached")
            return True

        except PermissionError as e:
            print(f"\n❌ Permission denied: {e}")
            print("This usually means:")
            print("  1. ptrace_scope is set too restrictively")
            print("  2. Permission was not granted by controller")
            print(f"  3. Check: cat /proc/sys/kernel/yama/ptrace_scope")
            return False

        except ProcessLookupError:
            print(f"\n❌ Target process {self.target_pid} not found")
            print("The target may have crashed or exited")
            return False

        except Exception as e:
            print(f"\n❌ Error attaching debugger: {e}")
            return False

    def run_interactive(self):
        """Run the interactive command loop."""
        print("Helicopter Parent - Debug Client V2")
        print("=" * 50)
        print("Commands: attach, quit, stop")
        print("-" * 50)

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
                        print("Failed to get permission. Try again or check controller.")

                elif command in ("quit", "exit"):
                    # Just exit client, leave controller and target running
                    print("Exiting client (controller and target still running)")
                    self.running = False
                    break

                elif command == "stop":
                    # Stop controller and target, then exit client
                    print("Stopping controller and target...")
                    self.send_command("STOP")
                    self.running = False
                    break

                elif command == "help":
                    print("\nAvailable commands:")
                    print("  attach - Request permission and attach debugger to target")
                    print("  quit   - Exit client (leave controller running)")
                    print("  stop   - Stop controller, target, and exit client")
                    print("  help   - Show this help message")

                else:
                    print(f"Unknown command: {command}")
                    print("Available commands: attach, quit, stop, help")

            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print("\nInterrupted")
                break

    def run(self):
        """Main run method."""
        if not self.check_controller_running():
            return 1

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
            print("Goodbye!")

        return 0


def main():
    """Main entry point."""
    client = DebugClient()
    sys.exit(client.run())


if __name__ == "__main__":
    main()
