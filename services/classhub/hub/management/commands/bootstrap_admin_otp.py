import base64
import secrets
import string

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice


class Command(BaseCommand):
    help = "Provision or rotate a Django admin TOTP device for a superuser."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True, help="Superuser username to provision")
        parser.add_argument("--device-name", default="admin-primary", help="TOTP device label")
        parser.add_argument(
            "--rotate",
            action="store_true",
            help="Replace an existing TOTP device with the same name",
        )
        parser.add_argument(
            "--with-static-backup",
            action="store_true",
            help="Also generate a one-time static backup token",
        )

    def handle(self, *args, **options):
        username = (options["username"] or "").strip()
        device_name = (options["device_name"] or "").strip() or "admin-primary"
        rotate = bool(options["rotate"])
        with_static_backup = bool(options["with_static_backup"])

        User = get_user_model()
        user = User.objects.filter(username=username).first()
        if user is None:
            raise CommandError(f"User not found: {username}")
        if not user.is_superuser:
            raise CommandError(f"User {username} is not a superuser")
        if not user.is_active:
            raise CommandError(f"User {username} is inactive")

        existing = TOTPDevice.objects.filter(user=user, name=device_name)
        if existing.exists() and not rotate:
            raise CommandError(
                f"TOTP device '{device_name}' already exists for {username}. Use --rotate to replace it."
            )
        if rotate and existing.exists():
            existing.delete()

        device = TOTPDevice.objects.create(
            user=user,
            name=device_name,
            confirmed=True,
        )

        secret = base64.b32encode(device.bin_key).decode("ascii").rstrip("=")
        self.stdout.write(self.style.SUCCESS(f"Created TOTP device '{device_name}' for {username}."))
        self.stdout.write("Scan this URI in your authenticator app:")
        self.stdout.write(getattr(device, "config_url", ""))
        self.stdout.write(f"Manual secret (base32): {secret}")

        if with_static_backup:
            backup_name = f"{device_name}-backup"
            backup_device, _ = StaticDevice.objects.get_or_create(user=user, name=backup_name)
            backup_token = "".join(secrets.choice(string.digits) for _ in range(10))
            StaticToken.objects.create(device=backup_device, token=backup_token)
            self.stdout.write(self.style.WARNING("Generated one-time static backup token:"))
            self.stdout.write(backup_token)
            self.stdout.write("Store this token securely; it is shown only once.")
