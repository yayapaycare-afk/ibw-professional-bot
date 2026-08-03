import os, re, uuid
from urllib.parse import quote
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
from sqlalchemy import select, func
from app.config import get_settings
from app.db import Session
from app.models import User, Wallet, DocumentRule, Application, Submission

settings = get_settings()
router = Router()

class Flow(StatesGroup):
    document_input = State()
    bank_account = State()
    bank_ifsc = State()
    utr = State()
    receipt = State()
    track = State()


def menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='📝 Apply for Business Wallet', callback_data='apply')],
        [InlineKeyboardButton(text='🔍 Track Application', callback_data='track'), InlineKeyboardButton(text='📂 My Applications', callback_data='mine')],
        [InlineKeyboardButton(text='💬 Contact Support', callback_data='support'), InlineKeyboardButton(text='ℹ️ How It Works', callback_data='how')],
        [InlineKeyboardButton(text='📢 Official Channel', url=settings.official_channel or 'https://t.me/')],
    ])

async def ensure_user(m: Message):
    async with Session() as s:
        u = await s.get(User, m.from_user.id)
        if not u: s.add(User(telegram_id=m.from_user.id, full_name=m.from_user.full_name, username=m.from_user.username))
        else: u.full_name, u.username = m.from_user.full_name, m.from_user.username
        await s.commit()

@router.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear(); await ensure_user(m)
    await m.answer(f'🏦 <b>{settings.business_name}</b>\n\nChoose an option below:', reply_markup=menu())

@router.message(Command('cancel'))
async def cancel(m: Message, state: FSMContext):
    await state.clear(); await m.answer('Cancelled.', reply_markup=menu())

@router.callback_query(F.data == 'apply')
async def apply(c: CallbackQuery):
    async with Session() as s:
        wallets = (await s.scalars(select(Wallet).where(Wallet.active.is_(True)).order_by(Wallet.sort_order, Wallet.id))).all()
    kb = [[InlineKeyboardButton(text=f'🏦 {w.name}', callback_data=f'wallet:{w.id}')] for w in wallets]
    kb.append([InlineKeyboardButton(text='⬅️ Back', callback_data='home')])
    await c.message.answer('Select a Business Wallet:', reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await c.answer()

@router.callback_query(F.data.startswith('wallet:'))
async def wallet_details(c: CallbackQuery):
    wid=int(c.data.split(':')[1])
    async with Session() as s:
        w=await s.get(Wallet,wid)
        docs=(await s.scalars(select(DocumentRule).where(DocumentRule.wallet_id==wid).order_by(DocumentRule.sort_order))).all()
    due=round(w.total_fee*w.initial_percent/100)
    txt=f'🏦 <b>{w.name}</b>\n\n{w.description}\n\n📄 <b>Required Documents</b>\n' + '\n'.join(f'• {d.name}' for d in docs)
    txt+=f'\n\n💰 Total Fee: ₹{w.total_fee}\n💳 Initial Payment: {w.initial_percent}% — ₹{due}\n⏱ Processing: {w.processing_time}'
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ Continue Application',callback_data=f'continue:{wid}')],[InlineKeyboardButton(text='⬅️ Back',callback_data='apply')]])
    await c.message.answer(txt,reply_markup=kb); await c.answer()

@router.callback_query(F.data.startswith('continue:'))
async def continue_app(c: CallbackQuery, state: FSMContext):
    wid=int(c.data.split(':')[1])
    async with Session() as s:
        w=await s.get(Wallet,wid)
        app=Application(user_id=c.from_user.id,wallet_id=wid,status='DOCUMENTS_PENDING',amount_due=round(w.total_fee*w.initial_percent/100))
        s.add(app); await s.commit(); await s.refresh(app)
    await state.update_data(app_db_id=app.id,wallet_id=wid,doc_index=0)
    await ask_next_document(c.message,state); await c.answer()

async def ask_next_document(m: Message,state:FSMContext):
    data=await state.get_data(); wid=data['wallet_id']; idx=data.get('doc_index',0)
    async with Session() as s:
        docs=(await s.scalars(select(DocumentRule).where(DocumentRule.wallet_id==wid).order_by(DocumentRule.sort_order))).all()
    if idx>=len(docs):
        await show_payment(m,state); return
    d=docs[idx]; await state.update_data(current_doc_id=d.id,current_kind=d.manual_kind,current_name=d.name)
    buttons=[]
    if d.upload_allowed: buttons.append([InlineKeyboardButton(text=f'📤 Upload {d.name}',callback_data='doc:upload')])
    if d.manual_allowed: buttons.append([InlineKeyboardButton(text=f'✍️ {d.manual_label}',callback_data='doc:manual')])
    await m.answer(f'📄 <b>{d.name}</b>\n\nChoose a submission method:',reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data=='doc:upload')
async def choose_upload(c:CallbackQuery,state:FSMContext):
    await state.set_state(Flow.document_input); await state.update_data(input_method='upload')
    await c.message.answer('Send the document as an image or PDF.'); await c.answer()

@router.callback_query(F.data=='doc:manual')
async def choose_manual(c:CallbackQuery,state:FSMContext):
    data=await state.get_data(); kind=data['current_kind']; name=data['current_name']
    if kind=='bank':
        await state.set_state(Flow.bank_account); await c.message.answer('Enter Account Number:')
    else:
        await state.set_state(Flow.document_input); await state.update_data(input_method='manual'); await c.message.answer(f'Enter {name}:')
    await c.answer()

@router.message(Flow.document_input)
async def document_input(m:Message,state:FSMContext):
    data=await state.get_data(); method=data.get('input_method')
    if method=='upload':
        file_id=None
        if m.document: file_id=m.document.file_id
        elif m.photo: file_id=m.photo[-1].file_id
        if not file_id: await m.answer('Please send an image or PDF.'); return
        os.makedirs(settings.storage_dir,exist_ok=True); name=f'{uuid.uuid4().hex}'
        f=await m.bot.get_file(file_id); ext=os.path.splitext(f.file_path or '')[1] or '.bin'; path=os.path.join(settings.storage_dir,name+ext)
        await m.bot.download_file(f.file_path,path); manual=None
    else:
        if not m.text or len(m.text.strip())<3: await m.answer('Enter a valid value.'); return
        path=None; manual=m.text.strip()
    async with Session() as s:
        s.add(Submission(application_id=data['app_db_id'],document_rule_id=data['current_doc_id'],method=method,manual_value=manual,file_path=path)); await s.commit()
    await state.update_data(doc_index=data['doc_index']+1); await ask_next_document(m,state)

@router.message(Flow.bank_account)
async def bank_account(m:Message,state:FSMContext):
    if not m.text or len(re.sub(r'\D','',m.text))<6: await m.answer('Enter a valid account number.'); return
    await state.update_data(bank_account=m.text.strip()); await state.set_state(Flow.bank_ifsc); await m.answer('Enter IFSC Code:')

@router.message(Flow.bank_ifsc)
async def bank_ifsc(m:Message,state:FSMContext):
    if not m.text or not re.fullmatch(r'[A-Za-z]{4}0[A-Za-z0-9]{6}',m.text.strip()): await m.answer('Enter a valid IFSC code.'); return
    data=await state.get_data(); value=f"Account Number: {data['bank_account']}\nIFSC: {m.text.strip().upper()}"
    async with Session() as s:
        s.add(Submission(application_id=data['app_db_id'],document_rule_id=data['current_doc_id'],method='manual',manual_value=value)); await s.commit()
    await state.update_data(doc_index=data['doc_index']+1); await ask_next_document(m,state)

async def show_payment(m:Message,state:FSMContext):
    data=await state.get_data()
    async with Session() as s: w=await s.get(Wallet,data['wallet_id'])
    txt=f'💳 <b>Initial Payment</b>\n\nWallet: {w.name}\nTotal Fee: ₹{w.total_fee}\nPay Now: {w.initial_percent}% — <b>₹{round(w.total_fee*w.initial_percent/100)}</b>\nRemaining: ₹{w.total_fee-round(w.total_fee*w.initial_percent/100)}\n\nUPI ID: <code>{w.upi_id or "Not configured"}</code>'
    if w.qr_file and os.path.exists(w.qr_file): await m.answer_photo(FSInputFile(w.qr_file),caption=txt,reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ I Have Paid',callback_data='paid')]]))
    else: await m.answer(txt,reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ I Have Paid',callback_data='paid')]]))

@router.callback_query(F.data=='paid')
async def paid(c:CallbackQuery,state:FSMContext):
    await state.set_state(Flow.utr); await c.message.answer('Enter UTR / Transaction Reference Number:'); await c.answer()

@router.message(Flow.utr)
async def utr(m:Message,state:FSMContext):
    v=(m.text or '').strip()
    if len(v)<6: await m.answer('Enter a valid UTR.'); return
    async with Session() as s:
        if await s.scalar(select(Application.id).where(func.upper(Application.utr)==v.upper())): await m.answer('This UTR has already been used.'); return
    await state.update_data(utr=v); await state.set_state(Flow.receipt); await m.answer('Upload payment receipt as an image or PDF:')

@router.message(Flow.receipt)
async def receipt(m:Message,state:FSMContext):
    file_id=m.document.file_id if m.document else (m.photo[-1].file_id if m.photo else None)
    if not file_id: await m.answer('Please upload an image or PDF receipt.'); return
    os.makedirs(settings.storage_dir,exist_ok=True); f=await m.bot.get_file(file_id); ext=os.path.splitext(f.file_path or '')[1] or '.bin'; path=os.path.join(settings.storage_dir,uuid.uuid4().hex+ext); await m.bot.download_file(f.file_path,path)
    data=await state.get_data()
    async with Session() as s:
        app=await s.get(Application,data['app_db_id']); app.utr=data['utr']; app.receipt_file=path; app.status='PAYMENT_UNDER_VERIFICATION'; app.application_id=f'IBW-{app.id:06d}'; await s.commit(); await s.refresh(app); w=await s.get(Wallet,app.wallet_id)
    msg=f'Hello, I submitted my {w.name} application. Application ID: {app.application_id}. Please check it.'
    url=f'https://wa.me/{settings.whatsapp_number}?text={quote(msg)}' if settings.whatsapp_number else settings.public_base_url
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='💬 Contact Through WhatsApp',url=url)],[InlineKeyboardButton(text='🏠 Main Menu',callback_data='home')]])
    await state.clear(); await m.answer(f'🎉 <b>Application Submitted Successfully</b>\n\nApplication ID: <code>{app.application_id}</code>\nPayment Status: Under Verification',reply_markup=kb)

@router.callback_query(F.data=='mine')
async def mine(c:CallbackQuery):
    async with Session() as s:
        rows=(await s.execute(select(Application,Wallet).join(Wallet,Wallet.id==Application.wallet_id).where(Application.user_id==c.from_user.id).order_by(Application.id.desc()).limit(10))).all()
    text='📂 <b>My Applications</b>\n\n' + ('No applications found.' if not rows else '\n'.join(f'• <code>{a.application_id or "Draft"}</code> — {w.name} — {a.status.replace("_"," ").title()}' for a,w in rows))
    await c.message.answer(text); await c.answer()

@router.callback_query(F.data=='track')
async def track(c:CallbackQuery,state:FSMContext): await state.set_state(Flow.track); await c.message.answer('Enter Application ID:'); await c.answer()

@router.message(Flow.track)
async def track_result(m:Message,state:FSMContext):
    async with Session() as s:
        row=(await s.execute(select(Application,Wallet).join(Wallet).where(Application.application_id==(m.text or '').strip().upper(),Application.user_id==m.from_user.id))).first()
    await state.clear(); await m.answer('Application not found.' if not row else f'🆔 <code>{row[0].application_id}</code>\n🏦 {row[1].name}\n📌 {row[0].status.replace("_"," ").title()}')

@router.callback_query(F.data=='how')
async def how(c:CallbackQuery): await c.message.answer('1. Select wallet\n2. Submit required documents\n3. Pay initial amount\n4. Submit UTR and receipt\n5. Receive Application ID'); await c.answer()
@router.callback_query(F.data=='support')
async def support(c:CallbackQuery): await c.message.answer('Use the WhatsApp contact button after submitting an application. Never share OTP, UPI PIN or passwords.'); await c.answer()
@router.callback_query(F.data=='home')
async def home(c:CallbackQuery,state:FSMContext): await state.clear(); await c.message.answer('Main Menu',reply_markup=menu()); await c.answer()

def create_dispatcher():
    dp=Dispatcher(); dp.include_router(router); return dp
