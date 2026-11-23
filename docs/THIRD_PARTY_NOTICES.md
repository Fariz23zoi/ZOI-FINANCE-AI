# THIRD PARTY NOTICES

ZOI FINANCE AI memakai ulang sebagian kode dari proyek berlisensi MIT di bawah ini.
Kewajiban lisensi MIT adalah menyertakan pemberitahuan hak cipta dan teks lisensi;
dokumen ini memenuhi kewajiban tersebut.

File yang memuat kode turunan juga diberi komentar kepala yang menyebut sumbernya.

---

## RibasomR/finance-bot

https://github.com/RibasomR/finance-bot

Kode yang diadaptasi:

- `app/utils/sanitizer.py` — penyamaran data sensitif pada log
- `app/utils/validators.py` — validasi dan sanitasi input
- `app/ai/router.py` — pola *exponential backoff* dengan *jitter* dan *deadline* total

```
MIT License

Copyright (c) 2025-2026 RibasomR

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## Proyek yang hanya menjadi rujukan pola

Dari ketiga proyek berikut **tidak ada baris kode yang disalin**. Hanya pendekatan dan
pola desainnya yang ditiru lalu ditulis ulang dari nol. Ide dan arsitektur tidak
dilindungi hak cipta sehingga atribusi di bawah bersifat penghargaan, bukan kewajiban.

| Proyek | Lisensi | Pola yang ditiru |
|---|---|---|
| [nikamurkaa/finance-helper](https://github.com/nikamurkaa/finance-helper) | MIT © 2026 Nicole Zhurbenko | peran ditegakkan di lapisan data; pra-parser bahasa alami berbasis regex |
| [alainrk/pago](https://github.com/alainrk/pago) | MIT © 2025 Alain Di Chiappari | deteksi duplikat; instruksi *prompt* "JSON saja, tanpa backtick" |
| [cenoff/Money-Bot](https://github.com/cenoff/Money-Bot) | MIT © 2025 Oleh Zavieriukhin | struktur pytest + pytest-cov + CI |

Rincian audit lengkap: `docs/REPOSITORY_AUDIT.md`.
