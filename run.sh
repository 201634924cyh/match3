#!/usr/bin/env bash
# Match-3 launcher for macOS / Linux.
set -u
cd "$(dirname "$0")" || exit 1

if [ ! -f match3.py ]; then
    echo "match3.py is missing in this folder: $(pwd)" >&2
    exit 1
fi

for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        exec "$candidate" match3.py "$@"
    fi
done

echo "Python 3 not found. Install it first, then run this again." >&2
exit 1
