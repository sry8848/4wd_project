"""Manual SMTP email test.

Run after setting the required environment variables, for example:

    python -m src.tools.test_mail_sender --subject "地图更新" --body "A X\nA A"
"""

from __future__ import annotations

import argparse
import smtplib
import sys

from src.services.mail_sender import load_mail_config_from_env, send_email


def parse_args() -> argparse.Namespace:
    """解析手动测试参数。

    参数说明：
    无。参数来自命令行，由 argparse 读取。
    """

    parser = argparse.ArgumentParser(description="Send one SMTP test email.")
    parser.add_argument(
        "--subject",
        default="Yahboom 4WD 邮件发送测试",
        help="Email subject.",
    )
    parser.add_argument(
        "--body",
        default="这是一封来自 4wd_project 的 SMTP 测试邮件。",
        help="Plain text email body.",
    )
    return parser.parse_args()


def main() -> int:
    """读取环境变量并发送一封测试邮件。

    参数说明：
    无。返回 0 表示发送成功，非 0 表示配置或发送失败。
    """

    args = parse_args()

    # 1. 读取本地环境变量，不在代码中保存邮箱授权码。
    try:
        config = load_mail_config_from_env()
    except ValueError as exc:
        print(f"邮件配置错误: {exc}", file=sys.stderr)
        return 2

    # 2. 发送一封纯文本邮件，SMTP 错误会返回非零退出码。
    try:
        send_email(args.subject, args.body, config)
    except (OSError, smtplib.SMTPException) as exc:
        print(f"邮件发送失败: {exc}", file=sys.stderr)
        return 1

    print(f"邮件发送成功，收件人: {config.mail_to}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
