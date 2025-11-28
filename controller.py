"""
controller.py - Script A: The controller/parent process

This script:
1. Launches the target process (Script B)
2. Creates named pipes for communication
3. Listens for debug attach commands from client (Script C)
4. Attaches pdb to target process when requested
5. Routes pdb I/O through pipes to client
"""

import os
import sys
import subprocess
import threading
import time
import pdb

# Check Python version
if sys.version_info < (3, 14):
    print("Error: Python 3.14+ required for remote debugging")
    print(f"Current version: {sys.version}")
    sys.exit(1)

# Named pipe paths
PIPE_DIR = "/tmp/heli_debug"
CONTROL_PIPE = os.path.join(PIPE_DIR, "control")
DEBUG_IN = os.path.join(PIPE_DIR, "debug_in")
DEBUG_OUT = os.path.join(PIPE_DIR, "debug_out")


class DebugController:
    """Controller process that manages target and debugger attachment."""

    def __init__(self, target_script, target_args=None):
        """Initialize the debug controller.

        Args:
            target_script: Path to the Python script to run as target
            target_args: Optional list of arguments to pass to target script
        """
        self.target_script = target_script
        self.target_args = target_args or []
        self.target_process = None
        self.debug_active = False
        self.running = True

    def create_pipes(self):
        """Create the named pipes for communication."""
        os.makedirs(PIPE_DIR, exist_ok=True)

        for pipe in (CONTROL_PIPE, DEBUG_IN, DEBUG_OUT):
            if os.path.exists(pipe):
                os.unlink(pipe)
            os.mkfifo(pipe)

        print(f"Created pipes in {PIPE_DIR}")

    def start_target_process(self):
        """Launch the target process (Script B)."""
        cmd = [sys.executable, self.target_script] + self.target_args
        print(f"Starting target process: {' '.join(cmd)}")

        self.target_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )

        print(f"Target process started with PID: {self.target_process.pid}")

        # Start threads to monitor target output
        threading.Thread(
            target=self._monitor_stream,
            args=(self.target_process.stdout, "TARGET-OUT"),
            daemon=True
        ).start()

        threading.Thread(
            target=self._monitor_stream,
            args=(self.target_process.stderr, "TARGET-ERR"),
            daemon=True
        ).start()

    def _monitor_stream(self, stream, prefix):
        """Monitor and log output from target process.

        Args:
            stream: The stream to monitor (stdout or stderr)
            prefix: Prefix for log messages
        """
        try:
            for line in stream:
                print(f"[{prefix}] {line}", end='', flush=True)
        except Exception as e:
            print(f"Error monitoring {prefix}: {e}")

    def attach_debugger(self):
        """Attach pdb to the target process using pdb.attach()."""
        # Check preconditions
        if self.debug_active:
            print("ERROR: Debugger already attached")
            return

        if not self.target_process or self.target_process.poll() is not None:
            print("ERROR: Target process not running")
            return

        print(f"Attaching pdb to PID {self.target_process.pid}...")

        # Open debug pipes
        debug_in = None
        debug_out = None

        try:
            debug_in = open(DEBUG_IN, 'r', buffering=1)
            debug_out = open(DEBUG_OUT, 'w', buffering=1)

            # Save original I/O
            original_stdin = sys.stdin
            original_stdout = sys.stdout
            original_stderr = sys.stderr

            # Redirect to pipes
            sys.stdin = debug_in
            sys.stdout = debug_out
            sys.stderr = debug_out

            # Set debug active flag
            self.debug_active = True

            print("Debugger attached successfully", flush=True)

            # Attach debugger - BLOCKS HERE until user quits pdb
            pdb.attach(self.target_process.pid)

        except Exception as e:
            # Handle errors
            print(f"Error attaching debugger: {e}")

        finally:
            # Restore original I/O
            sys.stdin = original_stdin
            sys.stdout = original_stdout
            sys.stderr = original_stderr

            # Close debug pipes
            if debug_in:
                debug_in.close()
            if debug_out:
                debug_out.close()

            # Clear debug flag
            self.debug_active = False
            print("Debugger session ended")

    def listen_for_commands(self):
        """Listen on control pipe for commands from client."""
        print("Listening for commands on control pipe...")

        while self.running:
            try:
                # Open control pipe for reading (blocks until client connects)
                with open(CONTROL_PIPE, 'r') as pipe:
                    while self.running:
                        command = pipe.readline().strip()
                        if not command:
                            continue

                        print(f"Received command: {command}")

                        if command == "ATTACH":
                            self.attach_debugger()
                        elif command == "QUIT":
                            self.running = False
                            break
                        else:
                            print(f"Unknown command: {command}")
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
