import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
# Ensure project root is on ``sys.path`` so tests can import the package
sys.path.append(str(root))

# Also expose the project root on ``PATH`` so the ``ib-rebalance`` console
# script located in the repository can be executed by tests.  In normal use
# this script would be installed into a virtualenv's ``bin`` directory, but in
# the test environment we run the package in-place without installation.
os.environ["PATH"] = f"{root}{os.pathsep}" + os.environ.get("PATH", "")
