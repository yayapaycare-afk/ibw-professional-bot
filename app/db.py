from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select
from app.config import get_settings
from app.models import Base, Wallet, DocumentRule

settings = get_settings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with Session() as s:
        if not (await s.scalar(select(Wallet.id).limit(1))):
            w = Wallet(name='Google Pay Business', description='Business wallet onboarding assistance.', total_fee=1500, initial_percent=70, sort_order=1)
            s.add(w); await s.flush()
            s.add_all([
                DocumentRule(wallet_id=w.id, name='Mobile Number', manual_label='Enter Mobile Number', manual_kind='single', upload_allowed=False, manual_allowed=True, sort_order=0),
                DocumentRule(wallet_id=w.id, name='Aadhaar Card', manual_label='Enter Aadhaar Number', manual_kind='single', sort_order=1),
                DocumentRule(wallet_id=w.id, name='PAN Card', manual_label='Enter PAN Number', manual_kind='single', sort_order=2),
                DocumentRule(wallet_id=w.id, name='Bank Details', manual_label='Enter Account Number and IFSC', manual_kind='bank', sort_order=3),
            ])
            await s.commit()
