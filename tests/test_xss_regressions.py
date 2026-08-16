import json
import os
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
USERNAME_PAYLOAD = '" onmouseover=alert(1) x="'
TOKEN_PAYLOAD = '"><script>alert(1)</script>'


class ElementParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


def parse_elements(html):
    parser = ElementParser()
    parser.feed(html)
    return parser.elements


class XssRegressionTests(unittest.TestCase):

    def test_turnstile_tokens_are_not_logged(self):
        auth_js = Path(ROOT, "frontend", "js", "auth.js").read_text(
            encoding="utf-8"
        )
        for line in auth_js.splitlines():
            lowered = line.lower()
            if "console." in lowered:
                self.assertFalse(
                    "turnstile" in lowered or "token" in lowered,
                    line,
                )

    def test_username_stays_inside_data_attribute(self):
        script = f"""
const elements = new Map();
const element = (id) => elements.get(id) || null;
for (const id of ["searchAccInput", "searchResults", "publicStringsList", "searchView"]) {{
  elements.set(id, {{
    value: "payload",
    innerHTML: "",
    style: {{}},
    addEventListener() {{}},
  }});
}}
globalThis.document = {{
  getElementById: element,
  addEventListener() {{}},
  querySelector() {{ return null; }},
  querySelectorAll() {{ return []; }},
}};
globalThis.fetch = async (url) => ({{
  ok: true,
  async json() {{
    if (url.startsWith("/api/public/search")) {{
      return {{ items: [{{ id: 1, username: {json.dumps(USERNAME_PAYLOAD)} }}] }};
    }}
    return {{
      user: {{ id: 1, username: {json.dumps(USERNAME_PAYLOAD)} }},
      items: [{{ id: 2, content: "v1\\n@user\\n\\nbody", created_at: null }}],
    }};
  }},
}});

const publicModule = await import("./frontend/js/public.js");
await publicModule.runSearch();
const searchHtml = elements.get("searchResults").innerHTML;
await publicModule.loadPublicThoughtsByUsername({json.dumps(USERNAME_PAYLOAD)});
const profileHtml = elements.get("publicStringsList").innerHTML;
process.stdout.write(JSON.stringify({{ searchHtml, profileHtml }}));
"""
        result = subprocess.run(
            [
                "node",
                "--experimental-default-type=module",
                "--input-type=module",
                "-e",
                script,
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        rendered = json.loads(result.stdout)

        for html, tag in (
            (rendered["searchHtml"], "button"),
            (rendered["profileHtml"], "div"),
        ):
            matching = [attrs for parsed_tag, attrs in parse_elements(html) if parsed_tag == tag and "data-username" in attrs]
            self.assertEqual(len(matching), 1)
            self.assertNotIn("onmouseover", matching[0])
            self.assertEqual(matching[0]["data-username"], USERNAME_PAYLOAD)

    def test_reset_token_stays_inside_value_attribute(self):
        os.environ.setdefault("ETH_PK", "0x" + "1" * 64)
        from app.routers.auth import reset_password_page

        elements = parse_elements(reset_password_page(TOKEN_PAYLOAD))
        self.assertFalse(any(tag == "script" for tag, _ in elements))

        token_inputs = [
            attrs
            for tag, attrs in elements
            if tag == "input" and attrs.get("name") == "token"
        ]
        self.assertEqual(len(token_inputs), 1)
        self.assertEqual(token_inputs[0]["value"], TOKEN_PAYLOAD)


if __name__ == "__main__":
    unittest.main()
