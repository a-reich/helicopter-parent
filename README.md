# Helicopter Parent - Remote Python Debugger

On-demand remote debugging for Python processes using Python 3.14's `pdb.attach()` feature.

## Overview

Helicopter Parent allows you to:
- Start a Python process under supervision
- Attach a debugger to it later from a separate session
- Debug interactively with full native pdb features
- Detach and reattach multiple times

**Key Features:**
- Client directly calls `pdb.attach()` on target
- Controller grants ptrace permission via `sys.remote_exec()` + `prctl(PR_SET_PTRACER)`
- Full native pdb experience with colors, readline, tab completion

## Requirements

- **Python 3.14+** (uses `pdb.attach()` and `sys.remote_exec()` from PEP 768)
- **Linux with Yama LSM** (uses `prctl(PR_SET_PTRACER)`)
- **ptrace_scope ≤ 1** (check with `cat /proc/sys/kernel/yama/ptrace_scope`)
- Same user running both controller and client

## Quick Start

### Terminal 1: Start the Controller

```bash
python3.14 controller.py target.py
```

This starts the controller which:
- Creates named pipes in `/tmp/heliparent_debug/`
- Launches `target.py` as a subprocess
- Waits for debug commands

### Terminal 2: Connect the Client

```bash
python3.14 client.py
```

Available commands:
- `attach` - Attach debugger to the target process
- `quit` - Exit client (leave controller running)
- `terminate` - Stop controller, target, and exit client
- `help` - Show help message

### Example Session

```bash
# In Terminal 2 (client)
>>> attach
Requesting ptrace permission for client PID 12346...
✅ Permission granted

Attaching pdb to target PID 12345...
Type pdb commands (list, next, print, etc.) or 'quit' to detach

> /home/user/helicopter_parent/target.py(44)work_loop()
-> counter += 1
(Pdb) list
 39         def work_loop():
 40             """Simulate some work being done."""
 41             counter = 0
 42             while True:
 43                 counter += 1
 44  ->             n = random.randint(10**5, 10**6)
 45                 result = factorize(n)
 46                 logger.info(f"Iteration {counter}, number {n}")
 47                 time.sleep(1)

(Pdb) p counter
42

(Pdb) n
> /home/user/helicopter_parent/target.py(45)work_loop()
-> result = factorize(n)

(Pdb) p n
542891

(Pdb) quit

Debugger detached
>>> quit
Goodbye!
```

## Architecture

```
┌──────────────┐        ┌──────────────┐         ┌──────────────┐
│  Controller  │        │    Target    │         │    Client    │
│              │        │   (Process   │         │              │
│ controller.py│        │  to debug)   │         │  client.py   │
│              │        │              │         │              │
│  • Spawns    │        │  target.py   │         │  • Requests  │
│    target    │        │              │         │    permission│
│  • Injects   │        │              │         │  • Calls     │
│    prctl via │        │              │         │    pdb.attach│
│    sys.      │        │              │         │              │
│    remote_   │        │              │         │              │
│    exec()    │        └──────────────┘         └──────────────┘
│              │               ▲                        │
└──────────────┘               │                        │
       │                       │ prctl grants           │
       │                       │ ptrace permission      │
       ▼                       │                        ▼
Named Pipes:                   └────────────────────────┘
/tmp/.../                       Direct ptrace connection
  ├─ control ───► (Client → Controller)
  └─ response ──► (Controller → Client)
```

### How It Works

1. **Controller** spawns target process
2. **Client** connects and sends `GRANT_ACCESS <client_pid>`
3. **Controller** uses `sys.remote_exec(target_pid, script)` to inject:
   ```python
   prctl(PR_SET_PTRACER, client_pid)  # Grant permission
   ```
4. **Client** can now call `pdb.attach(target_pid)` directly
5. **User** interacts with native pdb in their terminal


## Usage Patterns

### Debug Your Own Script

Replace `target.py` with any Python script:

```bash
python3.14 controller.py my_script.py --arg1 value1
```

The controller will launch your script and you can attach to it later.

### Multiple Attach/Detach Cycles

You can attach, debug, quit pdb, and reattach multiple times:

```bash
>>> attach
(Pdb) p some_variable
42
(Pdb) quit

# Target keeps running...

>>> attach
(Pdb) p some_variable
156  # Value changed while target was running
(Pdb) quit
```

### Debugging Long-Running Processes

Perfect for debugging:
- Web servers
- Background workers
- Data processing pipelines
- Any process that runs continuously

## PDB Commands Reference

Once attached, use standard pdb commands:

- `list` / `l` - Show source code
- `next` / `n` - Execute next line
- `step` / `s` - Step into function
- `continue` / `c` - Continue execution
- `break` / `b` - Set breakpoint
- `print` / `p` - Print expression
- `where` / `w` - Show stack trace
- `up` / `u` - Go up stack frame
- `down` / `d` - Go down stack frame
- `quit` / `q` - Detach debugger

See [pdb documentation](https://docs.python.org/3/library/pdb.html) for complete command reference.

## Command Protocol

### Client → Controller (Control Pipe)

- `GET_TARGET_PID` - Request the target process PID
- `GRANT_ACCESS <pid>` - Request ptrace permission for client PID
- `TERMINATE` - Stop controller and target

### Controller → Client (Response Pipe)

- `TARGET_PID <pid>` - Target process PID
- `READY` - Permission granted, ready to attach
- `ERROR: <message>` - Error occurred

## Troubleshooting

### "Controller not running (pipes not found)"

Start the controller first:
```bash
python3.14 controller.py target.py
```

### "Python 3.14+ required"

This project requires Python 3.14 or later for `pdb.attach()` and `sys.remote_exec()`. Check your version:
```bash
python3.14 --version
```

### "Permission denied" when attaching

Check your ptrace_scope setting:
```bash
cat /proc/sys/kernel/yama/ptrace_scope
```

- `0` = Classic ptrace (permissive) - works
- `1` = Restricted ptrace (default on most systems) - **designed for this!**
- `2` = Admin-only attach - requires CAP_SYS_PTRACE
- `3` = No attach - won't work

This system is specifically designed to work with ptrace_scope=1 using PR_SET_PTRACER.

### "Target process not running"

The target process may have crashed. Check controller output for errors.

### Debugger not responsive after attach

If the target is blocked in a long C extension call, the injected prctl code may not execute immediately. The code runs "at next available opportunity" when Python bytecode executes. This is why target.py sleeps in small increments (1s) rather than one long sleep.

### Timeout waiting for response

The client has a 2-second timeout when waiting for responses from the controller. If you see timeout messages:
- Controller may not be running
- Target process may have crashed
- Network filesystem issues with named pipes

## Technical Details

### PR_SET_PTRACER

The system uses the Linux Yama LSM's `PR_SET_PTRACER` prctl option to grant specific ptrace permission:

```python
import ctypes
PR_SET_PTRACER = int.from_bytes(b'Yama')  # 0x59616d61
libc = ctypes.CDLL("libc.so.6")
libc.prctl(PR_SET_PTRACER, client_pid, 0, 0, 0)
```

This allows the target to explicitly grant ptrace permission to the client, bypassing the normal "parent-only" restriction.

### sys.remote_exec()

Python 3.14's `sys.remote_exec()` allows injecting code into the target:

```python
import sys
# Create script file with prctl call
sys.remote_exec(target_pid, script_path)
# Code executes "at next available opportunity"
```

The injected code grants ptrace permission, then the client can attach directly.

### Direct pdb.attach()

Once permission is granted, the client uses Python 3.14's native `pdb.attach()`:

```python
pdb.attach(target_pid)
```

This provides a native pdb debugging experience with full terminal control, readline support, and proper signal handling.

## Limitations

- **Linux only**: Uses Linux-specific prctl and Yama LSM
- **Python 3.14+ required**: Relies on `pdb.attach()` and `sys.remote_exec()`
- **Single client**: Only one client can attach at a time (shared pipes)
- **Local only**: Uses named pipes (for remote debugging, would need sockets)
- **ptrace_scope ≤ 1**: Requires permissive enough ptrace settings
- **Python targets only**: Target process must be Python (for remote_exec)


## References

- [Python 3.14 What's New - pdb](https://docs.python.org/3/whatsnew/3.14.html#pdb)
- [PEP 768 - Remote Debugging](https://peps.python.org/pep-0768/)
- [pdb documentation](https://docs.python.org/3/library/pdb.html)
- [Yama LSM Documentation](https://docs.kernel.org/admin-guide/LSM/Yama.html)
- [prctl(2) man page](https://man7.org/linux/man-pages/man2/prctl.2.html)

