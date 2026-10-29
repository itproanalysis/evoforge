"""Compare default Korean desktop SSR copy, not generated artifact contents.

Needs the saved pre-redesign HTML and current SSR review in .local/design-review.
This is a repeatable text budget, not a screenshot or browser visibility test.
"""
from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path


class DefaultDesktopCopy(HTMLParser):
    def __init__(self, canvas: bool):
        super().__init__(convert_charrefs=True)
        self.canvas = canvas
        self.stack: list[dict] = []
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        parent = self.stack[-1] if self.stack else {"hidden": False, "details": False}
        classes = attr.get("class", "").split()
        hidden = (
            parent["hidden"] or (parent["details"] and tag != "summary")
            or tag in {"script", "style", "svg"} or "hidden" in attr
            or attr.get("aria-hidden") == "true" or "sr-only" in classes
            or "md:hidden" in classes or (tag == "dialog" and "open" not in attr)
            or (self.canvas and "studio-topbar" in classes)
        )
        if not hidden and attr.get("placeholder"):
            self.parts.append(attr["placeholder"])
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append({"tag": tag, "hidden": hidden, "details": tag == "details" and "open" not in attr})

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                self.stack = self.stack[:index]
                break

    def handle_data(self, data):
        if self.stack and not self.stack[-1]["hidden"] and not self.stack[-1]["details"]:
            self.parts.append(data)


def main():
    directory = Path(__file__).resolve().parents[3] / ".local" / "design-review"
    documents = []
    for filename, canvas in [("before-canvas.html", False), ("index.html", True)]:
        data = (directory / filename).read_bytes()
        parser = DefaultDesktopCopy(canvas)
        parser.feed(data.decode("utf-8"))
        text = re.sub(r"\s+", "", "".join(parser.parts))
        documents.append({"file": filename, "sha256": hashlib.sha256(data).hexdigest(), "characters": len(text), "copy": text})
    assert documents[0]["characters"] > 0
    reduction = 1 - documents[1]["characters"] / documents[0]["characters"]
    report = {
        "method": "Default/empty Korean desktop SSR visible copy and placeholders. Excludes hidden mobile navigation, screen-reader labels, closed details/dialogs, styles and SVG. The canvas-hidden global header is excluded. No generated output is counted; not browser screenshot proof.",
        "baseline_code": "333d88d9",
        "before_characters": documents[0]["characters"],
        "after_characters": documents[1]["characters"],
        "reduction_percent": round(reduction * 100, 1),
        "documents": documents,
    }
    (directory / "text-density.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Default copy: {documents[0]['characters']} -> {documents[1]['characters']} characters; {reduction:.1%} reduction.")
    assert reduction >= .8, "Default interface copy exceeds the owner's 20 percent budget"


if __name__ == "__main__":
    main()
