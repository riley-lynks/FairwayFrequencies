"""
Live preview watcher for the Golfquilizer.

Watches config.py for changes and reruns preview_golfquilizer.py automatically.
Keep output/golfquilizer_preview.png open in Windows Photos — it auto-refreshes.

Usage:
    python watch_golfquilizer.py
"""

import os
import sys
import time
import subprocess
sys.stdout.reconfigure(encoding='utf-8')

WATCH_FILE = "config.py"
PREVIEW_SCRIPT = "preview_golfquilizer.py"
CHECK_INTERVAL = 0.5  # seconds

def run_preview():
    result = subprocess.run(
        [sys.executable, PREVIEW_SCRIPT],
        capture_output=True, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode == 0:
        print(f"  [{time.strftime('%H:%M:%S')}] Preview updated → output/golfquilizer_preview.png")
    else:
        print(f"  [{time.strftime('%H:%M:%S')}] Error: {result.stderr[-200:]}")

print("Golfquilizer live preview watcher")
print(f"  Watching: {WATCH_FILE}")
print(f"  Output:   output/golfquilizer_preview.png")
print(f"  Open the PNG in Windows Photos and it will auto-refresh on each save.")
print(f"  Press Ctrl+C to stop.\n")

# Run once immediately
run_preview()

last_mtime = os.path.getmtime(WATCH_FILE)

try:
    while True:
        time.sleep(CHECK_INTERVAL)
        mtime = os.path.getmtime(WATCH_FILE)
        if mtime != last_mtime:
            last_mtime = mtime
            run_preview()
except KeyboardInterrupt:
    print("\nStopped.")
