"""Arguments for running external tools (git, bundle) from the app.

A windowed Windows build has no console, so each console program it starts
opens a console window of its own unless created with ``CREATE_NO_WINDOW``.
Such a build can also have invalid standard handles: a call that redirects
stdout/stderr but not stdin makes Python duplicate the invalid stdin, which
fails with ``WinError 6`` before the child starts. Calls that redirect output
therefore pass ``stdin=subprocess.DEVNULL`` as well as this flag.
"""

import subprocess
import sys

#: ``creationflags`` for a console program started from the GUI; 0 off Windows.
NO_CONSOLE_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
