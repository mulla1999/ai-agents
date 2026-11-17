#!/bin/sh
# Zip the browser extension into the web app (served at /hirefinch-extension.zip).
#
# The committed manifest lets the extension talk to localhost and *.trycloudflare.com only. When this
# server has its own fixed https address (data/public_url, written by deploy/home-up.sh), it is added
# to the packaged copy here, so a live address never has to be committed.
set -eu

HERE=$(cd "$(dirname "$0")/.." && pwd)    # apps/hirefinch
OUT="$HERE/frontend/public/hirefinch-extension.zip"
BUILD=$(mktemp -d)
trap 'rm -rf "$BUILD"' EXIT

cd "$HERE/extension"
cp -r manifest.json background.js popup.html popup.js options.html options.js ui.css lib icons "$BUILD/"

URL=$(cat "$HERE/data/public_url" 2>/dev/null || true)
python3 - "$BUILD/manifest.json" "$URL" <<'EOF'
import json, sys
from urllib.parse import urlsplit

path, url = sys.argv[1], sys.argv[2].strip()
parts = urlsplit(url)
if parts.scheme == "https" and parts.hostname and not parts.hostname.endswith(".trycloudflare.com"):
    manifest = json.load(open(path))
    matches = manifest["externally_connectable"]["matches"]
    origin = f"https://{parts.hostname}/*"
    if origin not in matches:
        matches.insert(0, origin)
    json.dump(manifest, open(path, "w"), indent=2)
    print(f"extension: allowed {parts.hostname}")
EOF

rm -f "$OUT"
cd "$BUILD" && zip -qr -X "$OUT" .
