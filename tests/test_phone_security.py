import sys
import tempfile
import unittest
from pathlib import Path

# Same bootstrap as every other module in tests/. Without it this file
# imports only when the repo root already happens to be on sys.path (e.g.
# under pytest rootdir discovery), and fails with ModuleNotFoundError when
# run directly the way the rest of the suite is run.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reyes_agent.phone_security import PhoneSecurity


class PhoneSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.security = PhoneSecurity(Path(self.temp.name) / "devices.sqlite")
    def tearDown(self) -> None:
        self.temp.cleanup()
    def test_pairing_is_one_time_and_only_a_hash_is_persisted(self) -> None:
        pair = self.security.create_pair()
        self.assertTrue(self.security._valid_pair(pair["token"]))
        with self.security._connection() as conn:
            row = conn.execute("SELECT token_hash FROM pairs").fetchone()
        self.assertNotIn(pair["token"], row["token_hash"])
        self.security.cancel_pair(pair["token"])
        self.assertFalse(self.security._valid_pair(pair["token"]))
    def test_command_nonce_and_id_are_single_use(self) -> None:
        self.assertTrue(self.security.claim_command("device", "command-a", "nonce-a"))
        self.assertFalse(self.security.claim_command("device", "command-a", "nonce-b"))
        self.assertFalse(self.security.claim_command("device", "command-b", "nonce-a"))
    def test_registration_options_require_a_valid_pair(self) -> None:
        pair = self.security.create_pair()
        options = self.security.registration_options(pair["token"], "Phone", "zeno.example.com")
        self.assertEqual(options["rp"]["id"], "zeno.example.com")
        self.assertEqual(options["authenticatorSelection"]["userVerification"], "required")
        manual = self.security.create_pair()
        options = self.security.registration_options(manual["manual_code"], "Phone", "zeno.example.com")
        self.assertTrue(options["challenge"])
