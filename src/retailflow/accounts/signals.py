from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.mail import send_mail
from django.contrib.auth.tokens import default_token_generator
from django.urls import reverse
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from .models import User


@receiver(post_save, sender=User)
def send_verification(sender, instance, created, **kwargs):
    if created and not instance.is_verified:
        token = default_token_generator.make_token(instance)

        uid = urlsafe_base64_encode(
            force_bytes(instance.id)
        )

        link = (
                "http://127.0.0.1:8000"
                + reverse(
            "verify_email",
            args=[uid, token]
        )
        )

        send_mail(
            "Verify your RetailFlow account",

            f"""
        Hello {instance.first_name},

        Please verify your RetailFlow account by clicking this link:

        {link}

        After verification, you can login.

        Thank you,
        RetailFlow
        """,

            None,

            [instance.email],

            fail_silently=False
        )

