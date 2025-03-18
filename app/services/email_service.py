import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import config

logger = logging.getLogger(__name__)


class EmailClient:
    """Контекстний менеджер для SMTP-з'єднання."""

    def __init__(self):
        self.server = None

    def __enter__(self):
        try:
            if config.SMTP_PORT == 587:
                self.server = smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT)
                self.server.starttls()
            elif config.SMTP_PORT == 465:
                self.server = smtplib.SMTP_SSL(config.SMTP_SERVER, config.SMTP_PORT)
            else:
                raise ValueError("Unsupported SMTP port. Use 587 (TLS) or 465 (SSL).")

            self.server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
            return self.server
        except Exception as e:
            logger.error(f"Failed to connect to SMTP server: {e}")
            raise

    def __exit__(self, exc_type, exc_value, traceback):
        if self.server:
            self.server.quit()


async def send_email(to_email: str, subject: str, message: str, html=False):
    """Функція для надсилання email з використанням контекстного менеджера."""
    try:
        msg = MIMEMultipart()
        msg["From"] = config.EMAIL_FROM
        msg["To"] = to_email
        msg["Subject"] = subject

        footer = """
        Це автоматичний лист, будь ласка, не відповідайте на нього.

        📚 Ваша бібліотека
        """

        if html:
            full_message = f"{message}<br><hr><p style='color: #888; font-size: 12px; text-align: center;'>{footer}</p>"
            msg.attach(MIMEText(full_message, "html"))
        else:
            msg.attach(MIMEText(message + footer, "plain"))

        with EmailClient() as server:
            server.sendmail(config.EMAIL_FROM, to_email, msg.as_string())

        logger.info(f"Email sent successfully to {to_email}")
        return {"message": "Email sent successfully"}

    except smtplib.SMTPException as e:
        logger.error(f"SMTP error: {e}")
        return {"error": f"SMTP error: {e}"}
    except Exception as e:
        logger.error(f"General email error: {e}")
        return {"error": f"General error: {e}"}
