"""Send SMTP email notifications for standalone project tests."""

from __future__ import annotations

from dataclasses import dataclass
from email.mime.text import MIMEText
import os
import smtplib
import ssl


DEFAULT_TIMEOUT_SECONDS = 10
REQUIRED_ENV_NAMES = (
    "MAIL_SMTP_HOST",
    "MAIL_SMTP_PORT",
    "MAIL_USERNAME",
    "MAIL_PASSWORD",
    "MAIL_FROM",
    "MAIL_TO",
)


@dataclass(frozen=True)
class MailConfig:
    """邮件发送配置。

    参数说明：
    smtp_host: SMTP 服务器地址，例如 smtp.qq.com。
    smtp_port: SMTP SSL 端口，QQ 邮箱通常为 465。
    username: 发件邮箱登录名。
    password: 邮箱 SMTP 授权码，不是邮箱登录密码。
    mail_from: 邮件发件人地址。
    mail_to: 单个收件人地址。
    timeout_seconds: SMTP 连接超时时间。
    """

    smtp_host: str
    smtp_port: int
    username: str
    password: str
    mail_from: str
    mail_to: str
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS


def load_mail_config_from_env() -> MailConfig:
    """从环境变量读取邮件配置。

    参数说明：
    无。函数只读取当前进程环境变量，不读取文件，避免把授权码写入仓库。
    """

    missing_names = [name for name in REQUIRED_ENV_NAMES if not os.environ.get(name)]
    if missing_names:
        raise ValueError("缺少邮件环境变量: " + ", ".join(missing_names))

    try:
        smtp_port = int(os.environ["MAIL_SMTP_PORT"])
    except ValueError as exc:
        raise ValueError("MAIL_SMTP_PORT 必须是整数") from exc

    return MailConfig(
        smtp_host=os.environ["MAIL_SMTP_HOST"],
        smtp_port=smtp_port,
        username=os.environ["MAIL_USERNAME"],
        password=os.environ["MAIL_PASSWORD"],
        mail_from=os.environ["MAIL_FROM"],
        mail_to=os.environ["MAIL_TO"],
    )


def send_email(subject: str, body: str, config: MailConfig) -> None:
    """发送一封纯文本邮件。

    参数说明：
    subject: 邮件主题。
    body: 邮件正文，可传入 grid_to_string(grid) 生成的地图字符串。
    config: 邮件发送配置，通常由 load_mail_config_from_env() 生成。
    """

    # 1. 组装纯文本邮件内容。
    message = MIMEText(body, "plain", "utf-8")
    message["Subject"] = subject
    message["From"] = config.mail_from
    message["To"] = config.mail_to

    # 2. 使用系统默认 CA 配置建立 SMTP SSL 连接。
    ssl_context = ssl.create_default_context()
    with smtplib.SMTP_SSL(
        config.smtp_host,
        config.smtp_port,
        timeout=config.timeout_seconds,
        context=ssl_context,
    ) as server:
        # 3. 登录邮箱并发送给单个收件人。
        server.login(config.username, config.password)
        server.sendmail(config.mail_from, [config.mail_to], message.as_string())
