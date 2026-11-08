"""Bangun ulang page.py dari index.html. Jalankan setiap kali index.html diubah:  python build_page.py"""
import pathlib

root = pathlib.Path(__file__).parent
src = (root / "index.html").read_text(encoding="utf-8")
assert "'''" not in src, "index.html tidak boleh memuat tiga tanda kutip tunggal"
head = '"""Halaman dasbor (otomatis dari index.html). Disematkan agar ikut ter-bundle di hosting serverless."""\nHTML = r\'\'\''
(root / "page.py").write_text(head + src + "'''\n", encoding="utf-8")
print("page.py dibangun dari index.html (%d karakter)" % len(src))
