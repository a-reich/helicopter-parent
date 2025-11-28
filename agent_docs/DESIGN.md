# Helicopter Parent - Design Document

## Project Overview

Helicopter Parent is a remote Python debugging system that enables users to attach a debugger to a running Python process on-demand. It leverages Python 3.14's new remote debugging capabilities (`pdb.attach()`) to provide an interactive debugging experience through a proxy architecture.

## Problem Statement

Developers often need to debug Python processes that are already running without:
- Restarting the process with a debugger
- Modifying the source code to add breakpoints
- Losing the current process state

Python 3.14 introduces `pdb.attach(pid)` which allows attaching to a running process, but requires direct access to that process. Helicopter Parent creates a wrapper architecture that allows users to:
1. Start a Python process under supervision
2. Connect from a separate interactive session later
3. Trigger debugging on-demand
4. Interact with the debugger as if directly attached

## Architecture

### Three-Process Model

```
┌─────────────────────────────────────────────────────────────┐
│                                                               │
│  Script A: controller.py (Parent/Proxy)                      │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ • Launches and monitors Script B                     │    │
│  │ • Creates and manages named pipes                    │    │
│  │ • Listens for debug commands from Script C          │    │
│  │ • Calls pdb.attach(B_PID) when requested            │    │
│  │ • Redirects pdb I/O to pipes for Script C          │    │
│  └─────────────────────────────────────────────────────┘    │
│         │                                                     │
│         │ spawns                                             │
│         ▼                                                     │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Script B: target.py (or any user script)            │    │
│  │ • The process being debugged                        │    │
│  │ • Runs normally until debugger attaches            │    │
│  │ • No special instrumentation needed                │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                               │
└─────────────────────────────────────────────────────────────┘
                         ▲
                         │ named pipes
                         │
┌────────────────────────┴──────────────────────────────────┐
│  Script C: client.py (Interactive Client)                  │
│  ┌──────────────────────────────────────────────────────┐ │
│  │ • Connects to controller via named pipes             │ │
│  │ • Sends debug commands (ATTACH, STATUS, QUIT)       │ │
│  │ • Routes user input to pdb session                  │ │
│  │ • Displays pdb output to user                       │ │
│  └──────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

### Component Responsibilities

#### Script A - Controller (`controller.py`)
**Role:** Process supervisor and I/O proxy

**Responsibilities:**
- Launch target process B and capture its PID
- Create named pipes for inter-process communication
- Monitor target process health
- Listen for commands from client C
- Execute `pdb.attach(target_pid)` when requested
- Redirect pdb's stdin/stdout/stderr to pipes
- Send status updates to client

**Key Design Decision:** Runs `pdb.attach()` in the main thread (blocks while debugging), rather than a separate thread, to avoid complex I/O redirection issues with process-wide sys.stdin/stdout/stderr globals.

#### Script B - Target (`target.py` or any Python script)
**Role:** The process being debugged

**Characteristics:**
- Can be any Python script or application
- Runs as a subprocess of controller
- No special instrumentation or modifications needed
- Continues running between debug sessions
- Can be debugged multiple times without restarting

#### Script C - Client (`client.py`)
**Role:** User interface for debugging

**Responsibilities:**
- Connect to controller via named pipes
- Provide interactive command interface
- Send debug triggers (ATTACH command)
- Route user input to debugger
- Display debugger output
- Handle status notifications

## Communication Protocol

### Named Pipes

All pipes located in: `/tmp/heli_debug/`

```
/tmp/heli_debug/
├── control      # C → A: Control commands
├── debug_in     # C → A → pdb: User input during debug session
├── debug_out    # pdb → A → C: Debugger output to user
└── status       # A → C: Status messages and notifications
```

### Control Commands (C → A)

| Command | Description | Response |
|---------|-------------|----------|
| `ATTACH` | Request debugger attachment to target | `ATTACHING` → `ATTACHED` or `ERROR` |
| `STATUS` | Query current state | `STATUS: RUNNING, Target PID: <pid>` |
| `QUIT` | Shutdown controller | Controller exits |

### Status Messages (A → C)

| Status | When Sent | Meaning |
|--------|-----------|---------|
| `STARTED: Target PID <pid>` | Target process launched | Target is running |
| `ATTACHING: PID <pid>` | Beginning attachment | About to call pdb.attach() |
| `ATTACHED: Debugger session active` | pdb.attach() called | Debug session ready |
| `DETACHED: Debugger session ended` | User quit pdb | Back to normal operation |
| `ERROR: <message>` | Error occurred | Operation failed |

### Debug I/O Flow

When debug session active:
```
User types in client → DEBUG_IN pipe → pdb stdin → target process
Target process → pdb stdout → DEBUG_OUT pipe → displayed to user
```

## Process Flow

### Startup Sequence

```
1. User runs: python controller.py target.py
2. Controller creates named pipes in /tmp/heli_debug/
3. Controller launches target.py as subprocess
4. Controller sends STARTED status
5. Controller enters command listening loop
6. Target runs normally
```

### Debug Attach Sequence

```
1. User runs: python client.py (in separate terminal)
2. Client connects to pipes
3. User types: attach
4. Client sends ATTACH to control pipe
5. Controller receives ATTACH command
6. Controller:
   a. Opens DEBUG_IN and DEBUG_OUT pipes
   b. Saves original sys.stdin/stdout/stderr
   c. Redirects sys.stdin/stdout/stderr to debug pipes
   d. Calls pdb.attach(target_pid)  [BLOCKS HERE]
7. Client receives ATTACHED status
8. Client opens DEBUG_IN/DEBUG_OUT pipes
9. User interacts with pdb through client
10. User types: quit (in pdb)
11. pdb.attach() returns
12. Controller restores original I/O
13. Controller sends DETACHED status
14. Controller returns to command listening loop
15. Target continues running normally
```

### Detach and Reattach

```
- User can quit pdb session (detach)
- Target continues running
- User can send ATTACH again later
- Debugger reattaches to same process (with updated state)
- Can inspect new variable values, stack state, etc.
```

## Key Design Decisions

### 1. PDB Attachment Method: `pdb.attach()` API

**Chosen Approach:** Use `pdb.attach(pid)` function directly in controller process

**Alternatives Considered:**
- ❌ Subprocess `python -m pdb -p <PID>`: Complex I/O redirection between processes
- ❌ Direct `sys.remote_exec()`: Too low-level, need to build debugging infrastructure

**Advantages:**
- pdb instance runs in controller's process
- Simple I/O redirection (just set sys.stdin/stdout before calling)
- Direct control over pdb lifecycle
- No subprocess management complexity

### 2. Threading Model: Main Thread Blocking

**Chosen Approach:** Run `pdb.attach()` in main thread (blocks during debug session)

**Alternative Considered:**
- ❌ Separate thread for pdb.attach(): Allows concurrent command handling

**Why Main Thread:**
- sys.stdin/stdout/stderr are process-wide globals (not thread-local)
- Redirecting in separate thread would affect entire process, causing race conditions
- Concurrent command handling not needed in practice (user is debugging, not sending other commands)
- Simpler code: ~100 fewer lines, no threading complexity
- Limitations are acceptable:
  - Cannot respond to STATUS while debugging (user knows they're debugging)
  - Cannot force-abort debug session (user can quit pdb or Ctrl+C)
  - Cannot detect target crash during debug (pdb handles this)

### 3. Named Pipes vs Sockets

**Chosen Approach:** Named pipes for local inter-process communication

**Advantages:**
- Simple for local debugging on same machine
- Filesystem-based (easy to check if controller is running)
- Low overhead

**Future Extension:** Could add TCP socket support for remote debugging

### 4. Single vs Multiple Debug Sessions

**Chosen Approach:** Single debug session at a time

**Rationale:**
- pdb.attach() itself only supports one debugger per process
- Simpler state management
- Matches typical debugging workflow

## Requirements

### Python Version
- **Python 3.14+** required
- Uses `pdb.attach()` function (new in 3.14)
- Uses PEP 768 remote debugging capabilities

### Platform
- **Linux/Unix** (named pipes)
- Could be adapted for Windows using named pipes (\\.\pipe\...) or sockets

### Permissions
- Controller must have permission to create files in `/tmp/heli_debug/`
- Must be able to attach to process (same user, or root)

## Error Handling

### Target Process Crashes
- Controller detects process exit via `poll()`
- Sends ERROR status to client
- If crash during debug: pdb.attach() will error and return

### Pipe Errors
- Status pipe: Ignore errors if client not connected (fire-and-forget)
- Control pipe: Retry with backoff on errors
- Debug pipes: Errors cause debug session to end gracefully

### pdb.attach() Failures
- Target process not found → Send ERROR status
- Permission denied → Send ERROR status
- Process blocked in I/O → pdb attaches but may be unresponsive until next bytecode instruction

### Python Version Mismatch
- Check version on startup
- Exit with clear error if < 3.14

## Limitations and Caveats

### 1. I/O Blocking Caveat (from Python docs)
> "Attaching to a remote process that is blocked in a system call or waiting for I/O will only work once the next bytecode instruction is executed or when the process receives a signal."

**Impact:** If target is blocked on I/O, debugger may not be immediately responsive

**Mitigation:** Target can be designed to avoid long blocking calls, or user can send signal

### 2. Single Debugger Session
- Only one client can debug at a time
- Second ATTACH request while debugging will return ERROR

### 3. Controller Blocking
- Controller cannot handle other commands while debug session active
- This is acceptable for intended use case

### 4. Local Only
- Current design uses named pipes (local machine only)
- Remote debugging would require socket-based implementation

## Future Enhancements

### Priority 1 (High Value)
- **Multiple target processes:** Controller manages multiple targets, client selects which to debug
- **Remote debugging:** Replace named pipes with TCP sockets
- **Python version detection:** Auto-detect and validate 3.14+

### Priority 2 (Nice to Have)
- **Session logging:** Record debug sessions for later review
- **Web UI:** Browser-based client instead of terminal
- **Target monitoring:** Display CPU, memory, thread info in client
- **Signal injection:** Send signals to unblock I/O-blocked targets

### Priority 3 (Advanced)
- **Multiple simultaneous clients:** Multiple users view same debug session (read-only)
- **Session persistence:** Save/restore debug state
- **Integration with existing tools:** IDE plugins, etc.

## Security Considerations

### Local Security
- Pipes in `/tmp/` are world-accessible by default
- Consider using `0700` permissions on `/tmp/heli_debug/`
- Or use user-specific directory: `/tmp/heli_debug_$USER/`

### Remote Security (if implemented)
- Authentication required for TCP socket version
- Encryption (TLS) for remote connections
- Access control (who can attach debugger)

## References

- [Python 3.14 What's New - pdb remote attaching](https://docs.python.org/3/whatsnew/3.14.html#pdb)
- [PEP 768 - Remote Debugging](https://peps.python.org/pep-0768/)
- `pdb.attach()` function documentation
- `sys.remote_exec()` function documentation

## Project Status

- **Current Phase:** Design Complete
- **Next Phase:** Implementation
- **Target Completion:** TBD
