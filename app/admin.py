import html
import mimetypes
import os
import uuid
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import select, func, delete
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db import Session
from app.models import Wallet, DocumentRule, Application, Submission, User, SystemSetting, FinalPayment, Rating, StatusEvent, Referral, ReferralPayout, ReferralProfile

settings = get_settings()
templates = Jinja2Templates(directory="app/templates")


def resolve_stored_file(stored_path: str | None) -> str | None:
    """Resolve current and legacy upload paths without changing database data."""
    if not stored_path:
        return None

    candidates = [stored_path]
    basename = os.path.basename(stored_path)
    if basename:
        candidates.append(os.path.join(settings.storage_dir, basename))
        candidates.append(os.path.join("storage", basename))

    seen: set[str] = set()
    for candidate in candidates:
        normalized = os.path.abspath(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        if os.path.isfile(normalized):
            return normalized
    return None


def protected_file_response(path: str) -> FileResponse:
    media_type, _ = mimetypes.guess_type(path)
    response = FileResponse(
        path,
        media_type=media_type or "application/octet-stream",
        filename=os.path.basename(path),
        content_disposition_type="inline",
    )
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def auth(request: Request) -> bool:
    return request.session.get("admin") is True


async def get_setting(session, key: str, default: str = "") -> str:
    row = await session.get(SystemSetting, key)
    return row.value if row else default


async def set_setting(session, key: str, value: str):
    row = await session.get(SystemSetting, key)
    if row:
        row.value = value
    else:
        session.add(SystemSetting(key=key, value=value))


async def notify_status(application_id: int, status: str):
    if not settings.bot_token:
        return

    async with Session() as session:
        app = await session.get(Application, application_id)
        if not app:
            return
        if getattr(app, "source", "TELEGRAM") == "WEBSITE":
            return

        wallet = await session.get(Wallet, app.wallet_id)
        final_qr = await get_setting(session, "final_qr_file", "")
        final_upi = await get_setting(session, "final_upi_id", "")
        final_banking_name = await get_setting(session, "final_banking_name", "")

    bot = Bot(settings.bot_token)

    try:
        application_code = html.escape(app.application_id or "Draft")
        wallet_name = html.escape(wallet.name if wallet else "Business Wallet")
        readable_status = html.escape(status.replace("_", " ").title())

        if status == "WALLET_READY":
            remaining = max((wallet.total_fee if wallet else 0) - app.amount_due, 0)

            message_text = (
                "🎉 <b>आपका Business Wallet तैयार है!</b>\n\n"
                f"Application ID: <code>{application_code}</code>\n"
                f"Wallet: <b>{wallet_name}</b>\n\n"
                f"💰 <b>Remaining Payment:</b> ₹{remaining}\n"
                f"💳 <b>UPI ID:</b> "
                f"<code>{html.escape(final_upi or 'Contact authorized agent')}</code>\n"
                f"🏦 <b>Banking Name:</b> "
                f"{html.escape(final_banking_name or 'Not configured')}\n\n"
                "कृपया नीचे दिए गए QR के माध्यम से अंतिम भुगतान पूरा करें।\n\n"
                "⚠️ Payment करने से पहले अपने UPI App में Banking Name जरूर verify करें।\n\n"
                "Payment पूरा होने के बाद:\n"
                "• UTR Number दर्ज करें\n"
                "• Payment Receipt upload करें"
            )

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ Submit Final Payment",
                            callback_data=f"final-paid:{app.id}",
                        )
                    ]
                ]
            )

            if final_qr and os.path.exists(final_qr):
                await bot.send_photo(
                    app.user_id,
                    FSInputFile(final_qr),
                    caption=message_text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML,
                )
            else:
                await bot.send_message(
                    app.user_id,
                    message_text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML,
                )

        elif status == "COMPLETED":
            message_text = (
                "🎉 <b>मुबारक हो!</b>\n\n"
                "आपकी Business Wallet Service सफलतापूर्वक पूरी हो गई है।\n\n"
                f"Application ID: <code>{application_code}</code>\n"
                f"Wallet: <b>{wallet_name}</b>\n"
                "Status: <b>Completed ✅</b>\n\n"
                "India Business Wallets पर भरोसा करने के लिए धन्यवाद।\n\n"
                "कृपया बताएं कि आपको हमारी Service कैसी लगी?"
            )

            rating_rows = [
                [
                    InlineKeyboardButton(
                        text="⭐" * rating,
                        callback_data=f"rate:{app.id}:{rating}",
                    )
                ]
                for rating in range(1, 6)
            ]

            await bot.send_message(
                app.user_id,
                message_text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=rating_rows),
                parse_mode=ParseMode.HTML,
            )

        else:
            message_text = (
                "🔔 <b>Application Status Updated</b>\n\n"
                f"Application ID: <code>{application_code}</code>\n"
                f"New Status: <b>{readable_status}</b>\n\n"
                "आपकी Application पर काम शुरू हो चुका है।\n"
                "कृपया आगे की जानकारी के लिए Bot notifications check करते रहें।"
            )

            await bot.send_message(
                app.user_id,
                message_text,
                parse_mode=ParseMode.HTML,
            )

    finally:
        await bot.session.close()



async def send_custom_message_to_user(application_id: int, message_text: str) -> None:
    """Send a plain-text admin message without changing application status."""
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is not configured")

    async with Session() as session:
        application = await session.get(Application, application_id)
        if not application:
            raise RuntimeError("Application not found")
        if getattr(application, "source", "TELEGRAM") == "WEBSITE":
            raise RuntimeError("Website applications do not have Telegram chat access")
        telegram_id = application.user_id

    bot = Bot(settings.bot_token)
    try:
        await bot.send_message(telegram_id, message_text)
    finally:
        await bot.session.close()


async def remove_legacy_drafts(session) -> int:
    """Delete old pre-fix draft rows and their child records/files."""
    drafts = (await session.scalars(
        select(Application).where(Application.application_id.is_(None))
    )).all()
    if not drafts:
        return 0

    paths: list[str] = []
    for application in drafts:
        submissions = (await session.scalars(
            select(Submission).where(Submission.application_id == application.id)
        )).all()
        paths.extend(item.file_path for item in submissions if item.file_path)
        if application.receipt_file:
            paths.append(application.receipt_file)

        final_payment = (await session.scalars(
            select(FinalPayment).where(FinalPayment.application_id == application.id)
        )).first()
        if final_payment and final_payment.receipt_file:
            paths.append(final_payment.receipt_file)

        for model in (Submission, FinalPayment, Rating, StatusEvent):
            rows = (await session.scalars(
                select(model).where(model.application_id == application.id)
            )).all()
            for row in rows:
                await session.delete(row)
        await session.delete(application)

    await session.commit()

    for stored_path in paths:
        resolved = resolve_stored_file(stored_path)
        if resolved:
            try:
                os.remove(resolved)
            except OSError:
                pass
    return len(drafts)

def build_admin_app():
    app = FastAPI(title="IBW Admin")
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        https_only=True,
        same_site="lax",
        max_age=43200,
    )

    @app.middleware("http")
    async def prevent_private_page_cache(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/admin") or request.url.path in {"/login", "/logout"}:
            response.headers["Cache-Control"] = "private, no-store, max-age=0"
            response.headers["Pragma"] = "no-cache"
        return response

    @app.get("/service-worker.js")
    async def service_worker():
        response = FileResponse(
            "app/static/service-worker.js",
            media_type="application/javascript",
        )
        response.headers["Service-Worker-Allowed"] = "/"
        response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/")
    async def root():
        return RedirectResponse("/admin", 303)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        if auth(request):
            return RedirectResponse("/admin", 303)
        return templates.TemplateResponse("login.html", {"request": request, "error": None})

    @app.post("/login")
    async def login(request: Request, username: str = Form(...), password: str = Form(...)):
        if username == settings.admin_username and password == settings.admin_password:
            request.session.clear()
            request.session["admin"] = True
            return RedirectResponse("/admin", 303)
        return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid username or password"}, status_code=401)

    @app.get("/logout")
    async def logout(request: Request):
        request.session.clear()
        return RedirectResponse("/login", 303)

    @app.get("/admin", response_class=HTMLResponse)
    async def dashboard(request: Request):
        if not auth(request): return RedirectResponse("/login", 303)
        async with Session() as session:
            removed_drafts = await remove_legacy_drafts(session)
            genuine = Application.application_id.is_not(None)
            counts = {
                "applications": await session.scalar(select(func.count(Application.id)).where(genuine)) or 0,
                "pending": await session.scalar(select(func.count(Application.id)).where(genuine, Application.status.in_(["PAYMENT_UNDER_VERIFICATION", "FINAL_PAYMENT_UNDER_VERIFICATION"]))) or 0,
                "wallets": await session.scalar(select(func.count(Wallet.id))) or 0,
                "completed": await session.scalar(select(func.count(Application.id)).where(genuine, Application.status == "COMPLETED")) or 0,
            }
            apps = (await session.execute(select(Application, Wallet, User).join(Wallet, Wallet.id == Application.wallet_id).join(User, User.telegram_id == Application.user_id).where(genuine).order_by(Application.id.desc()).limit(30))).all()
            avg_rating = await session.scalar(select(func.avg(Rating.stars))) or 0
            working_hours = await get_setting(session, "working_hours", "10:00 AM – 9:30 PM")
            service_available = (await get_setting(session, "service_available", "true")) == "true"
        return templates.TemplateResponse("dashboard.html", {"request": request, "counts": counts, "apps": apps, "avg_rating": round(float(avg_rating), 1), "working_hours": working_hours, "service_available": service_available, "removed_drafts": removed_drafts})

    @app.get("/admin/settings", response_class=HTMLResponse)
    async def settings_page(request: Request):
        if not auth(request): return RedirectResponse("/login", 303)
        async with Session() as session:
            data = {
                "working_hours": await get_setting(session, "working_hours", "10:00 AM – 9:30 PM"),
                "service_available": (await get_setting(session, "service_available", "true")) == "true",
                "final_upi_id": await get_setting(session, "final_upi_id", ""),
                "final_banking_name": await get_setting(session, "final_banking_name", ""),
                "final_qr_file": await get_setting(session, "final_qr_file", ""),
            }
        return templates.TemplateResponse("settings.html", {"request": request, **data})

    @app.post("/admin/settings")
    async def save_settings(request: Request, working_hours: str = Form(...), final_upi_id: str = Form(""), final_banking_name: str = Form(""), service_available: bool = Form(False), final_qr: UploadFile | None = File(None)):
        if not auth(request): raise HTTPException(403)
        async with Session() as session:
            await set_setting(session, "working_hours", working_hours.strip())
            await set_setting(session, "service_available", "true" if service_available else "false")
            await set_setting(session, "final_upi_id", final_upi_id.strip())
            await set_setting(session, "final_banking_name", final_banking_name.strip())
            if final_qr and final_qr.filename:
                os.makedirs(settings.storage_dir, exist_ok=True)
                ext = os.path.splitext(final_qr.filename)[1].lower() or ".jpg"
                path = os.path.join(settings.storage_dir, f"final_qr_{uuid.uuid4().hex}{ext}")
                with open(path, "wb") as handle: handle.write(await final_qr.read())
                await set_setting(session, "final_qr_file", path)
            await session.commit()
        return RedirectResponse("/admin/settings?saved=1", 303)

    @app.get("/admin/referrals", response_class=HTMLResponse)
    async def referral_rewards(request: Request):
        if not auth(request):
            return RedirectResponse("/login", 303)
        async with Session() as session:
            pending_referrals = await session.scalar(
                select(func.count(Referral.id)).where(Referral.status == "PENDING")
            ) or 0
            ready_rewards = await session.scalar(
                select(func.count(Referral.id)).where(
                    Referral.status == "EARNED", Referral.payout_id.is_(None)
                )
            ) or 0
            payout_requests = await session.scalar(
                select(func.count(ReferralPayout.id)).where(ReferralPayout.status == "REQUESTED")
            ) or 0
            paid_amount = await session.scalar(
                select(func.sum(ReferralPayout.amount)).where(ReferralPayout.status == "PAID")
            ) or 0

            payouts = (await session.execute(
                select(ReferralPayout, ReferralProfile)
                .join(ReferralProfile, ReferralProfile.id == ReferralPayout.referrer_profile_id)
                .order_by(ReferralPayout.id.desc()).limit(100)
            )).all()
            referrals = (await session.execute(
                select(Referral, ReferralProfile, Application, Wallet)
                .join(ReferralProfile, ReferralProfile.id == Referral.referrer_profile_id)
                .outerjoin(Application, Application.id == Referral.application_id)
                .outerjoin(Wallet, Wallet.id == Application.wallet_id)
                .order_by(Referral.id.desc()).limit(100)
            )).all()

        return templates.TemplateResponse("referrals.html", {
            "request": request,
            "pending_referrals": pending_referrals,
            "ready_rewards": ready_rewards,
            "payout_requests": payout_requests,
            "paid_amount": int(paid_amount),
            "payouts": payouts,
            "referrals": referrals,
        })

    @app.post("/admin/referrals/payout/{payout_id}/paid")
    async def mark_referral_payout_paid(request: Request, payout_id: int):
        if not auth(request):
            raise HTTPException(403)
        async with Session() as session:
            payout = await session.get(ReferralPayout, payout_id, with_for_update=True)
            if not payout:
                raise HTTPException(404, "Payout request not found")
            if payout.status != "PAID":
                payout.status = "PAID"
                payout.paid_at = datetime.now(timezone.utc)
                reward_rows = (await session.scalars(
                    select(Referral).where(Referral.payout_id == payout.id)
                )).all()
                for reward in reward_rows:
                    reward.status = "PAID"
                await session.commit()
        return RedirectResponse("/admin/referrals?paid=1", 303)

    @app.get("/admin/wallets", response_class=HTMLResponse)
    async def wallets(request: Request):
        if not auth(request): return RedirectResponse("/login", 303)
        async with Session() as session:
            rows = (await session.scalars(select(Wallet).order_by(Wallet.sort_order, Wallet.id))).all()
        return templates.TemplateResponse("wallets.html", {"request": request, "wallets": rows})

    @app.post("/admin/wallets/add")
    async def add_wallet(request: Request, name: str = Form(...), total_fee: int = Form(...), initial_percent: int = Form(...)):
        if not auth(request): raise HTTPException(403)
        initial_percent = min(max(initial_percent, 1), 100)
        async with Session() as session:
            session.add(Wallet(name=name.strip(), total_fee=max(total_fee, 0), initial_percent=initial_percent))
            try: await session.commit()
            except IntegrityError:
                await session.rollback(); raise HTTPException(400, "Wallet name already exists")
        return RedirectResponse("/admin/wallets", 303)

    @app.get("/admin/wallet/{wid}", response_class=HTMLResponse)
    async def wallet_edit(request: Request, wid: int):
        if not auth(request): return RedirectResponse("/login", 303)
        async with Session() as session:
            wallet = await session.get(Wallet, wid)
            if not wallet: raise HTTPException(404)
            docs = (await session.scalars(select(DocumentRule).where(DocumentRule.wallet_id == wid).order_by(DocumentRule.sort_order, DocumentRule.id))).all()
        return templates.TemplateResponse("wallet_edit.html", {"request": request, "w": wallet, "docs": docs})

    @app.post("/admin/wallet/{wid}/save")
    async def wallet_save(request: Request, wid: int, name: str = Form(...), description: str = Form(""), total_fee: int = Form(...), initial_percent: int = Form(...), processing_time: str = Form(""), upi_id: str = Form(""), banking_name: str = Form(""), active: bool = Form(False), qr: UploadFile | None = File(None)):
        if not auth(request): raise HTTPException(403)
        async with Session() as session:
            wallet = await session.get(Wallet, wid)
            if not wallet: raise HTTPException(404)
            wallet.name = name.strip(); wallet.description = description.strip(); wallet.total_fee = max(total_fee, 0); wallet.initial_percent = min(max(initial_percent, 1), 100); wallet.processing_time = processing_time.strip(); wallet.upi_id = upi_id.strip(); wallet.banking_name = banking_name.strip(); wallet.active = active
            if qr and qr.filename:
                os.makedirs(settings.storage_dir, exist_ok=True)
                ext = os.path.splitext(qr.filename)[1].lower() or ".jpg"
                path = os.path.join(settings.storage_dir, f"wallet_qr_{uuid.uuid4().hex}{ext}")
                with open(path, "wb") as handle: handle.write(await qr.read())
                wallet.qr_file = path
            await session.commit()
        return RedirectResponse(f"/admin/wallet/{wid}?saved=1", 303)

    @app.post("/admin/wallet/{wid}/document/add")
    async def doc_add(request: Request, wid: int, name: str = Form(...), manual_label: str = Form(...), manual_kind: str = Form("single"), upload_allowed: bool = Form(False), manual_allowed: bool = Form(False)):
        if not auth(request): raise HTTPException(403)
        if not upload_allowed and not manual_allowed: raise HTTPException(400, "At least one submission method is required")
        async with Session() as session:
            maximum = await session.scalar(select(func.max(DocumentRule.sort_order)).where(DocumentRule.wallet_id == wid)) or 0
            session.add(DocumentRule(wallet_id=wid, name=name.strip(), manual_label=manual_label.strip(), manual_kind=manual_kind, upload_allowed=upload_allowed, manual_allowed=manual_allowed, sort_order=maximum + 1))
            await session.commit()
        return RedirectResponse(f"/admin/wallet/{wid}", 303)

    @app.post("/admin/document/{did}/delete")
    async def doc_delete(request: Request, did: int):
        if not auth(request): raise HTTPException(403)
        async with Session() as session:
            doc = await session.get(DocumentRule, did)
            if not doc: raise HTTPException(404)
            if doc.name.strip().lower() == "mobile number": raise HTTPException(400, "Mobile Number cannot be removed")
            wid = doc.wallet_id
            await session.delete(doc); await session.commit()
        return RedirectResponse(f"/admin/wallet/{wid}", 303)

    @app.get("/admin/application/{aid}", response_class=HTMLResponse)
    async def app_detail(request: Request, aid: int):
        if not auth(request): return RedirectResponse("/login", 303)
        async with Session() as session:
            application = await session.get(Application, aid)
            if not application: raise HTTPException(404)
            wallet = await session.get(Wallet, application.wallet_id)
            user = await session.get(User, application.user_id)
            subs = (await session.execute(select(Submission, DocumentRule).join(DocumentRule, DocumentRule.id == Submission.document_rule_id).where(Submission.application_id == aid).order_by(DocumentRule.sort_order))).all()
            final_payment = (await session.scalars(select(FinalPayment).where(FinalPayment.application_id == aid))).first()
            rating = (await session.scalars(select(Rating).where(Rating.application_id == aid))).first()
            history = (await session.scalars(select(StatusEvent).where(StatusEvent.application_id == aid).order_by(StatusEvent.id.desc()).limit(30))).all()
        return templates.TemplateResponse("application.html", {"request": request, "a": application, "w": wallet, "u": user, "subs": subs, "final_payment": final_payment, "rating": rating, "history": history})

    @app.post("/admin/application/{aid}/status")
    async def status(request: Request, aid: int, status: str = Form(...)):
        if not auth(request): raise HTTPException(403)
        allowed = {"DOCUMENTS_PENDING", "PAYMENT_UNDER_VERIFICATION", "PAYMENT_VERIFIED", "PROCESSING", "WALLET_READY", "FINAL_PAYMENT_UNDER_VERIFICATION", "COMPLETED", "REJECTED"}
        if status not in allowed: raise HTTPException(400, "Invalid status")
        changed = False
        async with Session() as session:
            application = await session.get(Application, aid, with_for_update=True)
            if not application: raise HTTPException(404)
            old = application.status
            if old != status:
                application.status = status
                session.add(StatusEvent(application_id=aid, old_status=old, new_status=status, source="ADMIN"))
                if status == "COMPLETED":
                    referral = (await session.scalars(
                        select(Referral).where(Referral.application_id == aid)
                    )).first()
                    if referral and referral.status == "PENDING":
                        referral.status = "EARNED"
                        referral.completed_at = datetime.now(timezone.utc)
                await session.commit()
                changed = True
        if changed:
            try: await notify_status(aid, status)
            except Exception as exc: print(f"Notification error for application {aid}: {exc}")
        return RedirectResponse(f"/admin/application/{aid}?updated={'1' if changed else '0'}", 303)

    @app.post("/admin/application/{aid}/message")
    async def custom_message(request: Request, aid: int, message_text: str = Form(...)):
        if not auth(request):
            raise HTTPException(403)
        message_text = message_text.strip()
        if not message_text:
            return RedirectResponse(f"/admin/application/{aid}?message_error=empty", 303)
        if len(message_text) > 3500:
            return RedirectResponse(f"/admin/application/{aid}?message_error=long", 303)

        async with Session() as session:
            application = await session.get(Application, aid)
            if not application or not application.application_id:
                raise HTTPException(404)

        try:
            await send_custom_message_to_user(aid, message_text)
        except Exception as exc:
            print(f"Custom message error for application {aid}: {exc}")
            return RedirectResponse(f"/admin/application/{aid}?message_error=send", 303)
        return RedirectResponse(f"/admin/application/{aid}?message_sent=1", 303)


    @app.post("/admin/application/{aid}/delete")
    async def delete_application(request: Request, aid: int):
        if not auth(request):
            raise HTTPException(403)
        paths: list[str] = []
        async with Session() as session:
            application = await session.get(Application, aid, with_for_update=True)
            if not application:
                raise HTTPException(404)
            submissions = (await session.scalars(select(Submission).where(Submission.application_id == aid))).all()
            paths.extend(x.file_path for x in submissions if x.file_path)
            if application.receipt_file:
                paths.append(application.receipt_file)
            final_payment = (await session.scalars(select(FinalPayment).where(FinalPayment.application_id == aid))).first()
            if final_payment and final_payment.receipt_file:
                paths.append(final_payment.receipt_file)

            # Child records use cascade FKs where available; explicit deletes keep SQLite/Postgres consistent.
            for model in (Submission, FinalPayment, Rating, StatusEvent):
                rows = (await session.scalars(select(model).where(model.application_id == aid))).all()
                for row in rows:
                    await session.delete(row)
            await session.delete(application)
            await session.commit()

        for path in paths:
            try:
                if path and os.path.isfile(path):
                    os.remove(path)
            except OSError:
                pass
        return RedirectResponse("/admin?deleted=1", 303)

    def file_viewer_html(title: str, raw_url: str, download_url: str, back_url: str, filename: str) -> HTMLResponse:
        safe_title = html.escape(title)
        safe_raw = html.escape(raw_url, quote=True)
        safe_download = html.escape(download_url, quote=True)
        safe_back = html.escape(back_url, quote=True)
        safe_name = html.escape(filename)
        media_type, _ = mimetypes.guess_type(filename)
        is_pdf = media_type == "application/pdf"

        if is_pdf:
            preview = f'<iframe class="preview-frame" src="{safe_raw}" title="{safe_title}"></iframe>'
        else:
            preview = f'<img class="preview-image" src="{safe_raw}" alt="{safe_title}">'

        page = f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#14213d">
  <title>{safe_title} - IBW Admin</title>
  <style>
    *{{box-sizing:border-box}}
    body{{margin:0;background:#eef2f7;color:#162033;font-family:Arial,sans-serif;min-height:100vh}}
    .topbar{{position:sticky;top:0;z-index:10;background:#14213d;color:#fff;padding:12px 14px;display:flex;align-items:center;gap:10px;box-shadow:0 2px 12px rgba(0,0,0,.2)}}
    .topbar h1{{font-size:16px;margin:0;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
    .btn{{display:inline-flex;align-items:center;justify-content:center;text-decoration:none;border:0;border-radius:10px;padding:10px 14px;font-weight:700;font-size:14px;cursor:pointer}}
    .back{{background:#fff;color:#14213d}}
    .save{{background:#1877e8;color:#fff}}
    .wrap{{max-width:1100px;margin:0 auto;padding:14px}}
    .card{{background:#fff;border-radius:14px;padding:10px;box-shadow:0 6px 22px rgba(16,35,70,.12)}}
    .filename{{font-size:13px;color:#667085;margin:2px 4px 10px;word-break:break-all}}
    .preview-image{{display:block;max-width:100%;height:auto;max-height:calc(100vh - 145px);margin:auto;border-radius:8px;object-fit:contain}}
    .preview-frame{{display:block;width:100%;height:calc(100vh - 145px);border:0;border-radius:8px;background:#fff}}
    @media(max-width:520px){{.topbar{{padding:10px}}.btn{{padding:9px 11px}}.wrap{{padding:8px}}.card{{padding:7px}}}}
  </style>
</head>
<body>
  <header class="topbar">
    <a class="btn back" href="{safe_back}" onclick="if(history.length>1){{event.preventDefault();history.back();}}">← Back</a>
    <h1>{safe_title}</h1>
    <a class="btn save" href="{safe_download}">⬇ Save</a>
  </header>
  <main class="wrap">
    <div class="card">
      <div class="filename">{safe_name}</div>
      {preview}
    </div>
  </main>
</body>
</html>'''
        response = HTMLResponse(page)
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        return response

    def downloadable_file_response(path: str) -> FileResponse:
        media_type, _ = mimetypes.guess_type(path)
        response = FileResponse(
            path,
            media_type=media_type or "application/octet-stream",
            filename=os.path.basename(path),
            content_disposition_type="attachment",
        )
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/admin/file/{sid}")
    async def private_file_viewer(request: Request, sid: int):
        if not auth(request):
            return RedirectResponse(f"/login?next=/admin/file/{sid}", 303)
        async with Session() as session:
            sub = await session.get(Submission, sid)
        resolved = resolve_stored_file(sub.file_path if sub else None)
        if not resolved:
            raise HTTPException(404, "Document file is unavailable on server storage")
        back_url = f"/admin/application/{sub.application_id}" if sub else "/admin"
        return file_viewer_html("Submitted Document", f"/admin/file/{sid}/raw", f"/admin/file/{sid}/download", back_url, os.path.basename(resolved))

    @app.get("/admin/file/{sid}/raw")
    async def private_file_raw(request: Request, sid: int):
        if not auth(request):
            return RedirectResponse(f"/login?next=/admin/file/{sid}", 303)
        async with Session() as session:
            sub = await session.get(Submission, sid)
        resolved = resolve_stored_file(sub.file_path if sub else None)
        if not resolved:
            raise HTTPException(404, "Document file is unavailable on server storage")
        return protected_file_response(resolved)

    @app.get("/admin/file/{sid}/download")
    async def private_file_download(request: Request, sid: int):
        if not auth(request):
            return RedirectResponse(f"/login?next=/admin/file/{sid}", 303)
        async with Session() as session:
            sub = await session.get(Submission, sid)
        resolved = resolve_stored_file(sub.file_path if sub else None)
        if not resolved:
            raise HTTPException(404, "Document file is unavailable on server storage")
        return downloadable_file_response(resolved)

    @app.get("/admin/receipt/{aid}")
    async def receipt_viewer(request: Request, aid: int):
        if not auth(request):
            return RedirectResponse(f"/login?next=/admin/receipt/{aid}", 303)
        async with Session() as session:
            application = await session.get(Application, aid)
        resolved = resolve_stored_file(application.receipt_file if application else None)
        if not resolved:
            raise HTTPException(404, "Payment receipt is unavailable on server storage")
        return file_viewer_html("Initial Payment Receipt", f"/admin/receipt/{aid}/raw", f"/admin/receipt/{aid}/download", f"/admin/application/{aid}", os.path.basename(resolved))

    @app.get("/admin/receipt/{aid}/raw")
    async def receipt_raw(request: Request, aid: int):
        if not auth(request):
            return RedirectResponse(f"/login?next=/admin/receipt/{aid}", 303)
        async with Session() as session:
            application = await session.get(Application, aid)
        resolved = resolve_stored_file(application.receipt_file if application else None)
        if not resolved:
            raise HTTPException(404, "Payment receipt is unavailable on server storage")
        return protected_file_response(resolved)

    @app.get("/admin/receipt/{aid}/download")
    async def receipt_download(request: Request, aid: int):
        if not auth(request):
            return RedirectResponse(f"/login?next=/admin/receipt/{aid}", 303)
        async with Session() as session:
            application = await session.get(Application, aid)
        resolved = resolve_stored_file(application.receipt_file if application else None)
        if not resolved:
            raise HTTPException(404, "Payment receipt is unavailable on server storage")
        return downloadable_file_response(resolved)

    @app.get("/admin/final-receipt/{aid}")
    async def final_receipt_viewer(request: Request, aid: int):
        if not auth(request):
            return RedirectResponse(f"/login?next=/admin/final-receipt/{aid}", 303)
        async with Session() as session:
            payment = (await session.scalars(select(FinalPayment).where(FinalPayment.application_id == aid))).first()
        resolved = resolve_stored_file(payment.receipt_file if payment else None)
        if not resolved:
            raise HTTPException(404, "Final payment receipt is unavailable on server storage")
        return file_viewer_html("Final Payment Receipt", f"/admin/final-receipt/{aid}/raw", f"/admin/final-receipt/{aid}/download", f"/admin/application/{aid}", os.path.basename(resolved))

    @app.get("/admin/final-receipt/{aid}/raw")
    async def final_receipt_raw(request: Request, aid: int):
        if not auth(request):
            return RedirectResponse(f"/login?next=/admin/final-receipt/{aid}", 303)
        async with Session() as session:
            payment = (await session.scalars(select(FinalPayment).where(FinalPayment.application_id == aid))).first()
        resolved = resolve_stored_file(payment.receipt_file if payment else None)
        if not resolved:
            raise HTTPException(404, "Final payment receipt is unavailable on server storage")
        return protected_file_response(resolved)

    @app.get("/admin/final-receipt/{aid}/download")
    async def final_receipt_download(request: Request, aid: int):
        if not auth(request):
            return RedirectResponse(f"/login?next=/admin/final-receipt/{aid}", 303)
        async with Session() as session:
            payment = (await session.scalars(select(FinalPayment).where(FinalPayment.application_id == aid))).first()
        resolved = resolve_stored_file(payment.receipt_file if payment else None)
        if not resolved:
            raise HTTPException(404, "Final payment receipt is unavailable on server storage")
        return downloadable_file_response(resolved)

    from app.miniapp import register_miniapp_routes
    register_miniapp_routes(app)

    from app.website import register_website_routes
    register_website_routes(app)

    return app
