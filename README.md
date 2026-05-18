# LinkIntel / DorkFlow Phase 1

Local Streamlit MVP để lấy URL từ Serper.dev Google Search API, crawl backlink prospect pages song song bằng `aiohttp`, trích xuất title/email/phone/domain, lưu SQLite, export Excel và push Google Sheet.

## Setup

1. Cài Python 3.11+.
2. Tạo virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

3. Cài dependencies:

```powershell
pip install -r requirements.txt
```

4. Tạo `.env` từ `.env.example`:

```powershell
Copy-Item .env.example .env
```

5. Lấy API key từ [Serper.dev](https://serper.dev/) và điền:

```env
SERPER_API_KEY=your_serper_api_key_here
```

## Run

```powershell
streamlit run app.py
```

Mở URL Streamlit hiển thị trong terminal. Nhập 1-10 dorks, chỉnh cấu hình crawl nếu cần, rồi bấm **Start Crawl**.

## Google Sheets

1. Tạo Google Cloud Service Account.
2. Enable Google Sheets API và Google Drive API.
3. Tải file JSON credentials.
4. Share Google Sheet cho email của service account với quyền Editor.
5. Điền đường dẫn JSON vào `.env`:

```env
GOOGLE_SERVICE_ACCOUNT_JSON=C:\path\to\service-account.json
```

Trong app, chọn job cụ thể, nhập Google Sheet ID và worksheet name, rồi bấm **Push to Google Sheet**.

## Data

- SQLite DB: `data/linkintel.db`
- Excel exports: `data/exports/`

## Compliance Notes

- Không scrape Google trực tiếp; SERP được lấy qua Serper.dev API.
- Không bypass CAPTCHA.
- Chỉ crawl public pages, không crawl dữ liệu sau login.
- Robots.txt respect đang để TODO cho phase sau.
- Delay, timeout, retry và workers có thể cấu hình để giảm tải lên website đích.
