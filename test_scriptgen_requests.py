"""Ensure Gemini credentials stay in headers and API fallbacks work headlessly."""
import os
import sys
import types
import unittest
from unittest import mock

try:
    import requests  # noqa: F401
except ImportError:
    requests_stub = types.ModuleType("requests")
    requests_stub.get = lambda *args, **kwargs: None
    requests_stub.post = lambda *args, **kwargs: None
    sys.modules["requests"] = requests_stub

import scriptgen


class GeminiCredentialTransportTests(unittest.TestCase):
    def test_model_discovery_sends_key_in_header_not_url(self):
        secret = "offline-test-secret-never-log"
        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "models": [{
                "name": "models/gemini-2.5-flash",
                "supportedGenerationMethods": ["generateContent"],
            }]
        }
        previous = scriptgen._discovered
        try:
            scriptgen._discovered = None
            with mock.patch.object(scriptgen.requests, "get", return_value=response) as request:
                models = scriptgen._best_models(secret)
        finally:
            scriptgen._discovered = previous
        args, kwargs = request.call_args
        self.assertEqual(args[0], scriptgen.LIST_URL)
        self.assertNotIn(secret, args[0])
        self.assertEqual(kwargs["headers"]["x-goog-api-key"], secret)
        self.assertIn("gemini-2.5-flash", models)

    def test_generation_sends_key_in_header_not_url(self):
        secret = "offline-test-secret-never-log"
        response = mock.Mock()
        response.status_code = 200
        response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]
        }
        with mock.patch.object(scriptgen, "_best_models", return_value=["gemini-test"]), \
                mock.patch.object(scriptgen.requests, "post", return_value=response) as request:
            result = scriptgen._call_gemini(secret, "offline prompt", 0.1)
        args, kwargs = request.call_args
        self.assertEqual(result, {"ok": True})
        self.assertNotIn(secret, args[0])
        self.assertEqual(kwargs["headers"]["x-goog-api-key"], secret)

    def test_rate_limits_walk_the_model_chain_until_flash_lite_fallback(self):
        rate_limited = mock.Mock()
        rate_limited.status_code = 429
        rate_limited.json.return_value = {
            "error": {"message": "per-minute request limit reached"}
        }
        success = mock.Mock()
        success.status_code = 200
        success.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]
        }
        chain = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-2.5-flash-lite"]
        with mock.patch.object(scriptgen, "_dead_models", set()), \
                mock.patch.object(scriptgen, "_best_models", return_value=chain), \
                mock.patch.object(scriptgen.requests, "post",
                                  side_effect=[rate_limited, rate_limited, rate_limited, success]) as request, \
                mock.patch("time.sleep"):
            result = scriptgen._call_gemini("offline-key", "offline prompt", 0.1)

        self.assertEqual(result, {"ok": True})
        self.assertEqual(request.call_count, 4)
        self.assertIn("gemini-2.5-flash-lite", request.call_args_list[-1].args[0])

    def test_actions_rate_limit_error_does_not_recommend_local_cli_install(self):
        quota_error = scriptgen._GeminiQuotaExhausted(
            "Gemini per-minute rate limit", is_daily=False,
        )
        default_events = {
            "used_claude_fallback": False,
            "gate_fallbacks": 0,
            "all_gemini_down": 0,
            "gemini_exhausted": False,
            "gemini_daily_exhausted": False,
            "waited_for_perminute": False,
        }
        with mock.patch.dict(scriptgen.RUN_EVENTS, default_events, clear=True), \
                mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}), \
                mock.patch.object(scriptgen, "PROVIDER", "gemini"), \
                mock.patch.object(scriptgen, "_claude_cli_available", return_value=False), \
                mock.patch.object(scriptgen, "_call_gemini",
                                  side_effect=[quota_error, quota_error]) as api_call, \
                mock.patch("time.sleep"):
            with self.assertRaises(RuntimeError) as caught:
                scriptgen._call("offline-key", "offline prompt", 0.1)

        message = str(caught.exception)
        self.assertIn("HTTP 429", message)
        self.assertIn("GitHub Actions", message)
        self.assertIn("one-minute retry", message)
        self.assertIn("No draft was generated", message)
        self.assertNotIn("Install the Claude Code CLI", message)
        self.assertEqual(api_call.call_count, 2)


if __name__ == "__main__":
    unittest.main()
