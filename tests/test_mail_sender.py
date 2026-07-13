import os
from threading import Event
import unittest
from email import message_from_string
from unittest.mock import patch


class MailSenderTest(unittest.TestCase):
    def test_load_mail_config_from_env_requires_all_values(self):
        from src.services.mail_sender import load_mail_config_from_env

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError) as context:
                load_mail_config_from_env()

        message = str(context.exception)
        self.assertIn("MAIL_SMTP_HOST", message)
        self.assertIn("MAIL_PASSWORD", message)
        self.assertIn("MAIL_TO", message)

    def test_send_email_logs_in_and_sends_plain_text_message(self):
        from src.services.mail_sender import MailConfig, send_email

        smtp_calls = []

        class FakeSMTP:
            def __init__(self, host, port, timeout=None, context=None):
                smtp_calls.append(("connect", host, port, timeout, context))

            def __enter__(self):
                smtp_calls.append(("enter",))
                return self

            def __exit__(self, exc_type, exc, traceback):
                smtp_calls.append(("exit", exc_type))

            def login(self, username, password):
                smtp_calls.append(("login", username, password))

            def sendmail(self, sender, recipients, message):
                smtp_calls.append(("sendmail", sender, recipients, message))

        config = MailConfig(
            smtp_host="smtp.qq.com",
            smtp_port=465,
            username="sender@example.com",
            password="auth-code",
            mail_from="sender@example.com",
            mail_to="receiver@example.com",
            timeout_seconds=10,
        )

        with patch("src.services.mail_sender.smtplib.SMTP_SSL", FakeSMTP):
            send_email("地图更新", "A X\nA A\n", config)

        self.assertEqual(("connect", "smtp.qq.com", 465, 10, unittest.mock.ANY), smtp_calls[0])
        self.assertIn(("login", "sender@example.com", "auth-code"), smtp_calls)

        sendmail_call = next(call for call in smtp_calls if call[0] == "sendmail")
        self.assertEqual("sender@example.com", sendmail_call[1])
        self.assertEqual(["receiver@example.com"], sendmail_call[2])
        self.assertIn("Subject: =?utf-8?", sendmail_call[3])

        parsed_message = message_from_string(sendmail_call[3])
        body = parsed_message.get_payload(decode=True).decode(
            parsed_message.get_content_charset()
        )
        self.assertIn("A X", body)
        self.assertIn("A A", body)

    def test_async_notifier_reports_success_without_blocking_caller(self):
        from src.services.mail_sender import AsyncMailNotifier

        allow_send = Event()
        completed = Event()
        results = []

        def send_fn(_subject, _body):
            allow_send.wait(timeout=1)

        notifier = AsyncMailNotifier(send_fn=send_fn)
        self.addCleanup(notifier.close)

        notifier.notify(
            "到达起点 A1",
            "正文",
            lambda error: (results.append(error), completed.set()),
        )
        self.assertFalse(completed.is_set())

        allow_send.set()
        self.assertTrue(completed.wait(timeout=1))
        self.assertEqual(results, [None])

    def test_unavailable_notifier_reports_configuration_error(self):
        from src.services.mail_sender import AsyncMailNotifier

        results = []
        notifier = AsyncMailNotifier(unavailable_reason="缺少 MAIL_PASSWORD")

        notifier.notify("到达终点 E5", "正文", results.append)

        self.assertEqual(len(results), 1)
        self.assertIn("缺少 MAIL_PASSWORD", str(results[0]))


if __name__ == "__main__":
    unittest.main()
