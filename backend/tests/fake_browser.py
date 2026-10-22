"""Stand-in browser for the desktop launcher test: records its arguments, 'closes' after a moment."""

import json
import os
import sys
import time

with open(os.environ["FAKE_BROWSER_ARGS"], "w", encoding="utf-8") as fh:
    json.dump(sys.argv[1:], fh)
time.sleep(float(os.environ.get("FAKE_BROWSER_SECONDS", "3")))
