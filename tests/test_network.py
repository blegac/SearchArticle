"""Unit tests for the network layer (network.py) and the institution config."""

import tempfile
import unittest
from unittest.mock import MagicMock, patch

from searcharticle import network
from searcharticle.config import AppConfig, SessionState


def _fake_response(text=""):
    """Build a minimal fake ``requests.Response``."""
    response = MagicMock()
    response.status_code = 200
    response.text = text
    return response


class TestCheckInstitutionalProxy(unittest.TestCase):
    """check_institutional_proxy() against a configurable IP prefix."""

    def test_matching_prefix_returns_true(self):
        with patch(
            "searcharticle.network.make_request",
            return_value=_fake_response("132.204.12.34"),
        ):
            key, ok = network.check_institutional_proxy("132.204.")
        self.assertEqual(key, "proxy")
        self.assertTrue(ok)

    def test_other_prefix_returns_false(self):
        with patch(
            "searcharticle.network.make_request",
            return_value=_fake_response("8.8.8.8"),
        ):
            key, ok = network.check_institutional_proxy("132.204.")
        self.assertEqual(key, "proxy")
        self.assertFalse(ok)

    def test_lookup_error_returns_false(self):
        with patch(
            "searcharticle.network.make_request",
            side_effect=Exception("no network"),
        ):
            _, ok = network.check_institutional_proxy("132.204.")
        self.assertFalse(ok)


class TestDiagnoseNetworkProxy(unittest.TestCase):
    """The proxy check is skipped when no IP prefix is configured."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _state(self, **kwargs):
        cfg = AppConfig(email="a@b.c", output_folder=self._tmp.name, **kwargs)
        return SessionState(cfg)

    def test_proxy_skipped_when_prefix_empty(self):
        calls = []

        def fake_make_request(url, **kw):
            calls.append(url)
            return _fake_response()

        state = self._state(institution_ip_prefix="")
        with patch(
            "searcharticle.network.make_request", side_effect=fake_make_request
        ):
            network.diagnose_network(state)
        self.assertIsNone(state.diag["proxy"])
        self.assertNotIn(network._PUBLIC_IP_URL, calls)
        # The other endpoints were still probed.
        self.assertIn("https://www.google.com", calls)

    def test_proxy_checked_when_prefix_set(self):
        calls = []

        def fake_make_request(url, **kw):
            calls.append(url)
            if url == network._PUBLIC_IP_URL:
                return _fake_response("134.157.1.2")
            return _fake_response()

        state = self._state(institution_ip_prefix="134.157.")
        with patch(
            "searcharticle.network.make_request", side_effect=fake_make_request
        ):
            network.diagnose_network(state)
        self.assertTrue(state.diag["proxy"])
        self.assertIn(network._PUBLIC_IP_URL, calls)

    def test_proxy_label_is_generic(self):
        self.assertEqual(
            network.diagnostic_labels()["proxy"], "Institutional proxy"
        )


class TestInstitutionConfig(unittest.TestCase):
    """AppConfig handles the new institution keys."""

    def test_defaults_are_empty(self):
        cfg = AppConfig()
        self.assertEqual(cfg.institution_name, "")
        self.assertEqual(cfg.institution_ip_prefix, "")

    def test_from_dict_reads_new_keys(self):
        cfg = AppConfig.from_dict(
            {
                "institution_name": "Sorbonne Université",
                "institution_ip_prefix": "134.157.",
            }
        )
        self.assertEqual(cfg.institution_name, "Sorbonne Université")
        self.assertEqual(cfg.institution_ip_prefix, "134.157.")

    def test_to_dict_roundtrip(self):
        cfg = AppConfig(
            institution_name="Sorbonne Université",
            institution_ip_prefix="134.157.",
        )
        restored = AppConfig.from_dict(cfg.to_dict())
        self.assertEqual(restored.institution_name, "Sorbonne Université")
        self.assertEqual(restored.institution_ip_prefix, "134.157.")


if __name__ == "__main__":
    unittest.main()
