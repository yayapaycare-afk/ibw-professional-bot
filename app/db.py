from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select, text, inspect
from app.config import get_settings
from app.models import Base, Wallet, DocumentRule, SystemSetting

settings = get_settings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

DEFAULT_SETTINGS = {
    "working_hours": "10:00 AM – 9:30 PM",
    "service_available": "true",
    "final_upi_id": "",
    "final_banking_name": "",
    "final_qr_file": "",
}


async def setting_value(key: str, default: str = "") -> str:
    async with Session() as session:
        row = await session.get(SystemSetting, key)
        return row.value if row else default


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Lightweight migration for existing V2 databases.
        def migrate(sync_conn):
            columns = {c["name"] for c in inspect(sync_conn).get_columns("wallets")}
            if "banking_name" not in columns:
                sync_conn.execute(text("ALTER TABLE wallets ADD COLUMN banking_name VARCHAR(150) DEFAULT ''"))
        await conn.run_sync(migrate)

    async with Session() as session:
        for key, value in DEFAULT_SETTINGS.items():
            if not await session.get(SystemSetting, key):
                session.add(SystemSetting(key=key, value=value))

        if not (await session.scalar(select(Wallet.id).limit(1))):
            wallet = Wallet(
                name="Google Pay Business",
                description="Business wallet onboarding assistance.",
                total_fee=1500,
                initial_percent=70,
                processing_time="10–15 working days",
                sort_order=1,
            )
            session.add(wallet)
            await session.flush()
            session.add_all([
                DocumentRule(wallet_id=wallet.id, name="Mobile Number", manual_label="Enter Mobile Number", manual_kind="mobile", upload_allowed=False, manual_allowed=True, sort_order=0),
                DocumentRule(wallet_id=wallet.id, name="Aadhaar Card", manual_label="Enter Aadhaar Number", manual_kind="aadhaar", upload_allowed=True, manual_allowed=True, sort_order=1),
                DocumentRule(wallet_id=wallet.id, name="PAN Card", manual_label="Enter PAN Number", manual_kind="pan", upload_allowed=True, manual_allowed=True, sort_order=2),
                DocumentRule(wallet_id=wallet.id, name="Bank Details", manual_label="Enter Account Number and IFSC", manual_kind="bank", upload_allowed=True, manual_allowed=True, sort_order=3),
            ])
        await session.commit()
