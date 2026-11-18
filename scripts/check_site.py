"""Static check for the GitHub Pages site in docs/: every local href/src resolves to a file, every #anchor
exists on its target page, and pages load their scripts/styles. Exit 1 on any problem.

    python scripts/check_site.py            # local files only
    python scripts/check_site.py --external # also HEAD-check absolute https links
"""
import re
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urlparse

DOCS = Path(__file__).resolve().parent.parent / "docs"


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs, self.ids = [], set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        for k in ("href", "src"):
            if a.get(k):
                self.refs.append((tag, a[k]))


def parse(p: Path) -> Links:
    L = Links()
    L.feed(p.read_text(encoding="utf-8"))
    return L


def main() -> int:
    external = "--external" in sys.argv
    pages = sorted(DOCS.rglob("*.html"))
    parsed = {p: parse(p) for p in pages}
    problems, ext = [], set()
    for p, L in parsed.items():
        for tag, ref in L.refs:
            u = urlparse(ref)
            if u.scheme in ("http", "https"):
                ext.add(ref)
                continue
            if u.scheme in ("mailto", "tel", "data", "javascript") or ref == "#":
                continue
            path, frag = urldefrag(ref)
            target = p if not path else (p.parent / path)
            if target.is_dir():
                target = target / "index.html"
            if not target.exists():
                problems.append(f"{p.relative_to(DOCS)}: broken {tag} -> {ref}")
                continue
            if frag and target.suffix == ".html":
                ids = parsed.get(target.resolve(), parsed.get(target)) or parse(target)
                if frag not in ids.ids:
                    problems.append(f"{p.relative_to(DOCS)}: missing anchor #{frag} in {target.relative_to(DOCS)}")
    # resources fetched from JS
    for js in DOCS.rglob("*.js"):
        for m in re.finditer(r"fetch\(\"([^\"]+)\"\)", js.read_text(encoding="utf-8")):
            if not (DOCS / m.group(1)).exists():
                problems.append(f"{js.relative_to(DOCS)}: fetch target missing -> {m.group(1)}")
    if external:
        for url in sorted(ext):
            if "wa.me" in url:
                continue
            try:
                req = urllib.request.Request(url, method="GET", headers={"User-Agent": "Mozilla/5.0 link-check"})
                code = urllib.request.urlopen(req, timeout=20).status
            except Exception as e:  # noqa: BLE001
                code = getattr(e, "code", str(e))
            ok = code == 200 or (code in (999, 429) and "linkedin" in url)
            print(f"  {code}  {url}")
            if not ok:
                problems.append(f"external link {url} -> {code}")
    print(f"checked {len(pages)} pages, {sum(len(L.refs) for L in parsed.values())} links/assets, {len(ext)} external")
    for x in problems:
        print("PROBLEM:", x)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
