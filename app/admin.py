import html
import os
import uuid
from datetime import datetime

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db import Session
from app.models import Wallet, DocumentRule, Application, Submission, User, SystemSetting, FinalPayment, Rating, StatusEvent

settings = get_settings()
templates = Jinja2Templates(directory="app/templates")


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


def build_admin_app():
    app = FastAPI(title="IBW Admin")
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, https_only=True, same_site="lax", max_age=43200)

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
            counts = {
                "applications": await session.scalar(select(func.count(Application.id))) or 0,
                "pending": await session.scalar(select(func.count(Application.id)).where(Application.status.in_(["PAYMENT_UNDER_VERIFICATION", "FINAL_PAYMENT_UNDER_VERIFICATION"]))) or 0,
                "wallets": await session.scalar(select(func.count(Wallet.id))) or 0,
                "completed": await session.scalar(select(func.count(Application.id)).where(Application.status == "COMPLETED")) or 0,
            }
            apps = (await session.execute(select(Application, Wallet, User).join(Wallet, Wallet.id == Application.wallet_id).join(User, User.telegram_id == Application.user_id).order_by(Application.id.desc()).limit(30))).all()
            avg_rating = await session.scalar(select(func.avg(Rating.stars))) or 0
            working_hours = await get_setting(session, "working_hours", "10:00 AM – 9:30 PM")
            service_available = (await get_setting(session, "service_available", "true")) == "true"
        return templates.TemplateResponse("dashboard.html", {"request": request, "counts": counts, "apps": apps, "avg_rating": round(float(avg_rating), 1), "working_hours": working_hours, "service_available": service_available})

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
                await session.commit()
                changed = True
        if changed:
            try: await notify_status(aid, status)
            except Exception as exc: print(f"Notification error for application {aid}: {exc}")
        return RedirectResponse(f"/admin/application/{aid}?updated={'1' if changed else '0'}", 303)

    @app.post("/admin/application/{aid}/delete")
    async def delete_application(request: Request, aid: int, confirm_application_id: str = Form(...)):
        if not auth(request):
            raise HTTPException(403)
        paths: list[str] = []
        async with Session() as session:
            application = await session.get(Application, aid, with_for_update=True)
            if not application:
                raise HTTPException(404)
            expected = application.application_id or f"DRAFT-{application.id}"
            if confirm_application_id.strip().upper() != expected.upper():
                return RedirectResponse(f"/admin/application/{aid}?delete_error=1", 303)

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

    @app.get("/admin/file/{sid}")
    async def private_file(request: Request, sid: int):
        if not auth(request): raise HTTPException(403)
        async with Session() as session: sub = await session.get(Submission, sid)
        if not sub or not sub.file_path or not os.path.exists(sub.file_path): raise HTTPException(404)
        return FileResponse(sub.file_path)

    @app.get("/admin/receipt/{aid}")
    async def receipt(request: Request, aid: int):
        if not auth(request): raise HTTPException(403)
        async with Session() as session: application = await session.get(Application, aid)
        if not application or not application.receipt_file or not os.path.exists(application.receipt_file): raise HTTPException(404)
        return FileResponse(application.receipt_file)

    @app.get("/admin/final-receipt/{aid}")
    async def final_receipt(request: Request, aid: int):
        if not auth(request): raise HTTPException(403)
        async with Session() as session: payment = (await session.scalars(select(FinalPayment).where(FinalPayment.application_id == aid))).first()
        if not payment or not os.path.exists(payment.receipt_file): raise HTTPException(404)
        return FileResponse(payment.receipt_file)

    return app
