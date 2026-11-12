#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/static"
if command -v esbuild >/dev/null 2>&1; then ES=(esbuild); else ES=(npx --yes esbuild); fi
mkdir -p built
digest() { sha1sum "$1" | cut -c1-10; }
build() {
  local src="$1" out="$2"; shift 2
  "${ES[@]}" "$src" --minify --charset=utf8 --legal-comments=none "$@" --outfile="built/$out" --log-level=error
}
build app.js app.min.js --target=es2019
build i18n.js i18n.min.js --target=es2019
build style.css style.min.css
printf '{\n  "app.js": {"src": "%s", "out": "app.min.js"},\n  "i18n.js": {"src": "%s", "out": "i18n.min.js"},\n  "style.css": {"src": "%s", "out": "style.min.css"}\n}\n' \
  "$(digest app.js)" "$(digest i18n.js)" "$(digest style.css)" > built/manifest.json
ls -l built
