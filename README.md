# helicopter-parent - Helper for External Python Debugging with Linux Security Restrictions  

Python 3.14's [PEP 768](https://peps.python.org/pep-0768/) feature and accompanying `pdb` capability support on-demand external debugging for Python processes, but common Linux security restrictions make this awkward to use (without root privileges) for long jobs. This is a lightweight helper that manages processes for you to make the experience effectively as user-friendly as without the system restrictions: it can run any Python job and lets you launch a REPL from which you can debug it with Pdb. 

## Overview

`helicopter-parent` allows you to:
- Start a Python job under supervision; it does not have to remain connected to an interactive terminal
- Attach a debugger to it later from a separate client session
- Debug interactively with full pdb features
- Detach and reattach multiple times
- Terminate the Python job and parent when ready

## Requirements

- **Python 3.14+** (uses `sys.remote_exec()` and `pdb.attach()` from PEP 768)
- **Linux with Yama LSM** (uses `prctl(PR_SET_PTRACER)`; MacOS doesn't support full ptrace features)
- **ptrace_scope ≤ 1** (check with `cat /proc/sys/kernel/yama/ptrace_scope`; if 0 `helicopter-parent` is not necessary)
- **Same user** running both supervisor and client

## Quick Start

### Terminal 1: Start the Supervisor

```bash
helicopter-parent target.py
```

This starts the supervisor which itself launches `target.py` as a subprocess, and then waits for a client to connect.

### Terminal 2: Connect the Client

```bash
helicopter-client
```
This will attempt to connect to the running supervisor and then display an interactive command prompt. The client commands are:
- `attach` - Attach debugger to the target process
- `quit` - Exit client (leave supervisor running)
- `terminate` - Stop supervisor, target, and exit client
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

(Pdb) quit

Debugger detached
>>> quit
Exiting client (supervisor and target still running)
```

## Technical details

This section should not be necessary in order to use the helper, but is relevant if you'd like to know more about the underlying Operating Sytem feature, the restrictions under which `helicopter-parent` is valuable, and its internal design. 

### Background and Purpose
The feature introduced in PEP 768 uses OS-level capabilities that allow to interrupt a running process from the outside and execute any code within it; on Unix platforms the system call for this is named `ptrace` (there's a similar feature on Windows which is out of scope here.) The new feature essentially created a bridge between low-level native code and Python sessions, so that the debugger can understand the Python state of the target process, hook into the interpreter to have it execute the user's code, and send results back.

This is very useful if one doesn't control the full code getting run so the traditional method of inserting breakpoints into the actual source code to trigger debuggers at certain points doesn't work, or if one doesn't know in advance before the job is run whether or where to halt it for debugging but wants to be able to "on the fly" if it shows concerning behavior. 

Because the `ptrace` capability is very powerful, many distributions include a Linux Security Module defining a setting, `ptrace_scope`, that restricts which processes can call it on a particular target. The options are:

- 0, AKA "classic" ptrace permissions: A process can be traced by any other process owned by the same user.
- 1, "restricted": Can only be traced by its own parent process and ancestors; or processes it has explicitly registered permission for.
- 2, "admin-only": Tracing requires special privileges typically set only for the root user (who can also trace under the settings above.)
- 3, "no attach": Tracing is disabled.

The goal of `helicopter-parent` is to help with **case 1**.
In this situation, if you want to be able to debug your Python job as a non-root user, it is rather awkward. You _could_ do so as the parent process - i.e. from an interactive REPL, use `subprocess` to launch Python with some script, then whenever needed call `pdb.attach()` to enter a PDB session. _But_, that method has the disadvantage that the originating session must be kept for as long as you might need to debug the job, which is inconvenient for long-running jobs (not to mention one might accidentally close the tab/window.). 

The advantage of `helicopter-parent` is that it can run _in the background_ and detect a client REPL that you launch _whenever you want_, arranging permission for you to attach from there. 

### Security


### Architecture


```
┌──────────────┐        ┌──────────────┐         ┌──────────────┐
│  supervisor  │        │    Target    │         │    Client    │
│              │        │   (Process   │         │              │
│ supervisor.py│        │  to debug)   │         │  client.py   │
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
  ├─ control ───► (Client → Supervisor)
  └─ response ──► (Supervisor → Client)
```

### How It Works

1. **Supervisor** spawns target process
2. **Client** connects and sends `GRANT_ACCESS <client_pid>`
3. **Supervisor** uses `sys.remote_exec(target_pid, script)` to inject:
   ```python
   prctl(PR_SET_PTRACER, client_pid)  # Grant permission
   ```
4. **Client** can now call `pdb.attach(target_pid)` directly
5. **User** interacts with native pdb in their terminal


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



## References

- [Python 3.14 What's New - pdb](https://docs.python.org/3/whatsnew/3.14.html#pdb)
- [PEP 768 - Remote Debugging](https://peps.python.org/pep-0768/)
- [pdb documentation](https://docs.python.org/3/library/pdb.html)
- [Yama LSM Documentation](https://docs.kernel.org/admin-guide/LSM/Yama.html)
- [prctl(2) man page](https://man7.org/linux/man-pages/man2/prctl.2.html)

