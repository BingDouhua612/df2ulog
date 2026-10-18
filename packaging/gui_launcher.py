"""PyInstaller entry point: forwards to the real GUI module entry."""

import sys

from df2ulog.gui.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
