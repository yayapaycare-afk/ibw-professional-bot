from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import os
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qsl

from aiogram import Bot
from aiogram.enums import ParseMode
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db import Session
from app.models import (
    Application,
    DocumentRule,
    FinalPayment,
    Submission,
    SystemSetting,
    User,
    Wallet,
)

settings = get_settings()
templates = Jinja2Templates(directory="app/templates")

MAX_FILE_BYTES = 10 * 1024 * 1024
ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/pdf",
}
STATUS_LABELS = {
    "DOCUMENTS_PENDING": "Documents Pending",
    "PAYMENT_UNDER_VERIFICATION": "Initial Payment Under Verification",
    "PAYMENT_VERIFIED": "Payment Verified",
    "PROCESSING": "Processing",
    "WALLET_READY": "Wallet Ready",
    "FINAL_PAYMENT_UNDER_VERIFICATION": "Final Payment Under Verification",
    "COMPLETED": "Completed",
    "REJECTED": "Rejected",
}


def _verify_init_data(init_data: str) -> dict:
    if not settings.bot_token:
        raise HTTPException(503, "Bot authentication is not configured")
    if not init_data:
        raise HTTPException(401, "Open this portal from the Telegram bot")

    values = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = values.pop("hash", "")
    if not received_hash:
        raise HTTPException(401, "Telegram authentication is missing")

    data_check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret_key = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise HTTPException(401, "Telegram authentication failed")

    try:
        auth_date = int(values.get("auth_date", "0"))
    except ValueError as exc:
        raise HTTPException(401, "Invalid Telegram authentication date") from exc
    if auth_date <= 0 or abs(int(time.time()) - auth_date) > 86400:
        raise HTTPException(401, "Telegram session expired. Reopen the Mini App")

    try:
        user = json.loads(values.get("user", "{}"))
    except json.JSONDecodeError as exc:
        raise HTTPException(401, "Invalid Telegram user information") from exc
    if not user.get("id"):
        raise HTTPException(401, "Telegram user information is unavailable")
    return user


def _status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status.replace("_", " ").title())


async def _setting(session, key: str, default: str = "") -> str:
    row = await session.get(SystemSetting, key)
    return row.value if row else default


def _resolve_file(path: str | None) -> str | None:
    if not path:
        return None
    candidates = [path, os.path.join(settings.storage_dir, os.path.basename(path))]
    for candidate in candidates:
        normalized = os.path.abspath(candidate)
        if os.path.isfile(normalized):
            return normalized
    return None


def _is_uploaded_file(value) -> bool:
    return bool(value is not None and getattr(value, "filename", None) and hasattr(value, "read"))


async def _save_upload(upload: UploadFile, prefix: str) -> str:
    content_type = (upload.content_type or "").lower()
    if content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(400, "Only JPG, PNG, WEBP or PDF files are allowed")
    data = await upload.read(MAX_FILE_BYTES + 1)
    if not data:
        raise HTTPException(400, "Uploaded file is empty")
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(400, "Each file must be smaller than 10 MB")

    guessed_ext = mimetypes.guess_extension(content_type) or ""
    original_ext = os.path.splitext(upload.filename or "")[1].lower()
    ext = original_ext if original_ext in {".jpg", ".jpeg", ".png", ".webp", ".pdf"} else guessed_ext
    if ext == ".jpe":
        ext = ".jpg"
    os.makedirs(settings.storage_dir, exist_ok=True)
    path = os.path.join(settings.storage_dir, f"{prefix}_{uuid.uuid4().hex}{ext}")
    with open(path, "wb") as handle:
        handle.write(data)
    return path


async def _notify_submission(telegram_id: int, application_id: str, wallet_name: str) -> None:
    if not settings.bot_token:
        return
    bot = Bot(settings.bot_token)
    try:
        await bot.send_message(
            telegram_id,
            (
                "✅ <b>Application Submitted Successfully</b>\n\n"
                f"Application ID: <code>{application_id}</code>\n"
                f"Wallet: <b>{wallet_name}</b>\n"
                "Status: <b>Initial Payment Under Verification</b>\n\n"
                "अपनी Application ID सुरक्षित रखें। आगे के updates आपको इसी Bot पर मिलेंगे।"
            ),
            parse_mode=ParseMode.HTML,
        )
    finally:
        await bot.session.close()


def register_miniapp_routes(app: FastAPI) -> None:
    @app.get("/miniapp", response_class=HTMLResponse)
    async def miniapp_home(request: Request):
        return templates.TemplateResponse(
            "miniapp/index.html",
            {
                "request": request,
                "business_name": settings.business_name,
                "whatsapp_number": settings.whatsapp_number,
                "official_channel": settings.official_channel,
            },
        )

    @app.get("/miniapp/api/bootstrap")
    async def bootstrap():
        async with Session() as session:
            wallets = (
                await session.scalars(
                    select(Wallet).where(Wallet.active.is_(True)).order_by(Wallet.sort_order, Wallet.id)
                )
            ).all()
            output = []
            for wallet in wallets:
                docs = (
                    await session.scalars(
                        select(DocumentRule)
                        .where(DocumentRule.wallet_id == wallet.id)
                        .order_by(DocumentRule.sort_order, DocumentRule.id)
                    )
                ).all()
                first_amount = round(wallet.total_fee * wallet.initial_percent / 100)
                output.append(
                    {
                        "id": wallet.id,
                        "name": wallet.name,
                        "description": wallet.description,
                        "total_fee": wallet.total_fee,
                        "initial_percent": wallet.initial_percent,
                        "initial_amount": first_amount,
                        "remaining_amount": max(wallet.total_fee - first_amount, 0),
                        "processing_time": wallet.processing_time,
                        "upi_id": wallet.upi_id,
                        "banking_name": wallet.banking_name,
                        "has_qr": bool(_resolve_file(wallet.qr_file)),
                        "documents": [
                            {
                                "id": doc.id,
                                "name": doc.name,
                                "manual_label": doc.manual_label,
                                "manual_kind": doc.manual_kind,
                                "upload_allowed": doc.upload_allowed,
                                "manual_allowed": doc.manual_allowed,
                                "required": doc.required,
                            }
                            for doc in docs
                        ],
                    }
                )
            service_available = (await _setting(session, "service_available", "true")) == "true"
            working_hours = await _setting(session, "working_hours", "10:00 AM – 9:30 PM")
        return {
            "business_name": settings.business_name,
            "service_available": service_available,
            "working_hours": working_hours,
            "wallets": output,
            "whatsapp_number": settings.whatsapp_number,
            "official_channel": settings.official_channel,
        }

    @app.get("/miniapp/wallet/{wallet_id}/qr")
    async def wallet_qr(wallet_id: int):
        async with Session() as session:
            wallet = await session.get(Wallet, wallet_id)
        resolved = _resolve_file(wallet.qr_file if wallet else None)
        if not resolved:
            raise HTTPException(404, "Payment QR is not configured")
        response = FileResponse(resolved, media_type=mimetypes.guess_type(resolved)[0] or "image/jpeg")
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @app.post("/miniapp/api/applications")
    async def submit_application(request: Request):
        form = await request.form()
        user_data = _verify_init_data(str(form.get("init_data", "")))
        try:
            wallet_id = int(str(form.get("wallet_id", "0")))
        except ValueError as exc:
            raise HTTPException(400, "Invalid wallet selection") from exc
        utr = str(form.get("utr", "")).strip()
        if len(utr) < 6 or len(utr) > 100:
            raise HTTPException(400, "Enter a valid UTR number")
        try:
            manual_values = json.loads(str(form.get("manual_values", "{}")))
        except json.JSONDecodeError as exc:
            raise HTTPException(400, "Invalid document details") from exc

        receipt = form.get("receipt")
        if not _is_uploaded_file(receipt):
            raise HTTPException(400, "Initial payment receipt is required")

        saved_paths: list[str] = []
        try:
            async with Session() as session:
                wallet = await session.get(Wallet, wallet_id)
                if not wallet or not wallet.active:
                    raise HTTPException(400, "Selected wallet service is unavailable")
                docs = (
                    await session.scalars(
                        select(DocumentRule)
                        .where(DocumentRule.wallet_id == wallet_id)
                        .order_by(DocumentRule.sort_order, DocumentRule.id)
                    )
                ).all()
                submissions_data: list[tuple[DocumentRule, str, str | None, str | None]] = []
                for doc in docs:
                    manual = str(manual_values.get(str(doc.id), "")).strip()
                    upload = form.get(f"doc_{doc.id}")
                    has_upload = _is_uploaded_file(upload)
                    if doc.required and not manual and not has_upload:
                        raise HTTPException(400, f"{doc.name} is required")
                    if manual and not doc.manual_allowed:
                        raise HTTPException(400, f"Manual entry is not allowed for {doc.name}")
                    if has_upload and not doc.upload_allowed:
                        raise HTTPException(400, f"File upload is not allowed for {doc.name}")

                    file_path = None
                    method = "manual"
                    if has_upload:
                        file_path = await _save_upload(upload, f"document_{doc.id}")
                        saved_paths.append(file_path)
                        method = "upload"
                    if manual or file_path:
                        submissions_data.append((doc, method, manual or None, file_path))

                receipt_path = await _save_upload(receipt, "initial_receipt")
                saved_paths.append(receipt_path)

                telegram_id = int(user_data["id"])
                full_name = " ".join(
                    part for part in [user_data.get("first_name", ""), user_data.get("last_name", "")] if part
                ).strip() or "Telegram User"
                username = user_data.get("username")
                user = await session.get(User, telegram_id)
                if user:
                    user.full_name = full_name
                    user.username = username
                else:
                    session.add(User(telegram_id=telegram_id, full_name=full_name, username=username))

                amount_due = round(wallet.total_fee * wallet.initial_percent / 100)
                application = Application(
                    user_id=telegram_id,
                    wallet_id=wallet.id,
                    status="PAYMENT_UNDER_VERIFICATION",
                    amount_due=amount_due,
                    utr=utr,
                    receipt_file=receipt_path,
                )
                session.add(application)
                await session.flush()
                application.application_id = f"IBW-{datetime.now(timezone.utc).year}-{application.id:06d}"
                for doc, method, manual, file_path in submissions_data:
                    session.add(
                        Submission(
                            application_id=application.id,
                            document_rule_id=doc.id,
                            method=method,
                            manual_value=manual,
                            file_path=file_path,
                        )
                    )
                try:
                    await session.commit()
                except IntegrityError as exc:
                    await session.rollback()
                    raise HTTPException(409, "This UTR has already been submitted") from exc

                application_code = application.application_id
                wallet_name = wallet.name
                application_db_id = application.id

            try:
                await _notify_submission(int(user_data["id"]), application_code, wallet_name)
            except Exception as exc:
                print(f"Mini App submission notification error: {exc}")
            return {
                "success": True,
                "application": {
                    "id": application_db_id,
                    "application_id": application_code,
                    "wallet": wallet_name,
                    "status": "PAYMENT_UNDER_VERIFICATION",
                    "status_label": _status_label("PAYMENT_UNDER_VERIFICATION"),
                },
            }
        except Exception:
            for path in saved_paths:
                try:
                    if os.path.isfile(path):
                        os.remove(path)
                except OSError:
                    pass
            raise

    @app.post("/miniapp/api/my-applications")
    async def my_applications(request: Request):
        payload = await request.json()
        user_data = _verify_init_data(str(payload.get("init_data", "")))
        telegram_id = int(user_data["id"])
        async with Session() as session:
            rows = (
                await session.execute(
                    select(Application, Wallet)
                    .join(Wallet, Wallet.id == Application.wallet_id)
                    .where(Application.user_id == telegram_id, Application.application_id.is_not(None))
                    .order_by(Application.id.desc())
                )
            ).all()
            output = []
            for application, wallet in rows:
                final_payment = (
                    await session.scalars(
                        select(FinalPayment).where(FinalPayment.application_id == application.id)
                    )
                ).first()
                output.append(
                    {
                        "id": application.id,
                        "application_id": application.application_id,
                        "wallet": wallet.name,
                        "status": application.status,
                        "status_label": _status_label(application.status),
                        "created_at": application.created_at.isoformat(),
                        "total_fee": wallet.total_fee,
                        "paid_initial": application.amount_due,
                        "remaining_amount": max(wallet.total_fee - application.amount_due, 0),
                        "final_payment_submitted": bool(final_payment),
                    }
                )
        return {"applications": output}

    @app.post("/miniapp/api/track")
    async def track_application(request: Request):
        payload = await request.json()
        user_data = _verify_init_data(str(payload.get("init_data", "")))
        code = str(payload.get("application_id", "")).strip().upper()
        async with Session() as session:
            row = (
                await session.execute(
                    select(Application, Wallet)
                    .join(Wallet, Wallet.id == Application.wallet_id)
                    .where(
                        Application.application_id == code,
                        Application.user_id == int(user_data["id"]),
                    )
                )
            ).first()
        if not row:
            raise HTTPException(404, "Application not found")
        application, wallet = row
        return {
            "application": {
                "id": application.id,
                "application_id": application.application_id,
                "wallet": wallet.name,
                "status": application.status,
                "status_label": _status_label(application.status),
                "remaining_amount": max(wallet.total_fee - application.amount_due, 0),
            }
        }

    @app.get("/miniapp/final-payment-qr")
    async def final_payment_qr():
        async with Session() as session:
            path = await _setting(session, "final_qr_file", "")
        resolved = _resolve_file(path)
        if not resolved:
            raise HTTPException(404, "Final payment QR is not configured")
        response = FileResponse(resolved, media_type=mimetypes.guess_type(resolved)[0] or "image/jpeg")
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @app.post("/miniapp/api/final-payment-info")
    async def final_payment_info(request: Request):
        payload = await request.json()
        user_data = _verify_init_data(str(payload.get("init_data", "")))
        application_id = int(payload.get("application_id", 0))
        async with Session() as session:
            application = await session.get(Application, application_id)
            if not application or application.user_id != int(user_data["id"]):
                raise HTTPException(404, "Application not found")
            if application.status not in {"WALLET_READY", "FINAL_PAYMENT_UNDER_VERIFICATION"}:
                raise HTTPException(400, "Final payment is not available for this application")
            wallet = await session.get(Wallet, application.wallet_id)
            final_payment = (
                await session.scalars(select(FinalPayment).where(FinalPayment.application_id == application.id))
            ).first()
            return {
                "application_id": application.application_id,
                "remaining_amount": max((wallet.total_fee if wallet else 0) - application.amount_due, 0),
                "upi_id": await _setting(session, "final_upi_id", ""),
                "banking_name": await _setting(session, "final_banking_name", ""),
                "has_qr": bool(_resolve_file(await _setting(session, "final_qr_file", ""))),
                "already_submitted": bool(final_payment),
            }

    @app.post("/miniapp/api/final-payment")
    async def submit_final_payment(request: Request):
        form = await request.form()
        user_data = _verify_init_data(str(form.get("init_data", "")))
        try:
            application_id = int(str(form.get("application_id", "0")))
        except ValueError as exc:
            raise HTTPException(400, "Invalid application") from exc
        utr = str(form.get("utr", "")).strip()
        receipt = form.get("receipt")
        if len(utr) < 6 or len(utr) > 100:
            raise HTTPException(400, "Enter a valid UTR number")
        if not _is_uploaded_file(receipt):
            raise HTTPException(400, "Final payment receipt is required")

        receipt_path = await _save_upload(receipt, "final_receipt")
        try:
            async with Session() as session:
                application = await session.get(Application, application_id, with_for_update=True)
                if not application or application.user_id != int(user_data["id"]):
                    raise HTTPException(404, "Application not found")
                if application.status != "WALLET_READY":
                    raise HTTPException(400, "Final payment is not available for this application")
                existing = (
                    await session.scalars(select(FinalPayment).where(FinalPayment.application_id == application.id))
                ).first()
                if existing:
                    raise HTTPException(409, "Final payment has already been submitted")
                session.add(
                    FinalPayment(
                        application_id=application.id,
                        utr=utr,
                        receipt_file=receipt_path,
                        status="UNDER_VERIFICATION",
                    )
                )
                application.status = "FINAL_PAYMENT_UNDER_VERIFICATION"
                try:
                    await session.commit()
                except IntegrityError as exc:
                    await session.rollback()
                    raise HTTPException(409, "This UTR has already been submitted") from exc
            return {"success": True, "status_label": _status_label("FINAL_PAYMENT_UNDER_VERIFICATION")}
        except Exception:
            try:
                if os.path.isfile(receipt_path):
                    os.remove(receipt_path)
            except OSError:
                pass
            raise
