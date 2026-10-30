"""Prints a log line and never a handshake (supervisor timeout test)."""

import time

print("no handshake here", flush=True)
time.sleep(60)
