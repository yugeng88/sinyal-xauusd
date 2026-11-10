"""Titik masuk produksi untuk VPS: gunicorn wsgi:app (pakai 1 worker agar cache dan thread latar tidak ganda)."""
import app as _app

_app.start_background()      # thread pembaruan H1; tambah INTERNAL_CRON=1 untuk cron internal tiap menit
app = _app.app
