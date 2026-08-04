from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def now() -> datetime:
    return datetime.now()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(30), default="worker")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class OrderLine(Base):
    __tablename__ = "order_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    product_name: Mapped[str] = mapped_column(String(160), index=True)
    style_name: Mapped[str] = mapped_column(String(160), index=True)
    size: Mapped[str] = mapped_column(String(80), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    order_date: Mapped[str] = mapped_column(String(30), default="")
    delivery_date: Mapped[str] = mapped_column(String(80), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    batch: Mapped[str] = mapped_column(String(160), default="")
    sku: Mapped[str] = mapped_column(String(255), default="", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    company: Mapped[Company] = relationship()


class SkuMapping(Base):
    __tablename__ = "sku_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_name: Mapped[str] = mapped_column(String(120), index=True)
    product_name: Mapped[str] = mapped_column(String(160), index=True)
    style_name: Mapped[str] = mapped_column(String(160), index=True)
    size: Mapped[str] = mapped_column(String(80), index=True)
    sku: Mapped[str] = mapped_column(String(255), default="")
    barcode: Mapped[str] = mapped_column(String(255), default="", index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ProductAlias(Base):
    __tablename__ = "product_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_name: Mapped[str] = mapped_column(String(120), index=True)
    alias_product: Mapped[str] = mapped_column(String(160), index=True)
    alias_style: Mapped[str] = mapped_column(String(160), index=True)
    canonical_product: Mapped[str] = mapped_column(String(160), index=True)
    canonical_style: Mapped[str] = mapped_column(String(160), index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ShipmentReport(Base):
    __tablename__ = "shipment_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    ship_date: Mapped[str] = mapped_column(String(30), index=True)
    company_name: Mapped[str] = mapped_column(String(120), index=True)
    product_name: Mapped[str] = mapped_column(String(160), index=True)
    style_name: Mapped[str] = mapped_column(String(160), index=True)
    waybill_no: Mapped[str] = mapped_column(String(80), default="", index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="pending_review", index=True)
    review_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)

    user: Mapped[User] = relationship()
    lines: Mapped[list["ShipmentLine"]] = relationship(cascade="all, delete-orphan")
    photos: Mapped[list["ShipmentPhoto"]] = relationship(cascade="all, delete-orphan")


class ShipmentLine(Base):
    __tablename__ = "shipment_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("shipment_reports.id"))
    order_line_id: Mapped[int | None] = mapped_column(ForeignKey("order_lines.id"), nullable=True, index=True)
    size: Mapped[str] = mapped_column(String(80), index=True)
    quantity: Mapped[int] = mapped_column(Integer)

    order_line: Mapped[OrderLine | None] = relationship()


class ShipmentPhoto(Base):
    __tablename__ = "shipment_photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("shipment_reports.id"))
    draft_id: Mapped[int | None] = mapped_column(ForeignKey("packing_drafts.id"), nullable=True, index=True)
    file_path: Mapped[str] = mapped_column(String(500))
    original_name: Mapped[str] = mapped_column(String(255), default="")


class WaybillPhoto(Base):
    __tablename__ = "waybill_photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_name: Mapped[str] = mapped_column(String(120), index=True)
    stored_path: Mapped[str] = mapped_column(String(500))
    original_name: Mapped[str] = mapped_column(String(255), default="")
    waybill_date: Mapped[str] = mapped_column(String(30), default="", index=True)
    source_path: Mapped[str] = mapped_column(String(500), default="", index=True)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)

    uploader: Mapped[User | None] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("shipment_reports.id"))
    admin_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(60))
    before_text: Mapped[str] = mapped_column(Text, default="")
    after_text: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class OperationLog(Base):
    __tablename__ = "operation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    target: Mapped[str] = mapped_column(String(255), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)

    actor: Mapped[User | None] = relationship()


class DailyGoal(Base):
    __tablename__ = "daily_goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    goal_date: Mapped[str] = mapped_column(String(30), index=True)
    content: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    updater: Mapped[User | None] = relationship()


class PackingDraft(Base):
    __tablename__ = "packing_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    submitted_report_id: Mapped[int | None] = mapped_column(ForeignKey("shipment_reports.id"), nullable=True, index=True)
    pack_date: Mapped[str] = mapped_column(String(30), index=True)
    company_name: Mapped[str] = mapped_column(String(120), index=True)
    product_name: Mapped[str] = mapped_column(String(160), index=True)
    style_name: Mapped[str] = mapped_column(String(160), index=True)
    package_no: Mapped[str] = mapped_column(String(40), default="", index=True)
    waybill_no: Mapped[str] = mapped_column(String(80), default="", index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    user: Mapped[User] = relationship()
    lines: Mapped[list["PackingDraftLine"]] = relationship(cascade="all, delete-orphan")
    photos: Mapped[list["PackingDraftPhoto"]] = relationship(cascade="all, delete-orphan")


class PackingDraftLine(Base):
    __tablename__ = "packing_draft_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("packing_drafts.id"))
    order_line_id: Mapped[int | None] = mapped_column(ForeignKey("order_lines.id"), nullable=True, index=True)
    size: Mapped[str] = mapped_column(String(80), index=True)
    quantity: Mapped[int] = mapped_column(Integer)

    order_line: Mapped[OrderLine | None] = relationship()


class PackingDraftPhoto(Base):
    __tablename__ = "packing_draft_photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("packing_drafts.id"))
    file_path: Mapped[str] = mapped_column(String(500))
    original_name: Mapped[str] = mapped_column(String(255), default="")


class WorkInfoLine(Base):
    __tablename__ = "work_info_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_name: Mapped[str] = mapped_column(String(120), index=True)
    product_name: Mapped[str] = mapped_column(String(160), index=True)
    style_name: Mapped[str] = mapped_column(String(160), index=True)
    section_key: Mapped[str] = mapped_column(String(80), index=True)
    section_title: Mapped[str] = mapped_column(String(120))
    content: Mapped[str] = mapped_column(Text, default="")
    photo_path: Mapped[str] = mapped_column(String(500), default="")
    original_name: Mapped[str] = mapped_column(String(255), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    updater: Mapped[User | None] = relationship()


class WorkInfoProposal(Base):
    __tablename__ = "work_info_proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    company_name: Mapped[str] = mapped_column(String(120), index=True)
    product_name: Mapped[str] = mapped_column(String(160), index=True)
    style_name: Mapped[str] = mapped_column(String(160), index=True)
    payload: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="pending_review", index=True)
    review_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    user: Mapped[User] = relationship(foreign_keys=[user_id])
    reviewer: Mapped[User | None] = relationship(foreign_keys=[reviewed_by])


class OrderLedgerEntry(Base):
    """订单行流水：shipped/returned/adjusted/closed 各一条记录，由来源表重建。"""

    __tablename__ = "order_ledger_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_line_id: Mapped[int] = mapped_column(ForeignKey("order_lines.id"), index=True)
    movement_type: Mapped[str] = mapped_column(String(30), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text, default="")
    ref_report_id: Mapped[int | None] = mapped_column(ForeignKey("shipment_reports.id"), nullable=True)
    ref_return_id: Mapped[int | None] = mapped_column(ForeignKey("return_reworks.id"), nullable=True)
    ref_adjustment_id: Mapped[int | None] = mapped_column(ForeignKey("order_adjustments.id"), nullable=True)
    ref_close_id: Mapped[int | None] = mapped_column(ForeignKey("order_line_closes.id"), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)

    order_line: Mapped[OrderLine | None] = relationship()
    creator: Mapped[User | None] = relationship()


class ReturnRework(Base):
    __tablename__ = "return_reworks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_line_id: Mapped[int] = mapped_column(ForeignKey("order_lines.id"), index=True)
    report_id: Mapped[int | None] = mapped_column(ForeignKey("shipment_reports.id"), nullable=True, index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    reason_type: Mapped[str] = mapped_column(String(80), default="退回返工")
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="pending_rework", index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    order_line: Mapped[OrderLine | None] = relationship()
    report: Mapped[ShipmentReport | None] = relationship()
    creator: Mapped[User | None] = relationship()
    photos: Mapped[list["ReturnReworkPhoto"]] = relationship(cascade="all, delete-orphan")


class ReturnReworkPhoto(Base):
    __tablename__ = "return_rework_photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    return_id: Mapped[int] = mapped_column(ForeignKey("return_reworks.id"), index=True)
    file_path: Mapped[str] = mapped_column(String(500))
    original_name: Mapped[str] = mapped_column(String(255), default="")


class OrderAdjustment(Base):
    """盘点/调整：少发核销、报废、盘亏等，扣减待发量。"""

    __tablename__ = "order_adjustments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_line_id: Mapped[int] = mapped_column(ForeignKey("order_lines.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)

    order_line: Mapped[OrderLine | None] = relationship()
    creator: Mapped[User | None] = relationship()


class OrderLineClose(Base):
    """订单行关闭：客户不再要的余量，保留原订单与发货历史。"""

    __tablename__ = "order_line_closes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_line_id: Mapped[int] = mapped_column(ForeignKey("order_lines.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)

    order_line: Mapped[OrderLine | None] = relationship()
    creator: Mapped[User | None] = relationship()


class OrderLineComment(Base):
    __tablename__ = "order_line_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_line_id: Mapped[int] = mapped_column(ForeignKey("order_lines.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)

    order_line: Mapped[OrderLine | None] = relationship()
    user: Mapped[User | None] = relationship()
