from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db import Session
from app.models import Application, DocumentRule, FinalPayment, Rating, Submission, SystemSetting, User, Wallet

settings = get_settings()
templates = Jinja2Templates(directory="app/templates")
COOKIE_NAME = "ibw_web_session"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _visitor_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _visitor_user_id(visitor_hash: str) -> int:
    # Stable negative bigint; Telegram IDs are positive.
    value = int(visitor_hash[:15], 16) % 9_000_000_000_000_000_000
    return -(value or 1)


def _status_label(status: str) -> str:
    labels = {
        "DRAFT": "Draft",
        "DOCUMENTS_PENDING": "Documents Pending",
        "INITIAL_PAYMENT_PENDING": "Initial Payment Pending",
        "PAYMENT_UNDER_VERIFICATION": "Initial Payment Under Verification",
        "PAYMENT_VERIFIED": "Payment Verified",
        "PROCESSING": "Processing",
        "WALLET_READY": "Wallet Ready",
        "FINAL_PAYMENT_UNDER_VERIFICATION": "Final Payment Under Verification",
        "COMPLETED": "Completed",
        "REJECTED": "Rejected",
    }
    return labels.get(status, status.replace("_", " ").title())


def _resolve_file(stored_path: str | None) -> str | None:
    if not stored_path:
        return None
    candidates = [stored_path, os.path.join(settings.storage_dir, os.path.basename(stored_path))]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def _is_upload(value: object) -> bool:
    """Accept uploads returned by Starlette/FastAPI form parsing.

    Some Starlette versions return ``starlette.datastructures.UploadFile``
    instead of the FastAPI subclass, so a strict ``isinstance`` check can
    reject a real selected file.  Duck-typing keeps this compatible across
    versions while still requiring an actual filename and readable stream.
    """
    if value is None:
        return False
    filename = getattr(value, "filename", None)
    read_method = getattr(value, "read", None)
    return bool(filename and callable(read_method))


async def _save_upload(upload: UploadFile, prefix: str) -> str:
    content_type = (upload.content_type or "").lower()
    if content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(400, "Only JPG, PNG, WEBP or PDF files are allowed")
    data = await upload.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(400, "Uploaded file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "Maximum file size is 10 MB")
    extension = {
        "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "application/pdf": ".pdf"
    }[content_type]
    os.makedirs(settings.storage_dir, exist_ok=True)
    path = os.path.join(settings.storage_dir, f"web_{prefix}_{uuid.uuid4().hex}{extension}")
    with open(path, "wb") as handle:
        handle.write(data)
    return path


async def _setting(session, key: str, default: str = "") -> str:
    row = await session.get(SystemSetting, key)
    return row.value if row else default


def _mobile(value: str) -> str:
    normalized = re.sub(r"\D", "", value or "")
    if len(normalized) == 12 and normalized.startswith("91"):
        normalized = normalized[2:]
    if not re.fullmatch(r"[6-9]\d{9}", normalized):
        raise HTTPException(400, "Enter a valid 10-digit mobile number")
    return normalized


def register_website_routes(app: FastAPI) -> None:
    @app.middleware("http")
    async def website_session_cookie(request: Request, call_next):
        token = request.cookies.get(COOKIE_NAME)
        created = False
        if not token or not re.fullmatch(r"[A-Za-z0-9_-]{32,100}", token):
            token = secrets.token_urlsafe(32)
            created = True
        request.state.web_visitor_token = token
        response = await call_next(request)
        if created:
            response.set_cookie(
                COOKIE_NAME, token, max_age=COOKIE_MAX_AGE, httponly=True,
                secure=True, samesite="lax", path="/",
            )
        return response

    @app.get("/website", response_class=HTMLResponse)
    async def website_home(request: Request):
        return templates.TemplateResponse("website/index.html", {
            "request": request,
            "business_name": settings.business_name,
            "whatsapp_number": settings.whatsapp_number,
            "official_channel": settings.official_channel,
        })

    @app.get("/website/api/bootstrap")
    async def bootstrap():
        async with Session() as session:
            wallets = (await session.scalars(select(Wallet).where(Wallet.active.is_(True)).order_by(Wallet.sort_order, Wallet.id))).all()
            output = []
            for wallet in wallets:
                docs = (await session.scalars(select(DocumentRule).where(DocumentRule.wallet_id == wallet.id).order_by(DocumentRule.sort_order, DocumentRule.id))).all()
                initial = round(wallet.total_fee * wallet.initial_percent / 100)
                output.append({
                    "id": wallet.id, "name": wallet.name, "description": wallet.description,
                    "total_fee": wallet.total_fee, "initial_amount": initial,
                    "remaining_amount": max(wallet.total_fee-initial, 0),
                    "processing_time": wallet.processing_time, "upi_id": wallet.upi_id,
                    "banking_name": wallet.banking_name, "has_qr": bool(_resolve_file(wallet.qr_file)),
                    "documents": [{
                        "id": d.id, "name": d.name, "manual_label": d.manual_label,
                        "manual_kind": d.manual_kind, "upload_allowed": d.upload_allowed,
                        "manual_allowed": d.manual_allowed, "required": d.required,
                    } for d in docs],
                })
            available = (await _setting(session, "service_available", "true")) == "true"
            hours = await _setting(session, "working_hours", "10:00 AM – 9:30 PM")
        return {"business_name": settings.business_name, "service_available": available, "working_hours": hours,
                "wallets": output, "whatsapp_number": settings.whatsapp_number,
                "official_channel": settings.official_channel,
                "telegram_support": "https://t.me/Indiabusinesswallet", "support_email": "indiabusinesswallets@gmail.com"}

    @app.get("/website/wallet/{wallet_id}/qr")
    async def wallet_qr(wallet_id: int):
        async with Session() as session:
            wallet = await session.get(Wallet, wallet_id)
        path = _resolve_file(wallet.qr_file if wallet else None)
        if not path:
            raise HTTPException(404, "Payment QR is not configured")
        response = FileResponse(path, media_type=mimetypes.guess_type(path)[0] or "image/jpeg")
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @app.post("/website/api/applications")
    async def submit_application(request: Request):
        form = await request.form()
        visitor_hash = _visitor_hash(request.state.web_visitor_token)
        full_name = str(form.get("full_name", "")).strip()
        if len(full_name) < 2 or len(full_name) > 150:
            raise HTTPException(400, "Enter your full name")
        mobile = _mobile(str(form.get("mobile_number", "")))
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
        if not _is_upload(receipt):
            raise HTTPException(400, "Initial payment receipt is required")

        saved: list[str] = []
        try:
            async with Session() as session:
                wallet = await session.get(Wallet, wallet_id)
                if not wallet or not wallet.active:
                    raise HTTPException(400, "Selected wallet service is unavailable")
                docs = (await session.scalars(select(DocumentRule).where(DocumentRule.wallet_id == wallet_id).order_by(DocumentRule.sort_order, DocumentRule.id))).all()
                submissions = []
                for doc in docs:
                    manual = str(manual_values.get(str(doc.id), "")).strip()
                    upload = form.get(f"doc_{doc.id}")
                    has_upload = _is_upload(upload)
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
                        saved.append(file_path); method = "upload"
                    if manual or file_path:
                        submissions.append((doc.id, method, manual or None, file_path))
                receipt_path = await _save_upload(receipt, "initial_receipt")
                saved.append(receipt_path)

                user_id = _visitor_user_id(visitor_hash)
                user = await session.get(User, user_id)
                if user:
                    user.full_name = full_name
                    user.username = f"website:{mobile}"
                else:
                    user = User(
                        telegram_id=user_id,
                        full_name=full_name,
                        username=f"website:{mobile}",
                    )
                    session.add(user)

                # Flush the website user first so the applications.user_id
                # foreign key always points to an existing users row.
                await session.flush()

                amount_due = round(wallet.total_fee * wallet.initial_percent / 100)
                application = Application(
                    user_id=user_id, wallet_id=wallet.id, status="PAYMENT_UNDER_VERIFICATION",
                    amount_due=amount_due, utr=utr, receipt_file=receipt_path,
                    source="WEBSITE", web_visitor_hash=visitor_hash, customer_mobile=mobile,
                )
                session.add(application); await session.flush()
                application.application_id = f"IBW-{datetime.now(timezone.utc).year}-{application.id:06d}"
                for doc_id, method, manual, file_path in submissions:
                    session.add(Submission(application_id=application.id, document_rule_id=doc_id,
                                           method=method, manual_value=manual, file_path=file_path))
                try:
                    await session.commit()
                except IntegrityError as exc:
                    await session.rollback()
                    raise HTTPException(409, "This UTR has already been submitted") from exc
                return {"success": True, "application": {"id": application.id,
                        "application_id": application.application_id, "wallet": wallet.name,
                        "status": application.status, "status_label": _status_label(application.status)}}
        except Exception:
            for path in saved:
                try:
                    if os.path.isfile(path): os.remove(path)
                except OSError: pass
            raise

    @app.get("/website/api/my-applications")
    async def my_applications(request: Request):
        visitor_hash = _visitor_hash(request.state.web_visitor_token)
        async with Session() as session:
            rows = (await session.execute(select(Application, Wallet).join(Wallet, Wallet.id == Application.wallet_id)
                    .where(Application.source == "WEBSITE", Application.web_visitor_hash == visitor_hash,
                           Application.application_id.is_not(None)).order_by(Application.id.desc()))).all()
            output=[]
            for application, wallet in rows:
                final_payment=(await session.scalars(select(FinalPayment).where(FinalPayment.application_id==application.id))).first()
                rating=(await session.scalars(select(Rating).where(Rating.application_id==application.id))).first()
                output.append({"id":application.id,"application_id":application.application_id,"wallet":wallet.name,
                    "status":application.status,"status_label":_status_label(application.status),
                    "created_at":application.created_at.isoformat(),"total_fee":wallet.total_fee,
                    "paid_initial":application.amount_due,"remaining_amount":max(wallet.total_fee-application.amount_due,0),
                    "final_payment_submitted":bool(final_payment),"rating":rating.stars if rating else None})
        return {"applications":output}

    @app.post("/website/api/track")
    async def track(request: Request):
        payload=await request.json(); code=str(payload.get("application_id","")).strip().upper(); mobile=_mobile(str(payload.get("mobile_number","")))
        async with Session() as session:
            row=(await session.execute(select(Application,Wallet).join(Wallet,Wallet.id==Application.wallet_id)
                .where(Application.application_id==code,Application.source=="WEBSITE",Application.customer_mobile==mobile))).first()
        if not row: raise HTTPException(404,"Application not found")
        application,wallet=row
        return {"application":{"id":application.id,"application_id":application.application_id,"wallet":wallet.name,
            "status":application.status,"status_label":_status_label(application.status),
            "remaining_amount":max(wallet.total_fee-application.amount_due,0)}}

    @app.get("/website/final-payment-qr")
    async def final_qr():
        async with Session() as session: path=await _setting(session,"final_qr_file","")
        path=_resolve_file(path)
        if not path: raise HTTPException(404,"Final payment QR is not configured")
        response=FileResponse(path,media_type=mimetypes.guess_type(path)[0] or "image/jpeg"); response.headers["Cache-Control"]="private, no-store"; return response


    @app.post("/website/api/rating")
    async def submit_rating(request: Request):
        payload = await request.json()
        visitor_hash = _visitor_hash(request.state.web_visitor_token)
        try:
            application_id = int(payload.get("application_id", 0))
            stars = int(payload.get("stars", 0))
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "Invalid rating") from exc
        if stars not in range(1, 6):
            raise HTTPException(400, "Rating must be between 1 and 5")
        async with Session() as session:
            application = await session.get(Application, application_id)
            if (
                not application
                or application.source != "WEBSITE"
                or application.web_visitor_hash != visitor_hash
            ):
                raise HTTPException(404, "Application not found")
            if application.status != "COMPLETED":
                raise HTTPException(400, "Rating is available after completion")
            existing = (
                await session.scalars(
                    select(Rating).where(Rating.application_id == application.id)
                )
            ).first()
            if existing:
                return {"success": True, "stars": existing.stars, "already_submitted": True}
            session.add(
                Rating(
                    application_id=application.id,
                    user_id=application.user_id,
                    stars=stars,
                )
            )
            await session.commit()
        return {"success": True, "stars": stars, "already_submitted": False}

    @app.post("/website/api/final-payment-info")
    async def final_info(request: Request):
        payload=await request.json(); visitor_hash=_visitor_hash(request.state.web_visitor_token); application_id=int(payload.get("application_id",0))
        async with Session() as session:
            application=await session.get(Application,application_id)
            if not application or application.source!="WEBSITE" or application.web_visitor_hash!=visitor_hash: raise HTTPException(404,"Application not found")
            if application.status not in {"WALLET_READY","FINAL_PAYMENT_UNDER_VERIFICATION"}: raise HTTPException(400,"Final payment is not available")
            wallet=await session.get(Wallet,application.wallet_id)
            existing=(await session.scalars(select(FinalPayment).where(FinalPayment.application_id==application.id))).first()
            return {"application_id":application.application_id,"remaining_amount":max((wallet.total_fee if wallet else 0)-application.amount_due,0),
                    "upi_id":await _setting(session,"final_upi_id",""),"banking_name":await _setting(session,"final_banking_name",""),
                    "has_qr":bool(_resolve_file(await _setting(session,"final_qr_file",""))),"already_submitted":bool(existing)}

    @app.post("/website/api/final-payment")
    async def final_submit(request: Request):
        form=await request.form(); visitor_hash=_visitor_hash(request.state.web_visitor_token)
        try: application_id=int(str(form.get("application_id","0")))
        except ValueError as exc: raise HTTPException(400,"Invalid application") from exc
        utr=str(form.get("utr","")).strip(); receipt=form.get("receipt")
        if len(utr)<6 or len(utr)>100: raise HTTPException(400,"Enter a valid UTR number")
        if not _is_upload(receipt): raise HTTPException(400,"Final payment receipt is required")
        path=await _save_upload(receipt,"final_receipt")
        try:
            async with Session() as session:
                application=await session.get(Application,application_id,with_for_update=True)
                if not application or application.source!="WEBSITE" or application.web_visitor_hash!=visitor_hash: raise HTTPException(404,"Application not found")
                if application.status!="WALLET_READY": raise HTTPException(400,"Final payment is not available")
                existing=(await session.scalars(select(FinalPayment).where(FinalPayment.application_id==application.id))).first()
                if existing: raise HTTPException(409,"Final payment has already been submitted")
                session.add(FinalPayment(application_id=application.id,utr=utr,receipt_file=path,status="UNDER_VERIFICATION"))
                application.status="FINAL_PAYMENT_UNDER_VERIFICATION"
                try: await session.commit()
                except IntegrityError as exc: await session.rollback(); raise HTTPException(409,"This UTR has already been submitted") from exc
            return {"success":True,"status_label":_status_label("FINAL_PAYMENT_UNDER_VERIFICATION")}
        except Exception:
            try:
                if os.path.isfile(path): os.remove(path)
            except OSError: pass
            raise
