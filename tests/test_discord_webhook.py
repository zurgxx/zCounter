from __future__ import annotations

import json
import unittest
from unittest import mock

from zcounter.notify.discord_webhook import resolve_webhook_url, send_discord_message

FAKE_WEBHOOK_URL = "https://discord.com/api/webhooks/1234567890123456789/fake-token-for-tests"


class DiscordWebhookTests(unittest.TestCase):
    def test_resolve_webhook_url_uses_env_when_explicit_is_none(self) -> None:
        with mock.patch.dict("os.environ", {"DISCORD_WEBHOOK_URL": FAKE_WEBHOOK_URL}, clear=True):
            self.assertEqual(resolve_webhook_url(), FAKE_WEBHOOK_URL)

    def test_resolve_webhook_url_returns_none_when_unset(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(resolve_webhook_url())

    def test_send_discord_message_skips_when_webhook_unset(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            with mock.patch("zcounter.notify.discord_webhook.urllib.request.urlopen") as urlopen:
                sent = send_discord_message("hello")

        self.assertFalse(sent)
        urlopen.assert_not_called()

    def test_send_discord_message_posts_plain_content(self) -> None:
        with mock.patch("zcounter.notify.discord_webhook.urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.status = 204
            sent = send_discord_message("hello", webhook_url=FAKE_WEBHOOK_URL)

        self.assertTrue(sent)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, FAKE_WEBHOOK_URL)
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["content"], "hello")
        self.assertEqual(body["allowed_mentions"], {"parse": []})

    def test_send_discord_message_logs_http_error_without_raising(self) -> None:
        import urllib.error

        with mock.patch("zcounter.notify.discord_webhook.logger.warning") as warning:
            with mock.patch(
                "zcounter.notify.discord_webhook.urllib.request.urlopen",
                side_effect=urllib.error.HTTPError(
                    FAKE_WEBHOOK_URL,
                    500,
                    "server error",
                    None,
                    None,
                ),
            ):
                sent = send_discord_message("hello", webhook_url=FAKE_WEBHOOK_URL)

        self.assertFalse(sent)
        warning.assert_called_once_with("discord notify failed: HTTP %s", 500)

    def test_send_discord_message_logs_timeout_without_raising(self) -> None:
        with mock.patch("zcounter.notify.discord_webhook.logger.warning") as warning:
            with mock.patch(
                "zcounter.notify.discord_webhook.urllib.request.urlopen",
                side_effect=TimeoutError(),
            ):
                sent = send_discord_message("hello", webhook_url=FAKE_WEBHOOK_URL)

        self.assertFalse(sent)
        warning.assert_called_once()
        self.assertIn("timeout", warning.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
