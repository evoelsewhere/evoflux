"""Logs a few lines and never prints a handshake (slow first start test)."""

import sys
import time

print("migrating database step 1", flush=True)
print("never_ready last log line", file=sys.stderr, flush=True)
time.sleep(120)
