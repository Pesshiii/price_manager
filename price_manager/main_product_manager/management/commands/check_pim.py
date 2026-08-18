import time
import httpx
from django.core.management.base import BaseCommand
from main_product_manager.pim_api import site


class Command(BaseCommand):
    help = "Проверяет доступность PIM API (GET /api/)"

    def handle(self, *args, **options):
        url = f"https://{site.host}/api/"
        headers = {
            "Accept": "application/json",
            "Authorization-Token": site.token,
        }
        self.stdout.write(f"GET {url} ...")
        t0 = time.monotonic()
        try:
            response = httpx.get(url, headers=headers, timeout=site.timeout)
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            response.raise_for_status()
            self.stdout.write(self.style.SUCCESS(
                f"OK  {response.status_code}  {elapsed_ms}ms"
            ))
        except httpx.HTTPStatusError as exc:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            self.stdout.write(self.style.ERROR(
                f"HTTP {exc.response.status_code}  {elapsed_ms}ms  —  {exc}"
            ))
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            self.stdout.write(self.style.ERROR(
                f"{type(exc).__name__}  {elapsed_ms}ms  —  {exc}"
            ))
