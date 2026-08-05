import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.config import get_settings
from app.db import Session
from app.models import Application, DocumentRule, User, Wallet

settings = get_settings()
templates = Jinja2Templates(directory="app/templates")

TERMS_TEXT = """📜 नियम एवं शर्तें — India Business Wallets

कृपया सेवा लेने से पहले नीचे दिए गए सभी नियम ध्यानपूर्वक पढ़ें।

✅ Verified Service
जिस Bot के माध्यम से आपने हमसे संपर्क किया है, वह India Business Wallets का सत्यापित Bot है। हमारी टीम सुरक्षित और पारदर्शी तरीके से Business Wallet खुलवाने में सहायता करती है।

📱 केवल अधिकृत Agent से संपर्क करें
WhatsApp पर केवल उसी Direct Agent Contact Number से बात करें, जो आपको India Business Wallets bot के आधिकारिक माध्यम से दिया गया हो। किसी अनजान नंबर या व्यक्ति पर भरोसा न करें।

🔐 OTP और Password की सुरक्षा
अपना बैंक पासवर्ड, ईमेल पासवर्ड, UPI PIN या Card PIN किसी अन्य व्यक्ति के साथ साझा न करें।

💳 दो भागों में भुगतान
पहला भुगतान कुल Fee का लगभग 70%–80% आवेदन और प्रक्रिया शुरू करते समय तथा बचा हुआ लगभग 20%–30% Wallet तैयार होने के बाद देना होगा।

💰 अतिरिक्त भुगतान न करें
निर्धारित Service Fee के अलावा Agent को कोई अतिरिक्त भुगतान न करें। Extra Charge मांगे जाने पर आधिकारिक Support से शिकायत करें।

⏳ प्रक्रिया में समय लग सकता है
बैंक, कंपनी की जाँच या तकनीकी कारणों से Wallet बनने में देरी हो सकती है। अपना Application Status समय-समय पर check करते रहें।

🛡️ आपका भुगतान सुरक्षित है
यदि किसी वैध कारण से Wallet नहीं बन पाता है, तो Refund Policy के अनुसार योग्य राशि लौटाई जाएगी।

✅ Service का उपयोग करने पर यह माना जाएगा कि आपने सभी नियम एवं शर्तें पढ़ ली हैं और उनसे सहमत हैं।"""

STATUS_LABELS = {
    "PAYMENT_UNDER_VERIFICATION": "Payment Under Verification",
    "PROCESSING": "Processing",
    "WALLET_READY": "Wallet Ready",
    "FINAL_PAYMENT_UNDER_VERIFICATION": "Final Payment Under Verification",
    "COMPLETED": "Completed",
    "REJECTED": "Rejected",
}


def verify_telegram_init_data(init_data: str, max_age_seconds: int = 86400) -> dict:
    """Validate Telegram Mini App initData using BOT_TOKEN."""
    if not init_data or not settings.bot_token:
        raise HTTPException(status_code=401, detail="Open this Mini App inside Telegram.")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", "")
    if not received_hash:
        raise HTTPException(status_code=401, detail="Telegram verification data is missing.")

    data_check_string = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        raise HTTPException(status_code=401, detail="Telegram verification failed.")

    auth_date = int(pairs.get("auth_date", "0") or 0)
    if auth_date <= 0 or abs(int(time.time()) - auth_date) > max_age_seconds:
        raise HTTPException(status_code=401, detail="Telegram session expired. Reopen the Mini App.")

    try:
        user = json.loads(pairs.get("user", "{}"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=401, detail="Invalid Telegram user data.") from exc

    if not user.get("id"):
        raise HTTPException(status_code=401, detail="Telegram user data is unavailable.")
    return user


def register_miniapp_routes(app: FastAPI) -> None:
    @app.get("/miniapp", response_class=HTMLResponse)
    async def miniapp_home(request: Request):
        return templates.TemplateResponse(
            "miniapp/index.html",
            {
                "request": request,
                "business_name": settings.business_name,
                "official_channel": settings.official_channel,
                "whatsapp_number": settings.whatsapp_number,
                "terms_text": TERMS_TEXT,
            },
        )

    @app.get("/miniapp/api/wallets")
    async def miniapp_wallets():
        async with Session() as session:
            wallets = (await session.scalars(
                select(Wallet).where(Wallet.active.is_(True)).order_by(Wallet.sort_order, Wallet.id)
            )).all()
            result = []
            for wallet in wallets:
                docs = (await session.scalars(
                    select(DocumentRule)
                    .where(DocumentRule.wallet_id == wallet.id, DocumentRule.required.is_(True))
                    .order_by(DocumentRule.sort_order, DocumentRule.id)
                )).all()
                initial_amount = round(wallet.total_fee * wallet.initial_percent / 100)
                result.append({
                    "id": wallet.id,
                    "name": wallet.name,
                    "description": wallet.description,
                    "total_fee": wallet.total_fee,
                    "initial_percent": wallet.initial_percent,
                    "initial_amount": initial_amount,
                    "remaining_amount": max(wallet.total_fee - initial_amount, 0),
                    "processing_time": wallet.processing_time,
                    "documents": [doc.name for doc in docs],
                })
        return {"wallets": result}

    @app.post("/miniapp/api/session")
    async def miniapp_session(request: Request):
        payload = await request.json()
        telegram_user = verify_telegram_init_data(str(payload.get("init_data", "")))
        return {
            "user": {
                "id": telegram_user["id"],
                "first_name": telegram_user.get("first_name", "User"),
                "last_name": telegram_user.get("last_name", ""),
                "username": telegram_user.get("username"),
            }
        }

    @app.post("/miniapp/api/applications")
    async def miniapp_applications(request: Request):
        payload = await request.json()
        telegram_user = verify_telegram_init_data(str(payload.get("init_data", "")))
        telegram_id = int(telegram_user["id"])

        async with Session() as session:
            rows = (await session.execute(
                select(Application, Wallet)
                .join(Wallet, Wallet.id == Application.wallet_id)
                .where(
                    Application.user_id == telegram_id,
                    Application.application_id.is_not(None),
                )
                .order_by(Application.id.desc())
            )).all()

        applications = [
            {
                "application_id": application.application_id,
                "wallet": wallet.name,
                "status": application.status,
                "status_label": STATUS_LABELS.get(application.status, application.status.replace("_", " ").title()),
                "created_at": application.created_at.isoformat() if application.created_at else None,
            }
            for application, wallet in rows
        ]
        return {"applications": applications}

    @app.post("/miniapp/api/track")
    async def miniapp_track(request: Request):
        payload = await request.json()
        telegram_user = verify_telegram_init_data(str(payload.get("init_data", "")))
        application_code = str(payload.get("application_id", "")).strip().upper()
        if not application_code:
            raise HTTPException(status_code=400, detail="Application ID is required.")

        async with Session() as session:
            row = (await session.execute(
                select(Application, Wallet)
                .join(Wallet, Wallet.id == Application.wallet_id)
                .where(
                    Application.application_id == application_code,
                    Application.user_id == int(telegram_user["id"]),
                )
            )).first()

        if not row:
            raise HTTPException(status_code=404, detail="Application not found for this Telegram account.")

        application, wallet = row
        return {
            "application": {
                "application_id": application.application_id,
                "wallet": wallet.name,
                "status": application.status,
                "status_label": STATUS_LABELS.get(application.status, application.status.replace("_", " ").title()),
            }
        }

    @app.get("/miniapp/health")
    async def miniapp_health():
        return JSONResponse({"status": "ok", "module": "miniapp-phase-1"})
