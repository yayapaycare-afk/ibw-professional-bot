import os, uuid
from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import select, func
from app.config import get_settings
from app.db import Session
from app.models import Wallet, DocumentRule, Application, Submission, User

settings=get_settings(); templates=Jinja2Templates(directory='app/templates')

def auth(request:Request): return request.session.get('admin') is True

def build_admin_app():
    app=FastAPI(title='IBW Admin'); app.add_middleware(SessionMiddleware,secret_key=settings.session_secret,https_only=False)
    @app.get('/login',response_class=HTMLResponse)
    async def login_page(request:Request): return templates.TemplateResponse('login.html',{'request':request,'error':None})
    @app.post('/login')
    async def login(request:Request,username:str=Form(...),password:str=Form(...)):
        if username==settings.admin_username and password==settings.admin_password:
            request.session['admin']=True; return RedirectResponse('/admin',303)
        return templates.TemplateResponse('login.html',{'request':request,'error':'Invalid username or password'},status_code=401)
    @app.get('/logout')
    async def logout(request:Request): request.session.clear(); return RedirectResponse('/login',303)
    @app.get('/admin',response_class=HTMLResponse)
    async def dashboard(request:Request):
        if not auth(request): return RedirectResponse('/login',303)
        async with Session() as s:
            counts={'applications':await s.scalar(select(func.count(Application.id))) or 0,'pending':await s.scalar(select(func.count(Application.id)).where(Application.status=='PAYMENT_UNDER_VERIFICATION')) or 0,'wallets':await s.scalar(select(func.count(Wallet.id))) or 0}
            apps=(await s.execute(select(Application,Wallet,User).join(Wallet,Wallet.id==Application.wallet_id).join(User,User.telegram_id==Application.user_id).order_by(Application.id.desc()).limit(20))).all()
        return templates.TemplateResponse('dashboard.html',{'request':request,'counts':counts,'apps':apps})
    @app.get('/admin/wallets',response_class=HTMLResponse)
    async def wallets(request:Request):
        if not auth(request): return RedirectResponse('/login',303)
        async with Session() as s: rows=(await s.scalars(select(Wallet).order_by(Wallet.sort_order,Wallet.id))).all()
        return templates.TemplateResponse('wallets.html',{'request':request,'wallets':rows})
    @app.post('/admin/wallets/add')
    async def add_wallet(request:Request,name:str=Form(...),total_fee:int=Form(...),initial_percent:int=Form(...)):
        if not auth(request): raise HTTPException(403)
        async with Session() as s: s.add(Wallet(name=name,total_fee=total_fee,initial_percent=initial_percent)); await s.commit()
        return RedirectResponse('/admin/wallets',303)
    @app.get('/admin/wallet/{wid}',response_class=HTMLResponse)
    async def wallet_edit(request:Request,wid:int):
        if not auth(request): return RedirectResponse('/login',303)
        async with Session() as s:
            w=await s.get(Wallet,wid); docs=(await s.scalars(select(DocumentRule).where(DocumentRule.wallet_id==wid).order_by(DocumentRule.sort_order))).all()
        return templates.TemplateResponse('wallet_edit.html',{'request':request,'w':w,'docs':docs})
    @app.post('/admin/wallet/{wid}/save')
    async def wallet_save(request:Request,wid:int,name:str=Form(...),description:str=Form(''),total_fee:int=Form(...),initial_percent:int=Form(...),processing_time:str=Form(''),upi_id:str=Form(''),active:bool=Form(False),qr:UploadFile|None=File(None)):
        if not auth(request): raise HTTPException(403)
        async with Session() as s:
            w=await s.get(Wallet,wid); w.name=name; w.description=description; w.total_fee=total_fee; w.initial_percent=initial_percent; w.processing_time=processing_time; w.upi_id=upi_id; w.active=active
            if qr and qr.filename:
                os.makedirs(settings.storage_dir,exist_ok=True); ext=os.path.splitext(qr.filename)[1]; path=os.path.join(settings.storage_dir,uuid.uuid4().hex+ext); open(path,'wb').write(await qr.read()); w.qr_file=path
            await s.commit()
        return RedirectResponse(f'/admin/wallet/{wid}',303)
    @app.post('/admin/wallet/{wid}/document/add')
    async def doc_add(request:Request,wid:int,name:str=Form(...),manual_label:str=Form(...),manual_kind:str=Form('single'),upload_allowed:bool=Form(False),manual_allowed:bool=Form(False)):
        if not auth(request): raise HTTPException(403)
        async with Session() as s:
            maxo=await s.scalar(select(func.max(DocumentRule.sort_order)).where(DocumentRule.wallet_id==wid)) or 0
            s.add(DocumentRule(wallet_id=wid,name=name,manual_label=manual_label,manual_kind=manual_kind,upload_allowed=upload_allowed,manual_allowed=manual_allowed,sort_order=maxo+1)); await s.commit()
        return RedirectResponse(f'/admin/wallet/{wid}',303)
    @app.post('/admin/document/{did}/delete')
    async def doc_delete(request:Request,did:int):
        if not auth(request): raise HTTPException(403)
        async with Session() as s:
            d=await s.get(DocumentRule,did); wid=d.wallet_id; await s.delete(d); await s.commit()
        return RedirectResponse(f'/admin/wallet/{wid}',303)
    @app.get('/admin/application/{aid}',response_class=HTMLResponse)
    async def app_detail(request:Request,aid:int):
        if not auth(request): return RedirectResponse('/login',303)
        async with Session() as s:
            a=await s.get(Application,aid); w=await s.get(Wallet,a.wallet_id); u=await s.get(User,a.user_id)
            subs=(await s.execute(select(Submission,DocumentRule).join(DocumentRule,DocumentRule.id==Submission.document_rule_id).where(Submission.application_id==aid).order_by(DocumentRule.sort_order))).all()
        return templates.TemplateResponse('application.html',{'request':request,'a':a,'w':w,'u':u,'subs':subs})
    @app.post('/admin/application/{aid}/status')
    async def status(request:Request,aid:int,status:str=Form(...)):
        if not auth(request): raise HTTPException(403)
        async with Session() as s: a=await s.get(Application,aid); a.status=status; await s.commit()
        return RedirectResponse(f'/admin/application/{aid}',303)
    @app.get('/admin/file/{sid}')
    async def private_file(request:Request,sid:int):
        if not auth(request): raise HTTPException(403)
        async with Session() as s: sub=await s.get(Submission,sid)
        if not sub or not sub.file_path or not os.path.exists(sub.file_path): raise HTTPException(404)
        return FileResponse(sub.file_path)
    @app.get('/admin/receipt/{aid}')
    async def receipt(request:Request,aid:int):
        if not auth(request): raise HTTPException(403)
        async with Session() as s: a=await s.get(Application,aid)
        if not a or not a.receipt_file or not os.path.exists(a.receipt_file): raise HTTPException(404)
        return FileResponse(a.receipt_file)
    return app
