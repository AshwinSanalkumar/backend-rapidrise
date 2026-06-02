import requests
from django.conf import settings


class BrevoEmailService:

    @staticmethod
    def send_email(subject, html_content, recipients):
        url = "https://api.brevo.com/v3/smtp/email"

        headers = {
            "accept": "application/json",
            "api-key": settings.BREVO_API_KEY,
            "content-type": "application/json",
        }

        payload = {
            "sender": {
                "name": "NexusShare",
                "email": "ashwindev25@gmail.com"
            },
            "to": [{"email": email} for email in recipients],
            "subject": subject,
            "htmlContent": html_content,
        }

        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=30
        )

        response.raise_for_status()

        return response.json()