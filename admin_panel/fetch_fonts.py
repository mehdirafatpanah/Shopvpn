"""Downloads the panel fonts from Google Fonts once and writes static/fonts/fonts.css so the panel serves them itself."""

import hashlib
import os
import re
import sys
import urllib.request

FONTS_URL = (
    "https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;500;600;700;800"
    "&family=JetBrains+Mono:wght@400;500;700&family=Chakra+Petch:wght@500;600;700&display=swap"
)
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "fonts")
URL_RE = re.compile(r"url\((https://[^)]+\.woff2)\)")


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def localize(css: str, download) -> str:
    """Rewrites every remote woff2 url in css to /assets/fonts/<hash>.woff2, calling download(url, filename) for each."""
    mapping = {}
    for url in URL_RE.findall(css):
        if url not in mapping:
            mapping[url] = hashlib.sha1(url.encode()).hexdigest()[:12] + ".woff2"
    for url, name in mapping.items():
        download(url, name)
        css = css.replace(url, "/assets/fonts/" + name)
    return css


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    css = fetch(FONTS_URL).decode("utf-8")

    def download(url, name):
        with open(os.path.join(OUT_DIR, name), "wb") as f:
            f.write(fetch(url))

    local_css = localize(css, download)
    with open(os.path.join(OUT_DIR, "fonts.css"), "w", encoding="utf-8") as f:
        f.write(local_css)
    print(f"done: {len(URL_RE.findall(css))} font files in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
