# Helicopter Parent - Usage Guide

## Quick Start with Python 3.14

All commands below use Python 3.14, which is required for the `pdb.attach()` feature.

### Terminal 1: Start the Controller

```bash
/home/asaf/.local/bin/python3.14 controller.py target.py
```

Expected output:
```
Created pipes in /tmp/heli_debug
Starting target process: /home/asaf/.local/bin/python3.14 target.py
Target process started with PID: 12345
Listening for commands on control pipe...
[TARGET-OUT] Target process started (PID: 12345)
[TARGET-OUT] Starting work loop...
[TARGET-OUT] Iteration 1: result = 2
[TARGET-OUT] Iteration 2: result = 4
...
```

### Terminal 2: Connect the Client and Debug

```bash
/home/asaf/.local/bin/python3.14 client.py
```

Expected output and interaction:
```
Helicopter Parent - Debug Client
==================================================
Commands: attach, status, quit
--------------------------------------------------
>>> status
[STATUS] STATUS: RUNNING, Target PID: 12345

>>> attach
[STATUS] ATTACHING: PID 12345
[STATUS] ATTACHED: Debugger session active
Debugger attached successfully
> /home/asaf/helicopter_parent/target.py(16)work_loop()
-> counter += 1
(Pdb)
```

### In the Debugger (Pdb)

Try these commands:

```python
(Pdb) list
 11         def work_loop():
 12             """Simulate some work being done."""
 13             counter = 0
 14             while True:
 15                 counter += 1
 16  ->             result = counter * 2
 17                 print(f"Iteration {counter}: result = {result}", flush=True)
 18                 time.sleep(2)

(Pdb) p counter
42

(Pdb) p result
84

(Pdb) where
  /home/asaf/helicopter_parent/target.py(27)main()
-> work_loop()
> /home/asaf/helicopter_parent/target.py(16)work_loop()
-> counter += 1

(Pdb) next
> /home/asaf/helicopter_parent/target.py(17)work_loop()
-> result = counter * 2

(Pdb) next
> /home/asaf/helicopter_parent/target.py(18)work_loop()
-> print(f"Iteration {counter}: result = {result}", flush=True)

(Pdb) continue
# Target continues running...

(Pdb) quit
[STATUS] DETACHED: Debugger session ended
>>>
```

### Testing Reattach

After quitting the debugger, you can attach again:

```
>>> attach
[STATUS] ATTACHING: PID 12345
[STATUS] ATTACHED: Debugger session active
Debugger attached successfully
> /home/asaf/helicopter_parent/target.py(16)work_loop()
-> counter += 1
(Pdb) p counter
156
# Note: counter value increased while target was running!
(Pdb) quit
```

### Cleanup

In the client:
```
>>> quit
Goodbye!
```

In the controller (Terminal 1):
- Press Ctrl+C or
- The controller will exit when client sends QUIT

## Using with Your Own Scripts

Replace `target.py` with any Python script:

```bash
# Terminal 1
/home/asaf/.local/bin/python3.14 controller.py my_script.py --arg1 value --arg2 value

# Terminal 2
/home/asaf/.local/bin/python3.14 client.py
>>> attach
(Pdb) # Debug your script!
```

## Common PDB Commands

| Command | Shortcut | Description |
|---------|----------|-------------|
| `list` | `l` | Show source code around current line |
| `where` | `w` | Show stack trace |
| `print <expr>` | `p <expr>` | Evaluate and print expression |
| `next` | `n` | Execute current line, step over functions |
| `step` | `s` | Execute current line, step into functions |
| `continue` | `c` | Continue execution until breakpoint |
| `break <line>` | `b <line>` | Set breakpoint at line number |
| `up` | `u` | Move up one stack frame |
| `down` | `d` | Move down one stack frame |
| `quit` | `q` | Detach debugger (target keeps running) |

## Troubleshooting

### Version Check Failed

If you see "Python 3.14+ required":
```bash
# Use the full path to Python 3.14
/home/asaf/.local/bin/python3.14 controller.py target.py
```

### Pipes Already Exist

If you see errors about existing pipes:
```bash
rm -rf /tmp/heli_debug
```
Then restart the controller.

### Target Not Responsive

If the debugger attaches but commands don't work, the target might be blocked in I/O.
This is a Python limitation - the debugger will become responsive at the next bytecode instruction.

### Client Can't Connect

Make sure the controller is running first. Check Terminal 1 for the controller output.

## Example: Debugging a Web Server

```python
# myserver.py
from http.server import HTTPServer, BaseHTTPRequestHandler
import os

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # You can attach debugger and inspect requests here!
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Hello!")

server = HTTPServer(('', 8000), Handler)
print(f"Server PID: {os.getpid()}")
server.serve_forever()
```

```bash
# Terminal 1
/home/asaf/.local/bin/python3.14 controller.py myserver.py

# Terminal 2
/home/asaf/.local/bin/python3.14 client.py
>>> attach

# Terminal 3
curl http://localhost:8000

# Terminal 2 (in pdb)
(Pdb) # Execution paused in request handler!
(Pdb) p self.path
'/'
(Pdb) continue
# Request completes
```

## Next Steps

- Read [DESIGN.md](DESIGN.md) for architecture details
- Read [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for implementation details
- Try debugging your own long-running processes!
