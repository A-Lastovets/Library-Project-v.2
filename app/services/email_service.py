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
        --
        This is an automated message. Please do not reply.

        - Your Support Team
        """

        if html:
            full_message = f"{message}<br><br><p>--<br>This is an automated message. Please do not reply.<br><br>- Your Support Team</p>"
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


async def send_reservation_cancellation_email(user_email: str, book_title: str):
    """📩 Відправляє email про скасування бронювання."""
    subject = "Бронювання скасовано"
    body = f"Ваше бронювання книги '{book_title}' було автоматично скасовано, оскільки ви не забрали її вчасно."
    await send_email(user_email, subject, body)


async def send_return_reminder_email(user_email: str, book_title: str, due_date: str):
    """📩 Відправляє нагадування про повернення книги."""
    subject = "Нагадування про повернення книги"
    body = (
        f"Нагадуємо, що термін повернення книги '{book_title}' закінчується {due_date}.\n"
        "Будь ласка, поверніть її вчасно, щоб уникнути штрафів."
    )
    await send_email(user_email, subject, body)
