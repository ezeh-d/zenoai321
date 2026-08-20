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

from reyes_agent.phone_security import DEVICE_KEY_AUTH, PhoneSecurity


class PhoneSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.security = PhoneSecurity(Path(self.temp.name) / "devices.sqlite")
    def tearDown(self) -> None:
        self.temp.cleanup()
    def test_pairing_is_one_time_and_only_a_hash_is_persisted(self) -> None:
        pair = self.security.create_pair()
        self.assertTrue(pair["manual_code"].isdigit())
        self.assertEqual(len(pair["manual_code"]), 6)
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

    def test_standing_mic_key_creates_a_usable_session(self) -> None:
        """The phone is a microphone, not a lesser principal.

        This asserted audio-only, and that made the remote microphone
        useless: every sentence was transcribed perfectly and then refused
        with "this device does not have the 'status' scope" -- ZENO could
        hear the owner and was not allowed to answer him. The grant now
        matches a passkey-verified device.
        """
        paired = self.security.pair_with_mic_key(
            self.security.mic_key(), "Test phone", peer_ip="127.0.0.1")
        session = self.security.session(paired["session"])
        self.assertEqual(session["auth_level"], DEVICE_KEY_AUTH)
        self.assertEqual(session["device_id"], paired["device_id"])
        scopes = set(self.security.devices()[0]["scopes"])
        self.assertIn("remote_audio_send", scopes)
        self.assertIn("status", scopes)      # may answer a question
        self.assertIn("talk", scopes)        # may act on an instruction

    def test_a_paired_phone_still_cannot_touch_money_or_credentials(self) -> None:
        """What did NOT widen, and cannot.

        Money movement and security changes are refused by CATEGORY, before
        scopes are consulted -- so no grant reaches them, and a lost phone
        still cannot start either one.
        """
        from reyes_agent.remote_access import policy

        self.security.pair_with_mic_key(
            self.security.mic_key(), "Test phone", peer_ip="127.0.0.1")
        scopes = set(self.security.devices()[0]["scopes"])
        for forbidden in ("transfer 500 to my brother", "change my password",
                          "disable the firewall"):
            self.assertFalse(policy.evaluate(forbidden, scopes=scopes).allowed,
                             forbidden)
        for allowed in ("what time is it", "open slack"):
            self.assertTrue(policy.evaluate(allowed, scopes=scopes).allowed,
                            allowed)
