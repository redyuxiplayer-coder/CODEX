import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Event

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Company, OperationLog, OrderLine, Spu
from app.services.sales_orders import (
    StaleUnitPriceError,
    create_sales_order,
    update_order_line_unit_price,
)


def test_stale_sqlite_reader_cannot_overwrite_committed_price(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'price-race.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as seed:
        company = Company(name="并发公司", code="RACE", next_order_sequence=1)
        spu = Spu(code="SKU", product_name="产品", style_name="款式")
        seed.add_all([company, spu])
        seed.commit()
        order = create_sales_order(
            seed, company.id, spu.id, "", "", "2026-09-24",
            [{"size": "S", "quantity": 1}],
        )
        order_id, line_id = order.id, order.lines[0].id

    a_read = Event()
    b_committed = Event()
    seen_by_a = []

    def writer_a():
        with Session() as session:
            def pause_after_read(current_session, instance):
                if isinstance(instance, OrderLine) and instance.id == line_id:
                    seen_by_a.append((instance.unit_price, instance.price_revision))
                    a_read.set()
                    assert b_committed.wait(timeout=10)

            event.listen(session, "loaded_as_persistent", pause_after_read)
            try:
                line, _before = update_order_line_unit_price(
                    session, order_id, line_id, "20.00", None, 0,
                )
                session.add(OperationLog(
                    action="order_line_unit_price_update",
                    detail=json.dumps({"after": str(line.unit_price)}),
                ))
                session.commit()
                return "overwrote"
            except StaleUnitPriceError:
                session.rollback()
                return "stale"

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future_a = executor.submit(writer_a)
            assert a_read.wait(timeout=10)
            with Session() as session_b:
                line, _before = update_order_line_unit_price(
                    session_b, order_id, line_id, "15.00", None, 0,
                )
                session_b.add(OperationLog(
                    action="order_line_unit_price_update",
                    detail=json.dumps({"after": str(line.unit_price)}),
                ))
                session_b.commit()
            b_committed.set()
            result_a = future_a.result(timeout=10)

        with Session() as verify:
            line = verify.get(OrderLine, line_id)
            audits = verify.query(OperationLog).filter_by(action="order_line_unit_price_update").all()
            assert seen_by_a == [(None, 0)]
            assert result_a == "stale"
            assert line.unit_price == Decimal("15.00")
            assert line.price_revision == 1
            assert [json.loads(audit.detail) for audit in audits] == [{"after": "15.00"}]
    finally:
        b_committed.set()
        engine.dispose()
