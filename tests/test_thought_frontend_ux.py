import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ThoughtFrontendUxTests(unittest.TestCase):
    def run_node(self, script):
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
        return result.stdout

    def test_owner_route_is_distinct_from_public_route(self):
        output = self.run_node(
            """
globalThis.window = { location: { pathname: "/own/thoughts/42" } };
const { parseRoute } = await import("./frontend/js/router.js");
process.stdout.write(JSON.stringify(parseRoute()));
"""
        )
        self.assertEqual(
            json.loads(output),
            {"type": "own-thought", "thoughtId": "42"},
        )

        source = (ROOT / "frontend/js/thoughts.js").read_text(encoding="utf-8")
        self.assertIn("/own/thoughts/", source)
        self.assertNotIn("?from=overview`;", source.split("/own/thoughts/", 1)[0])

    def test_delivery_state_is_not_added_to_visible_markup(self):
        detail = (ROOT / "frontend/js/detail.js").read_text(encoding="utf-8")
        thoughts = (ROOT / "frontend/js/thoughts.js").read_text(encoding="utf-8")
        styles = (ROOT / "frontend/css/views.css").read_text(encoding="utf-8")

        self.assertNotIn("Confirming —", detail)
        self.assertNotIn('meta-label\">status', detail)
        self.assertNotIn("Available after final confirmation", detail)
        self.assertNotIn("stringItemStatus", thoughts)
        self.assertNotIn(".stringItemStatus", styles)
        self.assertIn('>copy link</button>', detail)
        self.assertIn('showMsg(`saved!`, 3000)', thoughts)

    def test_public_link_is_immediate_and_owner_polling_is_bounded(self):
        detail = (ROOT / "frontend/js/detail.js").read_text(encoding="utf-8")
        thoughts = (ROOT / "frontend/js/thoughts.js").read_text(encoding="utf-8")

        self.assertNotIn('public_ready', detail)
        self.assertNotIn('if (!publicUrl) return', detail)
        self.assertIn('TERMINAL_STATUSES = new Set(["mined", "reverted", "failed"])', thoughts)
        self.assertIn("OWNER_POLL_INTERVAL_MS = 4000", thoughts)
        self.assertIn("document.hidden", thoughts)
        self.assertIn("updateThoughtDetail(data)", thoughts)
        self.assertNotIn("created.id", thoughts)
        self.assertIn("await refreshStringsList()", thoughts)
        self.assertIn("setTimeout(() => closePostModal(), 900)", thoughts)


if __name__ == "__main__":
    unittest.main()
