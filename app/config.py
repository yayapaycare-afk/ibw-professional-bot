from dataclasses import dataclass
import os
from dotenv import load_dotenv

load_dotenv()


def normalize_db(url: str) -> str:
    if url.startswith('postgres://'):
        return url.replace('postgres://', 'postgresql+asyncpg://', 1)
    if url.startswith('postgresql://'):
        return url.replace('postgresql://', 'postgresql+asyncpg://', 1)
    return url


@dataclass(frozen=True)
class Settings:
    bot_token: str
    database_url: str
    admin_username: str
    admin_password: str
    session_secret: str
    public_base_url: str
    whatsapp_number: str
    official_channel: str
    business_name: str
    storage_dir: str


def get_settings() -> Settings:
    return Settings(
        bot_token=os.getenv('BOT_TOKEN', '').strip(),
        database_url=normalize_db(os.getenv('DATABASE_URL', 'sqlite+aiosqlite:///./ibw.db')),
        admin_username=os.getenv('ADMIN_USERNAME', 'admin'),
        admin_password=os.getenv('ADMIN_PASSWORD', 'change-me'),
        session_secret=os.getenv('SESSION_SECRET', 'change-this-secret'),
        public_base_url=os.getenv('PUBLIC_BASE_URL', 'http://localhost:8000').rstrip('/'),
        whatsapp_number=''.join(ch for ch in os.getenv('WHATSAPP_NUMBER', '') if ch.isdigit()),
        official_channel=os.getenv('OFFICIAL_CHANNEL', '').strip(),
        business_name=os.getenv('BUSINESS_NAME', 'India Business Wallets'),
        storage_dir=os.getenv('STORAGE_DIR', 'storage'),
    )
