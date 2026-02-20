# Releasing

Use this when creating a shareable source archive.

## Build release zip

```bash
cd /srv/lms/app
bash scripts/make_release_zip.sh
```

Optional output path:

```bash
bash scripts/make_release_zip.sh /srv/lms/releases/classhub_release.zip
```

## What is excluded

Release archives intentionally exclude local/runtime artifacts, including:

- `.git/`
- `.venv/`
- `__pycache__/`
- `media/`
- `staticfiles/`
- `dist/`
- common OS metadata (`.DS_Store`, `__MACOSX`)

## Verify artifact contents locally

```bash
export ZIP_PATH="$(ls -t dist/classhub_release_*.zip | head -n1)"
python3 - <<'PY'
from pathlib import PurePosixPath
from zipfile import ZipFile
import os

zip_path = os.environ["ZIP_PATH"]
blocked_parts = {".git", ".venv", "__pycache__", "media", "staticfiles"}
bad = []
with ZipFile(zip_path) as zf:
    for name in zf.namelist():
        parts = PurePosixPath(name).parts
        if any(part in blocked_parts for part in parts):
            bad.append(name)
if bad:
    print("FAIL:")
    for row in bad:
        print(row)
    raise SystemExit(1)
print("OK")
PY
```
