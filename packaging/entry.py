"""PyInstaller entry point (keeps the frozen app's main module simple)."""

import sys

from quirewright.app import main

if __name__ == "__main__":
    sys.exit(main())
