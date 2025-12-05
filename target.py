"""
target.py - Script B: The target process to be debugged

This is a simple example script that runs in the background.
It can be replaced with any Python script/application.
"""

import time
import os
import sys


def work_loop():
    """Simulate some work being done."""
    counter = 0
    while True:
        counter += 1
        result = counter * 2
        print(f"Iteration {counter}: result = {result}", flush=True)

        # Sleep in small increments to allow sys.remote_exec() to inject code
        # (injected code runs "at next available opportunity" during bytecode execution)
        for _ in range(20):
            time.sleep(0.1)  # 100 * 0.1 = 10 seconds total


def main():
    """Main entry point for the target process."""
    print(f"Target process started (PID: {os.getpid()})", flush=True)
    print("Starting work loop...", flush=True)

    try:
        work_loop()
    except KeyboardInterrupt:
        print("\nTarget process interrupted", flush=True)
    except Exception as e:
        print(f"Error in target process: {e}", file=sys.stderr, flush=True)
        raise


if __name__ == "__main__":
    main()
