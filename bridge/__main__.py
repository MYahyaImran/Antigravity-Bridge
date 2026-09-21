"""Allow running Antigravity Bridge directly via `python -m bridge`."""
import sys
from bridge.cli import main

if __name__ == "__main__":
    sys.exit(main() or 0)
