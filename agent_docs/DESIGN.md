# Helicopter Parent Architecture

## Overview

Helicopter Parent is a remote debugging system for Python 3.14+ that allows you to attach a debugger to a running Python process. It uses Linux's ptrace mechanism with Yama security module integration to enable secure debugging across process boundaries.

## Architecture

The system consists of three components:

1. **Controller** - Manages the target process and grants ptrace permissions
2. **Client** - Interactive debugger interface using `pdb.attach()`
3. **Target** - The Python process being debugged

### Communication

The system uses **2 named pipes** for communication:

```
/tmp/heliparent_debug/
├── control      # Client → Controller: Commands
└── response     # Controller → Client: Responses
```

## How It Works

### 1. Initialization

```
Controller                Client                Target
    |                        |                     |
    |--- Launch -----------→ |                     |
    |                        |                     |
    |--- Create pipes        |                     |
    |                        |                     |
    |                        |← Connect            |
    |                        |                     |
    |←- GET_TARGET_PID ------|                     |
    |--- TARGET_PID 12345 →  |                     |
```

### 2. Debugging Session

```
Client                 Controller              Target
  |                         |                     |
  |--- GRANT_ACCESS 67890 -→|                     |
  |                         |                     |
  |                         |--- remote_exec ---→ |
  |                         |    prctl(client)    |
  |                         |                     |
  |← READY -----------------|                     |
  |                         |                     |
  |--- pdb.attach(12345) ------------------------→|
  |                         |                     |
  |←------ Debug Session (direct ptrace) --------→|
```

### 3. Permission Grant Details

When the client requests to attach:

1. Client sends `GRANT_ACCESS <client_pid>` command
2. Controller uses `sys.remote_exec()` to inject code into target
3. Injected code calls `prctl(PR_SET_PTRACER, client_pid)`
4. This tells Yama to allow the client to ptrace the target
5. Controller responds with `READY`
6. Client directly calls `pdb.attach(target_pid)`

The ptrace connection is **direct** between client and target - no I/O redirection needed.

## Commands

The client supports these interactive commands:

- `attach` - Request permission and attach debugger to target
- `quit` - Exit client (leaves controller and target running)
- `terminate` - Stop controller, target, and exit client
- `help` - Show command help

## Command Protocol

### Client → Controller (Control Pipe)

- `GET_TARGET_PID` - Request the target process PID
- `GRANT_ACCESS <pid>` - Request ptrace permission for client PID
- `TERMINATE` - Stop controller and target

### Controller → Client (Response Pipe)

- `TARGET_PID <pid>` - Target process PID
- `READY` - Permission granted, ready to attach
- `ERROR: <message>` - Error occurred

## Technical Details

### PR_SET_PTRACER

The system uses the Linux Yama security module's `PR_SET_PTRACER` option:

```python
PR_SET_PTRACER_BINARY = int.from_bytes(b'Yama')  # 0x59616d61
libc.prctl(PR_SET_PTRACER_BINARY, client_pid, 0, 0, 0)
```

This allows the target to explicitly grant ptrace permission to a specific process, bypassing Yama's default restrictions.

### sys.remote_exec()

Python 3.14's `sys.remote_exec()` allows executing a Python script in another Python process:

```python
sys.remote_exec(target_pid, script_path)
```

The controller uses this to inject the `prctl()` call into the target process without interrupting its execution.

### Direct pdb.attach()

Once permission is granted, the client uses Python 3.14's native `pdb.attach()`:

```python
pdb.attach(target_pid)
```

This provides a native pdb debugging experience with full terminal control, readline support, and proper signal handling.

## Example Session

### Terminal 1 (Controller)
```bash
$ python controller.py target.py
Created pipes in /tmp/heliparent_debug
Starting target process: python target.py
Target process started with PID: 12345
Listening for commands on control pipe...
Received command: GET_TARGET_PID
Received command: GRANT_ACCESS 67890
Granting ptrace permission to client PID 67890...
Permission granted to client PID 67890
```

### Terminal 2 (Client)
```bash
$ python client.py
Client PID: 67890
Connecting to controller...
Target PID: 12345

Helicopter Parent - Debug Client
==================================================
Commands: attach, quit, terminate
--------------------------------------------------
>>> attach
Requesting ptrace permission for client PID 67890...
✅ Permission granted

Attaching pdb to target PID 12345...
Type pdb commands (list, next, print, etc.) or 'quit' to detach

> /home/user/target.py(44)work_loop()
-> counter += 1
(Pdb) list
(Pdb) print(counter)
42
(Pdb) next
> /home/user/target.py(45)work_loop()
-> n = random.randint(10**5, 10**6)
(Pdb) quit

Debugger detached
>>> quit
Exiting client (controller and target still running)
Goodbye!
```

## Design Philosophy

### Simplicity
- Minimal moving parts
- Direct ptrace connection (no I/O redirection)
- Simple command protocol
- Single-threaded design

### Security
- Explicit permission grant per attachment
- Temporary permission scripts are cleaned up
- Named pipes with restricted permissions (0600)
- Process isolation maintained

### Robustness
- Non-blocking pipe operations where appropriate
- Timeout handling for responses
- Graceful cleanup on exit
- Error reporting without crashing

## Requirements

- Python 3.14+ (for `pdb.attach()` and `sys.remote_exec()`)
- Linux with Yama LSM (most modern distributions)
- `/proc/sys/kernel/yama/ptrace_scope` ≤ 1

## Limitations

- Linux-only (uses prctl and Yama LSM)
- Python 3.14+ required
- Cannot debug processes that have crashed
- Single client at a time (shared pipes)