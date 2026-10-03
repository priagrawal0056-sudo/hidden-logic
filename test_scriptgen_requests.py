"""Ensure Gemini credentials are sent in headers, never logged in request URLs."""
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
            "candidates": [{"content": {"parts": [{"text": "{\"ok\": true}"}]}}]
        }
        with mock.patch.object(scriptgen, "_best_models", return_value=["gemini-test"]), \
                mock.patch.object(scriptgen.requests, "post", return_value=response) as request:
            result = scriptgen._call_gemini(secret, "offline prompt", 0.1)
        args, kwargs = request.call_args
        self.assertEqual(result, {"ok": True})
        self.assertNotIn(secret, args[0])
        self.assertEqual(kwargs["headers"]["x-goog-api-key"], secret)


if __name__ == "__main__":
    unittest.main()
