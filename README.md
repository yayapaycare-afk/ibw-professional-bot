# IBW Professional Bot + Browser Admin Panel

## Features
- Exact Telegram start menu requested
- Dynamic wallet list
- Wallet-wise price, initial-payment percentage, QR and UPI
- Admin-managed required documents per wallet
- Mobile Number as manual-only required document
- Upload or manual entry for other documents
- Special Bank Details manual flow: Account Number + IFSC
- Payment UTR and receipt
- Duplicate UTR prevention
- Generated Application ID
- WhatsApp contact button
- Password-protected browser admin panel
- Private document/receipt routes behind admin login
- SQLite locally; PostgreSQL on Railway

## Run locally
1. Copy `.env.example` to `.env` and fill it.
2. `pip install -r requirements.txt`
3. `uvicorn app.main:web_app --reload`
4. Open `http://localhost:8000/login`

The Telegram bot starts inside the same web process.

## Railway
Add PostgreSQL and set all variables from `.env.example`. Set `PUBLIC_BASE_URL` to your Railway/domain URL. The Procfile starts the web server.

## Important production work before collecting real identity documents
- Use object storage with encryption instead of local disk.
- Use HTTPS and a strong random session secret.
- Use hashed admin passwords and 2FA.
- Add privacy/consent and data-retention policies.
- Restrict access by admin roles and maintain audit logs.
- Never request OTP, UPI PIN, passwords or card PINs.
