# India Business Wallets V2

Integrated Telegram bot and secure browser admin panel.

## Important V2 features

- Welcome image, dynamic India date, service status and working time (default 10:00 AM – 9:30 PM)
- Fixed start menu and Back/Main Menu navigation
- Exact Terms & Conditions post supplied by the owner
- Dynamic wallet-wise documents
- Upload or manual document entry
- Wallet-wise first-payment QR and percentage
- One common final-payment QR
- Wallet Ready notification with final-payment flow
- Completed notification with one-time 1–5 star rating
- Idempotent admin status updates and status history
- Browser dashboard with wallet, document, application, payment and rating management

## Railway variables

Copy all keys from `.env.example` into Railway Variables. Use a PostgreSQL `DATABASE_URL` reference. For persistent documents attach a Railway Volume mounted at `/data` and set:

`STORAGE_DIR=/data/documents`

## Start command

`uvicorn app.main:web_app --host 0.0.0.0 --port $PORT`

## Admin panel

Open `/login` on your Railway domain.

## Upgrade note

V2 adds new database tables using `create_all`, so existing core tables and applications are retained. Always back up PostgreSQL before major updates.

## V3 Updates
- Start dashboard responds to `/start`, Hi, Hello, Start, Open, Wallet and supported wallet names.
- First-payment and final-payment Banking Name fields.
- Cleaner start caption with Terms & Conditions reminder.
- Permanent application deletion with typed Application ID confirmation and file cleanup.

## Group Privacy Protection

- Application and payment flows run only in private chat.
- When the bot is added to a group, it posts a privacy notice with an **Open Bot Privately** button.
- Group `/start`, wallet keywords, mentions, replies to the bot, and received document/photo uploads trigger the private-chat warning.
- If the bot has permission to delete messages, received group photo/PDF uploads are removed automatically.
- For best protection, give the bot **Delete Messages** permission in the group. Telegram privacy mode may prevent a bot from seeing ordinary group messages that are not commands, mentions, replies, or service messages.
