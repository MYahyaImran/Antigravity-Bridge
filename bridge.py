#!/usr/bin/env python3
"""
Antigravity Multi-Account Bridge CLI Launcher.
Runs the CLI entry point from bridge.cli.
"""
import sys
from pathlib import Path

# Ensure the package root is on sys.path when invoked directly as a script
package_root = Path(__file__).resolve().parent
if str(package_root) not in sys.path:
    sys.path.insert(0, str(package_root))

from bridge.cli import main

if __name__ == "__main__":
    sys.exit(main() or 0)
