"""
client.py - Script C: Interactive client for remote debugging

This script:
1. Connects to the controller via named pipes
2. Provides interactive command interface
3. Sends debug commands (attach, status, quit)
4. Routes user input to debugger and displays output
"""

import os
import sys
import threading
import time

# Check Python version
if sys.version_info < (3, 14):
    print("Error: Python 3.14+ required for remote debugging")
    print(f"Current version: {sys.version}")
    sys.exit(1)

# Same pipe paths as controller
PIPE_DIR = "/tmp/heli_debug"
CONTROL_PIPE = os.path.join(PIPE_DIR, "control")
DEBUG_IN = os.path.join(PIPE_DIR, "debug_in")
DEBUG_OUT = os.path.join(PIPE_DIR, "debug_out")
STATUS_PIPE = os.path.join(PIPE_DIR, "status")


class DebugClient:
    """Interactive client for remote debugging."""

    def __init__(self):
        """Initialize the debug client."""
        self.running = True
        self.debug_active = False
        self.status_thread = None
        self.output_thread = None

    def check_controller_running(self):
        """Check if controller is running by verifying pipes exist.

        Returns:
            bool: True if controller is running, False otherwise
        """
        if not os.path.exists(PIPE_DIR):
            print("Error: Controller not running (pipes not found)")
            print(f"Start controller first: python controller.py <script>")
            return False
        return True

    def _monitor_status(self):
        """Monitor status pipe for messages from controller (runs in thread)."""
        try:
            with open(STATUS_PIPE, 'r') as pipe:
                while self.running:
                    line = pipe.readline()
                    if not line:
                        break

                    message = line.strip()
                    print(f"\n[STATUS] {message}", flush=True)

                    # Update state based on status
                    if "ATTACHED:" in message:
                        self.debug_active = True
                    elif "DETACHED:" in message:
                        self.debug_active = False

        except Exception as e:
            if self.running:
                print(f"Status monitor error: {e}")

    def send_command(self, command):
        """Send a command to the controller.

        Args:
            command: The command string to send

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Open with timeout to avoid infinite blocking
            import fcntl
            fd = os.open(CONTROL_PIPE, os.O_WRONLY)
            os.write(fd, (command + '\n').encode())
            os.close(fd)
            return True
        except Exception as e:
            print(f"Error sending command: {e}")
            return False

    def _read_debug_output(self, pipe):
        """Read and display output from debugger (runs in thread).

        Args:
            pipe: The debug output pipe to read from
        """
        try:
            for line in pipe:
                print(line, end='', flush=True)
        except Exception as e:
            if self.debug_active:
                print(f"Output reader error: {e}")

    def _debug_session(self):
        """Handle interactive debug session."""
        try:
            # Open debug pipes (this unblocks controller)
            debug_in = open(DEBUG_IN, 'w', buffering=1)
            debug_out = open(DEBUG_OUT, 'r', buffering=1)

            # Mark session as active
            self.debug_active = True

            # Start output reader thread
            self.output_thread = threading.Thread(
                target=self._read_debug_output,
                args=(debug_out,),
                daemon=True
            )
            self.output_thread.start()

            # Read user input and send to debugger
            while True:
                try:
                    user_input = input()
                    debug_in.write(user_input + '\n')
                    debug_in.flush()

                except EOFError:
                    break
                except (BrokenPipeError, IOError) as e:
                    # Pipe closed by controller (pdb session ended)
                    break
                except KeyboardInterrupt:
                    # Send quit command to pdb
                    try:
                        debug_in.write('quit\n')
                        debug_in.flush()
                    except (BrokenPipeError, IOError):
                        pass  # Pipe already closed
                    break

        except Exception as e:
            print(f"Debug session error: {e}")
        finally:
            # Cleanup
            self.debug_active = False
            if 'debug_in' in locals():
                debug_in.close()
            if 'debug_out' in locals():
                debug_out.close()

    def run_interactive(self):
        """Run the interactive command loop."""
        print("Helicopter Parent - Debug Client")
        print("=" * 50)
        print("Commands: attach, status, quit")
        print("-" * 50)

        while self.running:
            try:
                if self.debug_active:
                    # In debug session - handled by _debug_session
                    time.sleep(0.1)
                    continue

                # Normal command mode
                command = input(">>> ").strip().lower()

                if not command:
                    continue

                if command == "attach":
                    self.send_command("ATTACH")
                    # Small delay to let controller process command
                    time.sleep(0.1)
                    # Start debug session immediately (opening pipes unblocks controller)
                    self._debug_session()

                elif command == "status":
                    self.send_command("STATUS")

                elif command in ("quit", "exit"):
                    self.send_command("QUIT")
                    self.running = False
                    break

                else:
                    print(f"Unknown command: {command}")
                    print("Available commands: attach, status, quit")

            except EOFError:
                break
            except KeyboardInterrupt:
                print("\nInterrupted")
                break

    def run(self):
        """Main run method."""
        if not self.check_controller_running():
            return

        # Start status monitor thread
        self.status_thread = threading.Thread(
            target=self._monitor_status,
            daemon=True
        )
        self.status_thread.start()

        # Give status thread time to connect
        time.sleep(0.2)

        try:
            self.run_interactive()
        finally:
            self.running = False
            print("Goodbye!")


def main():
    """Main entry point."""
    client = DebugClient()
    client.run()


if __name__ == "__main__":
    main()
