import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AuthenticationFrontendUxTests(unittest.TestCase):
    def test_unverified_login_offers_activation_link_resend(self):
        markup = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
        dom = (ROOT / "frontend/js/dom.js").read_text(encoding="utf-8")
        auth = (ROOT / "frontend/js/auth.js").read_text(encoding="utf-8")

        self.assertIn('id="resendVerificationBtn"', markup)
        self.assertIn("resendVerificationBtn", dom)
        self.assertIn("err.status === 403", auth)
        self.assertIn('apiFetch("/api/verification/resend"', auth)
        self.assertIn("JSON.stringify({ login })", auth)


if __name__ == "__main__":
    unittest.main()
