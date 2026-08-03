from datetime import datetime, timezone
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'
    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(150))
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Wallet(Base):
    __tablename__ = 'wallets'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(Text, default='')
    total_fee: Mapped[int] = mapped_column(Integer, default=0)
    initial_percent: Mapped[int] = mapped_column(Integer, default=50)
    processing_time: Mapped[str] = mapped_column(String(100), default='Subject to verification')
    upi_id: Mapped[str] = mapped_column(String(150), default='')
    qr_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    documents: Mapped[list['DocumentRule']] = relationship(back_populates='wallet', cascade='all, delete-orphan')


class DocumentRule(Base):
    __tablename__ = 'document_rules'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey('wallets.id', ondelete='CASCADE'))
    name: Mapped[str] = mapped_column(String(120))
    manual_label: Mapped[str] = mapped_column(String(150), default='Enter details manually')
    manual_kind: Mapped[str] = mapped_column(String(30), default='single') # single|bank|none
    upload_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    manual_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    wallet: Mapped[Wallet] = relationship(back_populates='documents')


class Application(Base):
    __tablename__ = 'applications'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[str | None] = mapped_column(String(30), unique=True, nullable=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.telegram_id'))
    wallet_id: Mapped[int] = mapped_column(ForeignKey('wallets.id'))
    status: Mapped[str] = mapped_column(String(50), default='DRAFT')
    amount_due: Mapped[int] = mapped_column(Integer, default=0)
    utr: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)
    receipt_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Submission(Base):
    __tablename__ = 'submissions'
    __table_args__ = (UniqueConstraint('application_id', 'document_rule_id'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey('applications.id', ondelete='CASCADE'))
    document_rule_id: Mapped[int] = mapped_column(ForeignKey('document_rules.id', ondelete='CASCADE'))
    method: Mapped[str] = mapped_column(String(20)) # manual|upload
    manual_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
