from contextlib import contextmanager
from typing import Optional
import streamlit as st
from sqlalchemy import delete
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from models import Giant, GiantPayment, Movement, Bucket

@contextmanager
def tx(db: Session):
    try:
        yield
        db.commit()
    except Exception:
        db.rollback()
        raise

def init_db_pragmas(engine: Engine):
    """SQLite pragmas para performance e integridade."""
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
            conn.exec_driver_sql("PRAGMA synchronous=NORMAL;")
            conn.exec_driver_sql("PRAGMA foreign_keys=ON;")
    except Exception:
        pass

def delete_giant_safe(db: Session, user_id: int, giant_id: int) -> bool:
    """Exclui gigante + pagamentos; sem warnings '0 rows matched'."""
    stmt_pay = delete(GiantPayment).where(GiantPayment.giant_id == giant_id)
    stmt_g   = delete(Giant).where(Giant.id == giant_id, Giant.user_id == user_id)
    try:
        with db.begin():
            db.execute(stmt_pay)
            res = db.execute(stmt_g)
        if res.rowcount == 0:
            st.info("Nada foi excluído (já não existia).")
            return False
        st.toast("🗑️ Excluído!")
        return True
    except Exception as e:
        st.error(f"Erro ao excluir: {e}")
        return False

def distribute_by_buckets(db: Session, user_id: int, buckets: list, valor: float,
                          tipo: str, data_mov, desc: str, auto: bool = True,
                          bucket_id: Optional[int] = None) -> bool:
    """Divide entrada/saída por percentuais ou aplica em um balde específico."""
    if valor <= 0:
        st.error("Informe um valor maior que zero.")
        return False

    if auto or not bucket_id:
        total_percent = sum(max(b.percent, 0) for b in buckets)
        if total_percent <= 0:
            st.error("Configure percentuais dos baldes.")
            return False
        for b in buckets:
            part = round(valor * (b.percent / total_percent), 2)
            db.add(Movement(
                user_id=user_id, bucket_id=b.id,
                kind=("Receita" if tipo == "Entrada" else "Despesa"),
                amount=part, description=f"{desc} (auto {b.percent:.1f}%)",
                date=data_mov
            ))
            if tipo == "Entrada": b.balance += part
            else: b.balance -= part
    else:
        b = next((x for x in buckets if x.id == bucket_id), None)
        if not b:
            st.error("Balde inválido.")
            return False
        db.add(Movement(
            user_id=user_id, bucket_id=b.id,
            kind=("Receita" if tipo == "Entrada" else "Despesa"),
            amount=valor, description=desc, date=data_mov
        ))
        if tipo == "Entrada": b.balance += valor
        else: b.balance -= valor
    return True

def giant_forecast_simple(giant: Giant, db: Session):
    """Retorna (restante, diária, dias) baseado em weekly_goal."""
    pago = sum(p.amount for p in db.query(GiantPayment).filter_by(giant_id=giant.id))
    restante = max((giant.total_to_pay or 0.0) - pago, 0.0)
    diaria   = (giant.weekly_goal or 0.0) / 7.0
    dias     = (restante / diaria) if diaria > 0 else None
    return restante, diaria, dias
