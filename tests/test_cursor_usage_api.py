from __future__ import annotations

import unittest
import urllib.error
from unittest import mock

from zcounter.providers.cursor import usage_api
from zcounter.providers.cursor.usage_api import (
    CursorAPIError,
    CursorShapeError,
    CursorUnauthorizedError,
)


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._body


class CursorUsageAPITests(unittest.TestCase):
    def test_sand_usage_status_uses_post_empty_json_and_minimal_headers(self) -> None:
        with mock.patch.object(
            usage_api.urllib.request,
            "urlopen",
            return_value=_Response(b'{"usagePercent":1}'),
        ) as urlopen:
            payload = usage_api.fetch_sand_usage_status("redacted-cookie")

        self.assertEqual(payload["usagePercent"], 1)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, usage_api.SAND_USAGE_STATUS_URL)
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.data, b"{}")
        self.assertEqual(request.headers.get("Cookie"), "redacted-cookie")
        self.assertEqual(request.headers.get("Origin"), "https://cursor.com")
        self.assertEqual(request.headers.get("Content-type"), "application/json")
        self.assertNotIn("Referer", request.headers)
        self.assertNotIn("User-agent", request.headers)

    def test_sand_usage_status_403_is_unauthorized_error(self) -> None:
        failure = urllib.error.HTTPError(
            usage_api.SAND_USAGE_STATUS_URL,
            403,
            "forbidden",
            hdrs=None,
            fp=None,
        )
        with mock.patch.object(usage_api.urllib.request, "urlopen", side_effect=failure):
            with self.assertRaises(CursorUnauthorizedError):
                usage_api.fetch_sand_usage_status("redacted-cookie")

    def test_sand_usage_status_timeout_is_api_error(self) -> None:
        with mock.patch.object(
            usage_api.urllib.request,
            "urlopen",
            side_effect=TimeoutError,
        ):
            with self.assertRaisesRegex(CursorAPIError, "timed out"):
                usage_api.fetch_sand_usage_status("redacted-cookie")

    def test_sand_usage_status_server_error_is_api_error(self) -> None:
        failure = urllib.error.HTTPError(
            usage_api.SAND_USAGE_STATUS_URL,
            500,
            "server error",
            hdrs=None,
            fp=None,
        )
        with mock.patch.object(usage_api.urllib.request, "urlopen", side_effect=failure):
            with self.assertRaises(CursorAPIError):
                usage_api.fetch_sand_usage_status("redacted-cookie")

    def test_sand_usage_status_invalid_json_shape_is_shape_error(self) -> None:
        with mock.patch.object(
            usage_api.urllib.request,
            "urlopen",
            return_value=_Response(b"[]"),
        ):
            with self.assertRaises(CursorShapeError):
                usage_api.fetch_sand_usage_status("redacted-cookie")


if __name__ == "__main__":
    unittest.main()
