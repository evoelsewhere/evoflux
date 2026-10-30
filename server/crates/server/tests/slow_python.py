"""Delays its handshake, then runs the gateway's fake upstream (handshake wait test)."""

import os
import runpy
import sys
import time
from pathlib import Path

print("slow python warming up", flush=True)
time.sleep(float(os.environ.get("EVOFLUX_TEST_HANDSHAKE_DELAY_S", "3")))
entry = Path(__file__).resolve().parents[4] / "contract-tests" / "gateway" / "fake_upstream.py"
sys.argv[0] = str(entry)
runpy.run_path(str(entry), run_name="__main__")
