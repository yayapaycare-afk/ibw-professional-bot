import html
import json
import os
import re
import uuid
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode, ChatType
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db import Session, setting_value
from app.models import User, Wallet, DocumentRule, Application, Submission, FinalPayment, Rating

settings = get_settings()
group_router = Router(name="group_privacy")
router = Router(name="private_bot")

group_router.message.filter(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
group_router.callback_query.filter(F.message.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))

# All application and payment handlers are private-chat only.
router.message.filter(F.chat.type == ChatType.PRIVATE)
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)

TERMS_TEXT = """📜 नियम एवं शर्तें — India Business Wallets

कृपया सेवा लेने से पहले नीचे दिए गए सभी नियम ध्यानपूर्वक पढ़ें।

✅ Verified Service
जिस Bot के माध्यम से आपने हमसे संपर्क किया है, वह India Business Wallets का सत्यापित Bot है। हमारी टीम सुरक्षित और पारदर्शी तरीके से Business Wallet खुलवाने में सहायता करती है।

📱 केवल अधिकृत Agent से संपर्क करें
WhatsApp पर केवल उसी Direct Agent Contact Number से बात करें, जो आपको India Business Wallets bot के आधिकारिक माध्यम से दिया गया हो। किसी अनजान नंबर या व्यक्ति पर भरोसा न करें।

🔐 OTP और Password की सुरक्षा
अपना बैंक पासवर्ड, ईमेल पासवर्ड या अन्य गोपनीय जानकारी किसी अन्य व्यक्ति के साथ साझा न करें। 

💳 दो भागों में भुगतान
Wallet खुलवाते समय पूरी Service Fee एक साथ नहीं देनी होगी। भुगतान दो भागों में किया जाएगा:

• पहला भुगतान: कुल Fee का लगभग 70%–80% आवेदन और प्रक्रिया शुरू करते समय देना होगा।
• दूसरा भुगतान: बची हुई लगभग 20%–30% Fee आपका Wallet तैयार होने के बाद देनी होगी।

⚠️ पूरा भुगतान करना अनिवार्य है
Wallet तैयार होने के बाद निर्धारित समय के अंदर बची हुई पूरी Fee का भुगतान करें। भुगतान पूरा न करने पर हमारी Service, Support और भविष्य में मिलने वाली सहायता बंद की जा सकती है। नियमों का उल्लंघन होने पर Wallet Service प्रभावित या Disabled भी हो सकती है, जिसकी जिम्मेदारी उपयोगकर्ता की होगी।

💰 अतिरिक्त भुगतान न करें
निर्धारित Service Fee के अलावा Agent को कोई अतिरिक्त भुगतान न करें। यदि कोई Agent Extra Charge की मांग करता है, तो तुरंत उस आधिकारिक WhatsApp नंबर पर शिकायत करें, जिस पर आपने सबसे पहले संपर्क किया था।

Kripya yah terms 

⏳ प्रक्रिया में समय लग सकता है
कभी-कभी बैंक, कंपनी की जाँच या तकनीकी कारणों से Wallet बनने में देरी हो सकती है। ऐसी स्थिति में धैर्य रखें और समय-समय पर अपना Application Status चेक करते रहें।

🛡️ आपका भुगतान सुरक्षित है
यदि किसी वैध कारण से आपका Wallet नहीं बन पाता है, तो हमारी Refund Policy के अनुसार आपको जमा की गई योग्य राशि का 100% Refund दिया जाएगा।

💵 Refund कैसे प्राप्त करें?
सबसे पहले अपने अधिकृत Direct Agent से Refund के लिए संपर्क करें। यदि Agent Refund देने से मना करता है या जवाब नहीं देता, तो उस आधिकारिक WhatsApp Contact पर शिकायत करें, जिस पर आपने सबसे पहले संपर्क किया था। हमारी Support Team आपकी सहायता करेगी।

🚫 धोखाधड़ी से सावधान रहें

✅ Service का उपयोग करने पर यह माना जाएगा कि आपने सभी नियम एवं शर्तें ध्यानपूर्वक पढ़ ली हैं और उनसे सहमत हैं।"""

GROUP_PRIVACY_TEXT = """🔐 <b>Privacy & Security Notice</b>

कृपया अपने Documents या व्यक्तिगत जानकारी इस Group में साझा न करें।

इस Group में अन्य सदस्य मौजूद हैं। Aadhaar Card, PAN Card, Bank Details, Mobile Number और Payment Receipt केवल Bot की Private Chat में submit करें।

नीचे दिए गए button से Bot को privately खोलकर अपनी Application पूरी करें।

⚠️ OTP, UPI PIN, Password या Card PIN कभी साझा न करें।"""

GROUP_UPLOAD_WARNING = """⚠️ <b>Documents Group में न भेजें</b>

आपकी Privacy और Security के लिए सभी Documents केवल Bot की Private Chat में submit किए जाते हैं।

नीचे दिए गए button से Bot को privately खोलें।"""


async def private_bot_keyboard(bot: Bot, label: str = "🔒 Open Bot Privately") -> InlineKeyboardMarkup:
    me = await bot.get_me()
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, url=f"https://t.me/{me.username}?start=private")],
    ])


async def group_main_menu(bot: Bot) -> InlineKeyboardMarkup:
    me = await bot.get_me()
    private_url = f"https://t.me/{me.username}?start=private"
    channel_url = settings.official_channel or "https://t.me/"

    # One full-width button per row prevents truncation in narrow group chats.
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 View Wallet Services", callback_data="g:apply")],
        [InlineKeyboardButton(text="📜 Terms & Conditions", callback_data="g:terms")],
        [InlineKeyboardButton(text="🔒 Open Bot Privately", url=private_url)],
        [InlineKeyboardButton(text="📢 Official Channel", url=channel_url)],
    ])


async def send_group_dashboard(message: Message, bot: Bot) -> None:
    first_name = message.from_user.first_name if message.from_user else "User"
    available = (await setting_value("service_available", "true")).lower() == "true"
    status = "🟢 ONLINE (Active)" if available else "🔴 OFFLINE (Unavailable)"
    today = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d %B %Y")

    # Lines are intentionally kept short for Telegram group bubbles.
    dashboard_text = (
        "🏛 <b>Welcome to IBW Bot</b>\n"
        "━━━━━━━━━━━━\n\n"
        f"👋 Hi {html.escape(first_name)},\n"
        "Welcome to our official Bot.\n\n"
        "🔐 Trusted Business Wallet\n"
        "Services available across India 🇮🇳\n\n"
        f"<b>Status:</b> {status}\n"
        f"📅 <b>Date:</b> {today}\n\n"
        "━━━━━━━━━━━━\n"
        "📋 पहले Terms जरूर पढ़ें 🔞\n\n"
        "नीचे से Service चुनें 👇"
    )

    await message.answer(
        dashboard_text,
        reply_markup=await group_main_menu(bot),
        parse_mode=ParseMode.HTML,
    )


async def send_group_privacy_notice(message: Message, bot: Bot, short: bool = False) -> None:
    mention = f'<a href="tg://user?id={message.from_user.id}">{html.escape(message.from_user.first_name or "User")}</a>' if message.from_user else "User"
    text = GROUP_UPLOAD_WARNING if short else GROUP_PRIVACY_TEXT
    await message.answer(
        f"{mention}\n\n{text}",
        reply_markup=await private_bot_keyboard(bot),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


@group_router.message(F.new_chat_members)
async def bot_added_to_group(message: Message, bot: Bot):
    if any(member.id == bot.id for member in message.new_chat_members):
        await send_group_dashboard(message, bot)


@group_router.message(CommandStart())
async def group_start(message: Message, bot: Bot):
    await send_group_dashboard(message, bot)


@group_router.callback_query(F.data == "g:apply")
async def group_apply(callback: CallbackQuery, bot: Bot):
    async with Session() as session:
        wallets = (await session.scalars(select(Wallet).where(Wallet.active.is_(True)).order_by(Wallet.sort_order, Wallet.id))).all()
    if not wallets:
        await callback.message.answer("Abhi koi wallet service available nahi hai.")
    else:
        rows = [[InlineKeyboardButton(text=f"🏦 {w.name}", callback_data=f"g:wallet:{w.id}")] for w in wallets]
        rows.append([InlineKeyboardButton(text="🏠 Main Menu", callback_data="g:home")])
        await callback.message.answer("🏦 <b>Select a Business Wallet</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode=ParseMode.HTML)
    await callback.answer()


@group_router.callback_query(F.data.startswith("g:wallet:"))
async def group_wallet_details(callback: CallbackQuery, bot: Bot):
    wallet_id = int(callback.data.rsplit(":", 1)[1])
    async with Session() as session:
        wallet = await session.get(Wallet, wallet_id)
        docs = (await session.scalars(select(DocumentRule).where(DocumentRule.wallet_id == wallet_id).order_by(DocumentRule.sort_order, DocumentRule.id))).all()
    if not wallet or not wallet.active:
        await callback.answer("Wallet unavailable.", show_alert=True)
        return
    due = round(wallet.total_fee * wallet.initial_percent / 100)
    remaining = max(wallet.total_fee - due, 0)
    doc_lines = "\n".join(f"• {html.escape(d.name)}" for d in docs) or "• Admin has not added documents yet"
    me = await bot.get_me()
    private_url = f"https://t.me/{me.username}?start=private"
    text = (
        f"🏦 <b>{html.escape(wallet.name)}</b>\n\n"
        f"{html.escape(wallet.description or '')}\n\n"
        f"📄 <b>Required Documents</b>\n{doc_lines}\n\n"
        f"💰 Total Fee: ₹{wallet.total_fee}\n"
        f"💳 First Payment: {wallet.initial_percent}% — ₹{due}\n"
        f"💵 Remaining Payment: ₹{remaining}\n"
        f"⏱ Processing Time: {html.escape(wallet.processing_time)}\n\n"
        "🔐 Application और Documents submit करने के लिए Bot को Private Chat में खोलें।"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Continue Application", callback_data=f"g:continue:{wallet_id}")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="g:apply"), InlineKeyboardButton(text="🏠 Main Menu", callback_data="g:home")],
    ])
    await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await callback.answer()


@group_router.callback_query(F.data.startswith("g:continue:"))
async def group_continue_application(callback: CallbackQuery, bot: Bot):
    """Show privacy warning only after the user explicitly continues in a group."""
    me = await bot.get_me()
    private_url = f"https://t.me/{me.username}?start=private"
    mention = (
        f'<a href="tg://user?id={callback.from_user.id}">'
        f'{html.escape(callback.from_user.first_name or "User")}</a>'
    )
    text = (
        f"{mention}\n\n"
        "🔐 <b>Private Documents Notice</b>\n\n"
        "Application continue करने और Aadhaar, PAN, Bank Details या Payment Receipt "
        "submit करने के लिए Bot की Private Chat खोलें।\n\n"
        "⚠️ Group में कोई personal document या payment receipt share न करें।"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔒 Open Bot Privately", url=private_url)],
        [InlineKeyboardButton(text="🔙 Back to Wallets", callback_data="g:apply")],
    ])
    await callback.message.answer(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    await callback.answer()


@group_router.callback_query(F.data == "g:terms")
async def group_terms(callback: CallbackQuery):
    await callback.message.answer(TERMS_TEXT, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 Main Menu", callback_data="g:home")]]))
    await callback.answer()


@group_router.callback_query(F.data == "g:home")
async def group_home(callback: CallbackQuery, bot: Bot):
    await send_group_dashboard(callback.message, bot)
    await callback.answer()


@group_router.message(F.text)
async def group_keyword_info(message: Message, bot: Bot):
    text_value = re.sub(r"[^a-z0-9 @]+", " ", (message.text or "").lower())
    normalized = " ".join(text_value.split())
    me = await bot.get_me()
    bot_mentioned = bool(me.username and f"@{me.username.lower()}" in normalized)
    replied_to_bot = bool(message.reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.id == bot.id)
    matched = normalized in START_KEYWORDS or any(
        phrase in normalized for phrase in (
            "business wallet", "wallet open", "open wallet", "google pay business",
            "paytm business", "bharatpe business", "phonepe business",
            "mobikwik business", "bajaj pay business"
        )
    )
    if matched or bot_mentioned or replied_to_bot:
        await send_group_dashboard(message, bot)


class Flow(StatesGroup):
    document_input = State()
    bank_account = State()
    bank_ifsc = State()
    initial_utr = State()
    initial_receipt = State()
    final_utr = State()
    final_receipt = State()
    track = State()


def main_menu() -> InlineKeyboardMarkup:
    channel_url = settings.official_channel or "https://t.me/"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Apply Now", callback_data="apply")],
        [
            InlineKeyboardButton(text="🔍 Track Status", callback_data="track"),
            InlineKeyboardButton(text="📂 My Applications", callback_data="mine"),
        ],
        [
            InlineKeyboardButton(text="💬 Support", callback_data="support"),
            InlineKeyboardButton(text="📜 Terms", callback_data="terms"),
        ],
        [InlineKeyboardButton(text="📢 Official Channel", url=channel_url)],
    ])


def navigation(back: str = "home") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data=back), InlineKeyboardButton(text="🏠 Main Menu", callback_data="home")]
    ])


async def ensure_user(message: Message):
    async with Session() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            session.add(User(telegram_id=message.from_user.id, full_name=message.from_user.full_name, username=message.from_user.username))
        else:
            user.full_name = message.from_user.full_name
            user.username = message.from_user.username
        await session.commit()


async def welcome_caption(first_name: str) -> str:
    available = (await setting_value("service_available", "true")).lower() == "true"
    system_status = "🟢 ONLINE (Active)" if available else "🔴 OFFLINE (Unavailable)"
    today = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d %B %Y")
    return (
        "🏛 <b>Welcome to IBW Bot</b>\n"
        "──────────────────────────\n"
        f"👋 Hi {html.escape(first_name)},\n"
        "Welcome to our official Bot.\n\n"
        "🔐 Trusted Business Wallets opening Online services across India 🇮🇳\n\n"
        f"<b>System Status:</b> {system_status}\n"
        f"📅 <b>Date:</b> {today}\n"
        "──────────────────────────\n"
        "📋 <b>Notice:</b> Proceed karne se pehle Terms zaroor padhein 🔞\n\n"
        "Services select karne ke liye niche click karein:👇"
    )


async def send_home(target: Message):
    dashboard_text = await welcome_caption(target.chat.first_name or "User")
    await target.answer(
        dashboard_text,
        reply_markup=main_menu(),
        parse_mode=ParseMode.HTML,
    )


@router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await ensure_user(message)
    await send_home(message)


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Current process cancelled.", reply_markup=main_menu())


@router.callback_query(F.data == "home")
async def home(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await send_home(callback.message)


@router.callback_query(F.data == "apply")
async def apply(callback: CallbackQuery):
    async with Session() as session:
        wallets = (await session.scalars(select(Wallet).where(Wallet.active.is_(True)).order_by(Wallet.sort_order, Wallet.id))).all()
    if not wallets:
        await callback.message.answer("Abhi koi wallet service available nahi hai.", reply_markup=navigation())
    else:
        rows = [[InlineKeyboardButton(text=f"🏦 {w.name}", callback_data=f"wallet:{w.id}")] for w in wallets]
        rows.append([InlineKeyboardButton(text="🔙 Back", callback_data="home"), InlineKeyboardButton(text="🏠 Main Menu", callback_data="home")])
        await callback.message.answer("🏦 <b>Select a Business Wallet</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith("wallet:"))
async def wallet_details(callback: CallbackQuery):
    wallet_id = int(callback.data.split(":", 1)[1])
    async with Session() as session:
        wallet = await session.get(Wallet, wallet_id)
        docs = (await session.scalars(select(DocumentRule).where(DocumentRule.wallet_id == wallet_id).order_by(DocumentRule.sort_order, DocumentRule.id))).all()
    if not wallet or not wallet.active:
        await callback.answer("Wallet unavailable.", show_alert=True)
        return
    due = round(wallet.total_fee * wallet.initial_percent / 100)
    remaining = max(wallet.total_fee - due, 0)
    doc_lines = "\n".join(f"• {html.escape(d.name)}" for d in docs) or "• Admin has not added documents yet"
    text = (
        f"🏦 <b>{html.escape(wallet.name)}</b>\n\n"
        f"{html.escape(wallet.description or '')}\n\n"
        f"📄 <b>Required Documents</b>\n{doc_lines}\n\n"
        f"💰 Total Fee: ₹{wallet.total_fee}\n"
        f"💳 First Payment: {wallet.initial_percent}% — ₹{due}\n"
        f"🏷 Banking Name: {html.escape(wallet.banking_name or 'Shown after continue')}\n"
        f"💵 Remaining Payment: ₹{remaining}\n"
        f"⏱ Processing Time: {html.escape(wallet.processing_time)}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Continue Application", callback_data=f"continue:{wallet_id}")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="apply"), InlineKeyboardButton(text="🏠 Main Menu", callback_data="home")],
    ])
    await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("continue:"))
async def continue_application(callback: CallbackQuery, state: FSMContext):
    wallet_id = int(callback.data.split(":", 1)[1])
    async with Session() as session:
        wallet = await session.get(Wallet, wallet_id)
        if not wallet or not wallet.active:
            await callback.answer("Wallet unavailable.", show_alert=True)
            return
        app = Application(user_id=callback.from_user.id, wallet_id=wallet_id, status="DOCUMENTS_PENDING", amount_due=round(wallet.total_fee * wallet.initial_percent / 100))
        session.add(app)
        await session.commit()
        await session.refresh(app)
    await state.update_data(app_db_id=app.id, wallet_id=wallet_id, doc_index=0)
    await callback.answer()
    await ask_next_document(callback.message, state)


async def ask_next_document(message: Message, state: FSMContext):
    data = await state.get_data()
    async with Session() as session:
        docs = (await session.scalars(select(DocumentRule).where(DocumentRule.wallet_id == data["wallet_id"]).order_by(DocumentRule.sort_order, DocumentRule.id))).all()
    index = data.get("doc_index", 0)
    if index >= len(docs):
        await show_initial_payment(message, state)
        return
    doc = docs[index]
    await state.update_data(current_doc_id=doc.id, current_kind=doc.manual_kind, current_name=doc.name)
    buttons = []
    if doc.upload_allowed:
        buttons.append([InlineKeyboardButton(text=f"📤 Upload {doc.name}", callback_data="doc:upload")])
    if doc.manual_allowed:
        buttons.append([InlineKeyboardButton(text=f"✍️ {doc.manual_label}", callback_data="doc:manual")])
    buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="apply"), InlineKeyboardButton(text="🏠 Main Menu", callback_data="home")])
    await message.answer(f"📄 <b>{html.escape(doc.name)}</b>\n\nSubmission method select karein:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data == "doc:upload")
async def choose_upload(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Flow.document_input)
    await state.update_data(input_method="upload")
    await callback.message.answer("Document ko image ya PDF ke roop mein bhejein.", reply_markup=navigation("apply"))
    await callback.answer()


@router.callback_query(F.data == "doc:manual")
async def choose_manual(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    kind = (data.get("current_kind") or "single").strip().lower()
    name = (data.get("current_name") or "details").strip()
    normalized_name = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()

    # Treat bank/account documents as two-step manual input even when an older
    # admin record was accidentally saved with the generic validation type.
    is_bank_document = (
        kind == "bank"
        or "bank detail" in normalized_name
        or "bank account" in normalized_name
        or "account detail" in normalized_name
        or normalized_name in {"bank", "account number", "account"}
    )

    if is_bank_document:
        await state.update_data(current_kind="bank")
        await state.set_state(Flow.bank_account)
        await callback.message.answer(
            "🏦 Account Number enter karein:",
            reply_markup=navigation("apply"),
        )
    else:
        await state.set_state(Flow.document_input)
        await state.update_data(input_method="manual")
        prompt = {
            "mobile": "10-digit Mobile Number enter karein:",
            "aadhaar": "12-digit Aadhaar Number enter karein:",
            "pan": "PAN Number enter karein:",
        }.get(kind, f"{name} ka number/details enter karein:")
        await callback.message.answer(prompt, reply_markup=navigation("apply"))
    await callback.answer()


def validate_manual(kind: str, value: str) -> str | None:
    value = value.strip()
    if kind == "mobile" and not re.fullmatch(r"[6-9]\d{9}", re.sub(r"\D", "", value)):
        return "Valid 10-digit Indian mobile number enter karein."
    if kind == "aadhaar" and not re.fullmatch(r"\d{12}", re.sub(r"\D", "", value)):
        return "Valid 12-digit Aadhaar number enter karein."
    if kind == "pan" and not re.fullmatch(r"[A-Za-z]{5}\d{4}[A-Za-z]", value):
        return "Valid PAN number enter karein, jaise ABCDE1234F."
    if len(value) < 2:
        return "Valid value enter karein."
    return None


async def save_submission(state: FSMContext, method: str, manual_value: str | None = None, file_path: str | None = None):
    data = await state.get_data()
    async with Session() as session:
        existing = (await session.scalars(select(Submission).where(Submission.application_id == data["app_db_id"], Submission.document_rule_id == data["current_doc_id"]))).first()
        if existing:
            existing.method = method; existing.manual_value = manual_value; existing.file_path = file_path
        else:
            session.add(Submission(application_id=data["app_db_id"], document_rule_id=data["current_doc_id"], method=method, manual_value=manual_value, file_path=file_path))
        await session.commit()
    await state.update_data(doc_index=data.get("doc_index", 0) + 1)


@router.message(Flow.document_input)
async def document_input(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    if data.get("input_method") == "upload":
        telegram_file = message.document or (message.photo[-1] if message.photo else None)
        if not telegram_file:
            await message.answer("Sirf image ya PDF bhejein.")
            return
        if message.document and message.document.mime_type not in {"application/pdf", "image/jpeg", "image/png"}:
            await message.answer("Accepted format: JPG, PNG ya PDF.")
            return
        os.makedirs(settings.storage_dir, exist_ok=True)
        ext = ".pdf" if message.document and message.document.mime_type == "application/pdf" else ".jpg"
        path = os.path.join(settings.storage_dir, f"doc_{uuid.uuid4().hex}{ext}")
        await bot.download(telegram_file.file_id, destination=path)
        await save_submission(state, "upload", file_path=path)
    else:
        value = (message.text or "").strip()
        error = validate_manual(data.get("current_kind", "single"), value)
        if error:
            await message.answer(error)
            return
        await save_submission(state, "manual", manual_value=value)
    await state.set_state(None)
    await message.answer("✅ Document saved successfully.")
    await ask_next_document(message, state)


@router.message(Flow.bank_account)
async def bank_account(message: Message, state: FSMContext):
    account = re.sub(r"\s", "", message.text or "")
    if not re.fullmatch(r"\d{6,20}", account):
        await message.answer("Valid account number enter karein.")
        return
    await state.update_data(bank_account=account)
    await state.set_state(Flow.bank_ifsc)
    await message.answer("🏦 Ab IFSC Code enter karein, jaise SBIN0001234:")


@router.message(Flow.bank_ifsc)
async def bank_ifsc(message: Message, state: FSMContext):
    ifsc = (message.text or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", ifsc):
        await message.answer("Valid IFSC code enter karein.")
        return
    data = await state.get_data()
    await save_submission(state, "manual", manual_value=json.dumps({"account_number": data["bank_account"], "ifsc": ifsc}))
    await state.set_state(None)
    await message.answer("✅ Account Number aur IFSC Code successfully saved.")
    await ask_next_document(message, state)


async def show_initial_payment(message: Message, state: FSMContext):
    data = await state.get_data()
    async with Session() as session:
        app = await session.get(Application, data["app_db_id"])
        wallet = await session.get(Wallet, app.wallet_id)
        app.status = "INITIAL_PAYMENT_PENDING"
        await session.commit()
    remaining = max(wallet.total_fee - app.amount_due, 0)
    text = (
        f"💳 <b>First Payment</b>\n\n"
        f"🏦 Wallet: {html.escape(wallet.name)}\n"
        f"💰 Total Fee: ₹{wallet.total_fee}\n"
        f"📥 Pay Now ({wallet.initial_percent}%): ₹{app.amount_due}\n"
        f"💵 Remaining: ₹{remaining}\n"
        f"🏷 Banking Name: <b>{html.escape(wallet.banking_name or 'Not configured')}</b>\n\n"
        f"UPI ID: <code>{html.escape(wallet.upi_id or 'Admin will provide')}</code>\n\n"
        "Payment karne se pehle UPI app mein Banking Name verify karein."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ I Have Made the Payment", callback_data=f"initial-paid:{app.id}")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="apply"), InlineKeyboardButton(text="🏠 Main Menu", callback_data="home")],
    ])
    if wallet.qr_file and os.path.exists(wallet.qr_file):
        await message.answer_photo(FSInputFile(wallet.qr_file), caption=text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("initial-paid:"))
async def initial_paid(callback: CallbackQuery, state: FSMContext):
    app_id = int(callback.data.split(":", 1)[1])
    await state.update_data(app_db_id=app_id)
    await state.set_state(Flow.initial_utr)
    await callback.message.answer("Payment ka UTR/Transaction Reference Number enter karein:", reply_markup=navigation())
    await callback.answer()


@router.message(Flow.initial_utr)
async def initial_utr(message: Message, state: FSMContext):
    utr = re.sub(r"\s", "", message.text or "")
    if not re.fullmatch(r"[A-Za-z0-9]{6,30}", utr):
        await message.answer("Valid UTR number enter karein.")
        return
    async with Session() as session:
        duplicate = (await session.scalars(select(Application).where(Application.utr == utr))).first()
    if duplicate:
        await message.answer("Ye UTR pehle submit ho chuka hai. Sahi UTR enter karein.")
        return
    await state.update_data(initial_utr=utr)
    await state.set_state(Flow.initial_receipt)
    await message.answer("Payment receipt image ya PDF upload karein:")


@router.message(Flow.initial_receipt)
async def initial_receipt(message: Message, state: FSMContext, bot: Bot):
    file_obj = message.document or (message.photo[-1] if message.photo else None)
    if not file_obj:
        await message.answer("Receipt image ya PDF upload karein.")
        return
    os.makedirs(settings.storage_dir, exist_ok=True)
    ext = ".pdf" if message.document and message.document.mime_type == "application/pdf" else ".jpg"
    path = os.path.join(settings.storage_dir, f"receipt_{uuid.uuid4().hex}{ext}")
    await bot.download(file_obj.file_id, destination=path)
    data = await state.get_data()
    async with Session() as session:
        app = await session.get(Application, data["app_db_id"])
        app.utr = data["initial_utr"]
        app.receipt_file = path
        app.status = "PAYMENT_UNDER_VERIFICATION"
        if not app.application_id:
            app.application_id = f"IBW-{datetime.now(ZoneInfo('Asia/Kolkata')).year}-{app.id:06d}"
        wallet = await session.get(Wallet, app.wallet_id)
        await session.commit()
        await session.refresh(app)
    wa_text = f"Hello, I submitted my {wallet.name} application. Application ID: {app.application_id}. Please check it."
    wa_url = f"https://wa.me/{settings.whatsapp_number}?text={quote(wa_text)}" if settings.whatsapp_number else settings.public_base_url
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Contact Through WhatsApp", url=wa_url)],
        [InlineKeyboardButton(text="📂 My Applications", callback_data="mine"), InlineKeyboardButton(text="🏠 Main Menu", callback_data="home")],
    ])
    await state.clear()
    await message.answer(
        f"🎉 <b>Application Submitted Successfully</b>\n\nApplication ID: <code>{app.application_id}</code>\nPayment Status: Under Verification",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("final-paid:"))
async def final_paid(callback: CallbackQuery, state: FSMContext):
    app_id = int(callback.data.split(":", 1)[1])
    async with Session() as session:
        app = await session.get(Application, app_id)
    if not app or app.user_id != callback.from_user.id:
        await callback.answer("Application not found.", show_alert=True)
        return
    await state.update_data(final_app_id=app_id)
    await state.set_state(Flow.final_utr)
    await callback.message.answer("Final payment ka UTR Number enter karein:", reply_markup=navigation())
    await callback.answer()


@router.message(Flow.final_utr)
async def final_utr(message: Message, state: FSMContext):
    utr = re.sub(r"\s", "", message.text or "")
    if not re.fullmatch(r"[A-Za-z0-9]{6,30}", utr):
        await message.answer("Valid UTR number enter karein.")
        return
    async with Session() as session:
        duplicate = (await session.scalars(select(FinalPayment).where(FinalPayment.utr == utr))).first()
    if duplicate:
        await message.answer("Ye UTR pehle submit ho chuka hai.")
        return
    await state.update_data(final_utr=utr)
    await state.set_state(Flow.final_receipt)
    await message.answer("Final payment receipt image ya PDF upload karein:")


@router.message(Flow.final_receipt)
async def final_receipt(message: Message, state: FSMContext, bot: Bot):
    file_obj = message.document or (message.photo[-1] if message.photo else None)
    if not file_obj:
        await message.answer("Receipt image ya PDF upload karein.")
        return
    os.makedirs(settings.storage_dir, exist_ok=True)
    ext = ".pdf" if message.document and message.document.mime_type == "application/pdf" else ".jpg"
    path = os.path.join(settings.storage_dir, f"final_{uuid.uuid4().hex}{ext}")
    await bot.download(file_obj.file_id, destination=path)
    data = await state.get_data()
    async with Session() as session:
        existing = (await session.scalars(select(FinalPayment).where(FinalPayment.application_id == data["final_app_id"]))).first()
        if existing:
            existing.utr = data["final_utr"]; existing.receipt_file = path; existing.status = "UNDER_VERIFICATION"
        else:
            session.add(FinalPayment(application_id=data["final_app_id"], utr=data["final_utr"], receipt_file=path))
        app = await session.get(Application, data["final_app_id"])
        app.status = "FINAL_PAYMENT_UNDER_VERIFICATION"
        await session.commit()
    await state.clear()
    await message.answer("✅ Final payment submitted. Verification ke baad status update kiya jayega.", reply_markup=main_menu())


@router.callback_query(F.data == "mine")
async def mine(callback: CallbackQuery):
    async with Session() as session:
        rows = (await session.execute(select(Application, Wallet).join(Wallet, Wallet.id == Application.wallet_id).where(Application.user_id == callback.from_user.id).order_by(Application.id.desc()).limit(20))).all()
    if not rows:
        text = "📂 <b>My Applications</b>\n\nNo applications found."
    else:
        text = "📂 <b>My Applications</b>\n\n" + "\n".join(f"• <code>{a.application_id or 'Draft'}</code> — {html.escape(w.name)} — {a.status.replace('_', ' ').title()}" for a, w in rows)
    await callback.message.answer(text, reply_markup=navigation())
    await callback.answer()


@router.callback_query(F.data == "track")
async def track(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Flow.track)
    await callback.message.answer("Application ID enter karein:", reply_markup=navigation())
    await callback.answer()


@router.message(Flow.track)
async def track_result(message: Message, state: FSMContext):
    app_id = (message.text or "").strip().upper()
    async with Session() as session:
        row = (await session.execute(select(Application, Wallet).join(Wallet, Wallet.id == Application.wallet_id).where(Application.application_id == app_id, Application.user_id == message.from_user.id))).first()
    await state.clear()
    if not row:
        await message.answer("Application not found.", reply_markup=navigation())
    else:
        app, wallet = row
        await message.answer(f"🆔 <code>{app.application_id}</code>\n🏦 {html.escape(wallet.name)}\n📌 {app.status.replace('_', ' ').title()}", reply_markup=navigation())


@router.callback_query(F.data == "terms")
async def terms(callback: CallbackQuery):
    await callback.message.answer(TERMS_TEXT, reply_markup=navigation())
    await callback.answer()


@router.callback_query(F.data == "support")
async def support(callback: CallbackQuery):
    if settings.whatsapp_number:
        url = f"https://wa.me/{settings.whatsapp_number}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Contact Support on WhatsApp", url=url)],
            [InlineKeyboardButton(text="🔙 Back", callback_data="home"), InlineKeyboardButton(text="🏠 Main Menu", callback_data="home")],
        ])
        await callback.message.answer("Authorized support se contact karne ke liye neeche button use karein.", reply_markup=kb)
    else:
        await callback.message.answer("Support number abhi configured nahi hai.", reply_markup=navigation())
    await callback.answer()


@router.callback_query(F.data.startswith("rate:"))
async def rate(callback: CallbackQuery):
    _, app_id_raw, stars_raw = callback.data.split(":")
    app_id, stars = int(app_id_raw), int(stars_raw)
    if stars not in range(1, 6):
        await callback.answer("Invalid rating.", show_alert=True)
        return
    async with Session() as session:
        app = await session.get(Application, app_id)
        if not app or app.user_id != callback.from_user.id:
            await callback.answer("Application not found.", show_alert=True)
            return
        existing = (await session.scalars(select(Rating).where(Rating.application_id == app_id))).first()
        if existing:
            await callback.answer("Rating already submitted.", show_alert=True)
            return
        session.add(Rating(application_id=app_id, user_id=callback.from_user.id, stars=stars))
        await session.commit()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("🙏 आपकी Rating के लिए धन्यवाद!\n\nआपका Feedback हमारी Service को बेहतर बनाने में मदद करता है।", reply_markup=main_menu())
    await callback.answer("Thank you!")



START_KEYWORDS = {
    "hi", "hii", "hiii", "hello", "hlo", "hey", "start", "open",
    "wallet", "business wallet", "business wallets", "wallet open",
    "google pay", "gpay", "paytm", "bharatpe", "bharat pe",
    "phonepe", "phone pe", "mobikwik", "bajaj pay"
}


@router.message(F.text)
async def keyword_start(message: Message, state: FSMContext):
    # Do not interrupt an active application/payment form.
    if await state.get_state() is not None:
        return
    text_value = re.sub(r"[^a-z0-9 ]+", " ", (message.text or "").lower())
    normalized = " ".join(text_value.split())
    matched = normalized in START_KEYWORDS or any(
        phrase in normalized for phrase in (
            "business wallet", "wallet open", "open wallet", "google pay business",
            "paytm business", "bharatpe business", "phonepe business",
            "mobikwik business", "bajaj pay business"
        )
    )
    if matched:
        await state.clear()
        await ensure_user(message)
        await send_home(message)


def create_dispatcher():
    dispatcher = Dispatcher()
    # Group privacy router must run before private application handlers.
    dispatcher.include_router(group_router)
    dispatcher.include_router(router)
    return dispatcher
