#!/bin/sh
set -eu

backup=${1:?usage: restore_drill.sh BACKUP SECRET_FILE CLEAN_DIRECTORY}
secret_file=${2:?usage: restore_drill.sh BACKUP SECRET_FILE CLEAN_DIRECTORY}
target=${3:?usage: restore_drill.sh BACKUP SECRET_FILE CLEAN_DIRECTORY}
[ -r "$backup" ] || { echo "backup is not readable" >&2; exit 2; }
[ -r "$secret_file" ] || { echo "secret file is not readable" >&2; exit 2; }
mkdir -p "$target"
umask 077
tmp=$(mktemp "$target/.restore.XXXXXX.zip")
trap 'rm -f "$tmp"' EXIT
openssl enc -d -aes-256-cbc -pbkdf2 -in "$backup" -out "$tmp" -pass "file:$secret_file"
unzip -q -o "$tmp" -d "$target"
"${PYTHON:-python3}" - "$target" <<'PY'
import hashlib
import json
import pathlib
import sys
root = pathlib.Path(sys.argv[1])
manifest = json.loads((root / "manifest.json").read_text())
for entry in manifest["stores"].values():
    data = (root / entry["file"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise SystemExit(f"checksum mismatch: {entry['file']}")
print(f"restore drill verified {len(manifest['stores'])} stores")
PY
