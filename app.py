
from typing import Optional
import re
from babel.numbers import format_currency

def _to_float_br(texto: str) -> float:
    if texto is None:
        return 0.0
    s = str(texto).strip()
    s = re.sub(r"[^0-9,\.]", "", s)
    if s == "":
        return 0.0
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0

def currency_input(label: str, key: str, default: float = 0.0, help: Optional[str] = None) -> float:
    if key not in st.session_state:
        st.session_state[key] = default
    valor_atual = st.session_state.get(key, default)
    texto_inicial = format_currency(float(valor_atual), 'BRL', locale='pt_BR')
    txt = st.text_input(label, value=texto_inicial, key=f"{key}__txt", help=help)
    valor_float = _to_float_br(txt)
    st.session_state[key] = valor_float
    st.caption(f"Valor: {format_currency(valor_float, 'BRL', locale='pt_BR')}")
    return valor_float

def persisted_number_input(label: str, key: str, default: float = 0.0, **kwargs) -> float:
    if key not in st.session_state:
        st.session_state[key] = default
    val = st.number_input(label, key=key, value=st.session_state[key], **kwargs)
    # Não modificar st.session_state[key] após a criação do widget para evitar StreamlitAPIException
    return val
# ======================================
# app.py — DAVI (Streamlit, organizado)
# ======================================

import os
from typing import Optional
import time
from datetime import date, timedelta, datetime
from contextlib import contextmanager

import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt

from sqlalchemy import create_engine, select, delete
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool

from models import (
    Base, User, UserProfile, Bucket, Giant, Movement, Bill, GiantPayment
)
from db_helpers import (
    init_db_pragmas, delete_giant_safe, distribute_by_buckets,
    giant_forecast_simple
)
from utils import (
    money_br, dias_do_mes
)

# -----------------------------
# Configuração de página
# -----------------------------
st.set_page_config(
    page_title="DAVI",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={'About': 'DAVI — Controle Financeiro Inteligente'}
)

# -----------------------------
# CSS mobile-first (estilo limpo)
# -----------------------------
def load_css():
    p = "styles.css"
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

st.markdown("""
<style>
.block-container{padding-top:.6rem;padding-bottom:.6rem;}
[data-testid="stDecoration"],#MainMenu,footer{display:none!important;}
.stTextInput input,.stNumberInput input,.stDateInput input{height:44px;font-size:16px;border-radius:10px;}
.stButton button{min-height:44px;border-radius:10px;font-weight:600;}
[data-testid="stDataFrame"] div[role="table"]{overflow-x:auto;}
</style>
""", unsafe_allow_html=True)
load_css()

# -----------------------------
# Engine / Session (SQLite)
# -----------------------------
DB_URL = os.getenv("DATABASE_URL", "sqlite:///sql_app.db")
engine = create_engine(
    DB_URL,
    poolclass=QueuePool,
    pool_size=10,
    max_overflow=20,
    connect_args={'check_same_thread': False} if DB_URL.startswith("sqlite") else {},
    pool_timeout=30,
    pool_recycle=1800,
    pool_pre_ping=True,
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False, future=True)

@contextmanager
def get_db() -> Session:
    """Sessão com commit/rollback automático e limpeza garantida."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        st.error(f"Erro de banco de dados: {e}")
        raise
    finally:
        session.close()

# Cria tabelas e pragmas na primeira carga

Base.metadata.create_all(bind=engine)
init_db_pragmas(engine)

# =====================
# Autenticação minimal
# =====================
def hash_password(plain: str) -> str:
    import hashlib
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()

# --- Seed seguro (não altera estrutura, só cria um usuário se não existir) ---
def _ensure_default_user():
    with get_db() as db:
        exists = db.query(User).first()
        if not exists:
            import hashlib
            demo = User(
                name="demo",
                password_hash=hash_password("1234")
            )
            db.add(demo)
            db.commit()
            st.info("Usuário padrão criado: usuário **demo** / senha **1234**")

_ensure_default_user()

# -----------------------------
# Matplotlib (tema leve)
# -----------------------------
plt.style.use('default')
plt.rcParams.update({
    'figure.facecolor': '#FFFFFF',
    'axes.facecolor':   '#FFFFFF',
    'axes.grid': True,
    'grid.alpha': 0.30,
    'grid.color': '#E5E7EB',
    'axes.labelcolor': '#111827',
    'xtick.color': '#6B7280',
    'ytick.color': '#6B7280',
    'figure.autolayout': True,
    'font.size': 10
})

def date_br(dt):
    if isinstance(dt, str):
        try:
            dt = pd.to_datetime(dt)
        except Exception:
            return dt
    if isinstance(dt, (pd.Timestamp, date, datetime)):
        return dt.strftime('%d/%m/%y')
    return str(dt)
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()

def auth_user(db: Session, username: str, password: str):

    u = db.query(User).filter(User.name == username).first()
    if u and u.password_hash == hash_password(password):
        return u
    return None

def user_exists(db: Session, username: str) -> bool:
    return db.query(User).filter(User.name == username).first() is not None

def create_user(db: Session, username: str, password: str) -> Optional[User]:
    uname = (username or "").strip()
    pwd   = (password or "").strip()
    if len(uname) < 3:
        st.error("O usuário deve ter pelo menos 3 caracteres.")
        return None
    if len(pwd) < 4:
        st.error("A senha deve ter pelo menos 4 caracteres.")
        return None
    if user_exists(db, uname):
        st.error("Este usuário já existe. Tente outro nome.")
        return None
    u = User(name=uname, password_hash=hash_password(pwd))
    db.add(u); db.commit(); db.refresh(u)
    return u

def init_auth():
    # Mantém usuário logado após atualização da tela
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False
    if "user" not in st.session_state:
        st.session_state["user"] = None
    # Se houver usuário salvo, restaura autenticação
    if st.session_state.get("saved_user") is not None:
        st.session_state["authenticated"] = True
        st.session_state["user"] = st.session_state["saved_user"]

def logout():
    for k in ("authenticated", "user", "saved_user"):
        st.session_state.pop(k, None)
    st.rerun()

def show_login():
    st.markdown("<h1 style='text-align:center'>DAVI</h1><p style='text-align:center;color:#10B981'>Vença seus gigantes financeiros</p>", unsafe_allow_html=True)
    tab1, tab2 = st.tabs(["Login", "Cadastro"])
    with tab1:
        with st.form("login"):
            user = st.text_input("Usuário", key="login_user")
            pwd = st.text_input("Senha", type="password", key="login_pwd")
            keep = st.checkbox("Manter conectado", key="login_keep")
            ok = st.form_submit_button("Entrar", use_container_width=True)
        if ok:
            if not user.strip() or not pwd:
                st.error("Preencha usuário e senha.")
                return
            with get_db() as db:
                u = auth_user(db, user.strip(), pwd)
            if u:
                st.session_state.authenticated = True
                st.session_state.user = u
                if keep:
                    st.session_state.saved_user = u
                st.rerun()
            else:
                st.error("Usuário ou senha inválidos.")
    with tab2:
        with st.form("cadastro"):
            new_user = st.text_input("Novo usuário", key="cadastro_user")
            new_pwd = st.text_input("Nova senha", type="password", key="cadastro_pwd")
            ok2 = st.form_submit_button("Cadastrar", use_container_width=True)
        if ok2:
            if not new_user.strip() or not new_pwd:
                st.error("Preencha usuário e senha.")
                return
            with get_db() as db:
                u = create_user(db, new_user.strip(), new_pwd)
            if u:
                st.success("Usuário cadastrado com sucesso!")
                st.session_state.authenticated = True
                st.session_state.user = u
                st.session_state.saved_user = u
                st.rerun()

# =====================
# Cache de leitura
# =====================
@st.cache_data(ttl=300)
def load_profile(uid: int):
    with get_db() as db:
        prof = db.execute(select(UserProfile).where(UserProfile.user_id == uid)).scalar_one_or_none()
        if not prof:
            prof = UserProfile(user_id=uid, monthly_income=0.0, monthly_expense=0.0)
            db.add(prof); db.commit(); db.refresh(prof)
        return prof

@st.cache_data(ttl=120)
def load_buckets(uid: int):
    with get_db() as db:
        return db.query(Bucket).filter(Bucket.user_id == uid).all()

@st.cache_data(ttl=120)
def load_giants(uid: int):
    with get_db() as db:
        return db.query(Giant).filter(Giant.user_id == uid).all()

@st.cache_data(ttl=120)
def load_bills(uid: int):
    with get_db() as db:
        return db.query(Bill).filter(Bill.user_id == uid).order_by(Bill.due_date.asc()).all()

@st.cache_data(ttl=120)
def load_movements(uid: int, limit: int = 300):
    with get_db() as db:
        return db.query(Movement).filter(Movement.user_id == uid).order_by(Movement.date.desc()).limit(limit).all()

# =====================
# Páginas
# =====================
def page_dashboard(user: User):
    st.markdown("## 📊 Visão Geral")
    movs = load_movements(user.id, 500)

    total_in  = sum(m.amount for m in movs if m.kind == "Receita")
    total_out = sum(m.amount for m in movs if m.kind == "Despesa")
    saldo     = total_in - total_out

    c1, c2, c3 = st.columns(3)
    c1.metric("Receitas",  money_br(total_in))
    c2.metric("Despesas",  money_br(total_out))
    # Adiciona ícone de lápis para editar e salvar o saldo total no Dashboard
    if "edit_saldo_total" not in st.session_state:
        st.session_state["edit_saldo_total"] = False
    if st.session_state["edit_saldo_total"]:
        saldo_edit = currency_input("Saldo Total (Receitas - Despesas)", key="dashboard_saldo_total", default=saldo)
        b1, b2 = c3.columns([2,2])
        with b1:
            if st.button("💾 Salvar", key="dashboard_save_saldo_total"):
                st.session_state["edit_saldo_total"] = False
                st.session_state["dashboard_saldo_total"] = saldo_edit
                st.success("Saldo total atualizado para esta sessão.")
        with b2:
            if st.button("❌ Cancelar", key="dashboard_cancel_saldo_total"):
                st.session_state["edit_saldo_total"] = False
    else:
        saldo_edit = st.session_state.get("dashboard_saldo_total", saldo)
        c3.metric("Saldo", money_br(saldo_edit))
        if c3.button("✏️ Editar saldo", key="dashboard_edit_saldo_total"):
            st.session_state["edit_saldo_total"] = True

    if movs:
        df = pd.DataFrame([{
            "Data": date_br(m.date), "Tipo": m.kind,
            "Valor": m.amount if m.kind == "Receita" else -m.amount,
            "Descrição": m.description
        } for m in movs]).sort_values("Data")

        st.subheader("📈 Evolução")
        fig, ax = plt.subplots(figsize=(10,4))
        df_in  = df[df["Tipo"] == "Receita"]
        df_out = df[df["Tipo"] == "Despesa"]
        ax.plot(df_in["Data"],  df_in["Valor"],  color="green", marker="o", label="Receitas")
        ax.plot(df_out["Data"], -df_out["Valor"], color="red",   marker="o", label="Despesas")
        ax.legend(); ax.grid(True, alpha=.3)
        ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
        st.pyplot(fig)

        st.subheader("📝 Últimas Movimentações")
        df_tail = df.tail(12).sort_values("Data", ascending=False).copy()
        df_tail["Valor"] = df_tail["Valor"].apply(money_br)
        st.dataframe(df_tail, hide_index=True, use_container_width=True)
    else:
        st.info("Sem movimentações ainda.")

def page_plano_ataque(user: User):
    st.markdown("## 🎯 Plano de Ataque")
    giants = load_giants(user.id)

    rows = []
    with get_db() as db:
        for g in giants:
            total_pago = sum(p.amount for p in db.query(GiantPayment).filter_by(giant_id=g.id).all())
            restante   = max((g.total_to_pay or 0.0) - total_pago, 0.0)
            rows.append({"ID": g.id, "Nome": g.name, "Total": g.total_to_pay or 0.0, "Pago": total_pago, "Restante": restante})

    df = pd.DataFrame(rows)
    if not df.empty:
        df_fmt = df.copy()
        df_fmt["Total"]    = df_fmt["Total"].apply(money_br)
        df_fmt["Pago"]     = df_fmt["Pago"].apply(money_br)
        df_fmt["Restante"] = df_fmt["Restante"].apply(money_br)
        st.dataframe(df_fmt, hide_index=True, use_container_width=True)
    else:
        st.info("Nenhum gigante cadastrado.")

    st.caption("Ações")
    with get_db() as db:
        for _, r in df.iterrows():
            c1, c2, c3, c4, c5, c6 = st.columns([2,5,3,3,3,2])
            with c1: st.write(f"**#{int(r['ID'])}**")
            with c2: st.write(r["Nome"])
            with c3: st.write(money_br(r["Total"]))
            with c4: st.write(money_br(r["Pago"]))
            with c5: st.write(money_br(r["Restante"]))
            with c6:
                b1, b2 = st.columns(2)
                if b1.button("✏️", key=f"edit_{r['ID']}"):
                    st.session_state.edit_giant_id = int(r["ID"]); st.rerun()
                if b2.button("🗑️", key=f"del_{r['ID']}"):
                    ok = delete_giant_safe(db, user.id, int(r["ID"]))
                    st.cache_data.clear()
                    st.rerun()

    st.markdown("### ➕ Novo Gigante")
    with get_db() as db:
        with st.form("novo_giant", clear_on_submit=True):
            nome   = st.text_input("Nome do Gigante", key="novo_giant_nome")
            total  = currency_input("Total a Quitar", key="novo_giant_total", default=0.0)
            weekly = currency_input("Meta semanal (R$)", key="novo_giant_weekly", default=0.0)
            juros  = persisted_number_input("Juros a.m. (%)", key="novo_giant_juros", default=0.0, min_value=0.0, step=0.1, format="%.2f")
            ok     = st.form_submit_button("Criar")

        if ok:
            if not nome or total <= 0:
                st.error("Informe nome e valor > 0.")
            else:
                try:
                    g = Giant(user_id=user.id, name=nome, total_to_pay=total,
                              weekly_goal=weekly, interest_rate=juros,
                              status="active", priority=1, parcels=0, payoff_efficiency=0.0)
                    db.add(g); db.commit()
                    st.success("Gigante criado.")
                    st.cache_data.clear(); st.rerun()
                except Exception as e:
                    db.rollback(); st.error(f"Erro ao criar: {e}")

def page_baldes(user: User):
    st.markdown("## 🪣 Baldes")
    with get_db() as db:
        buckets = load_buckets(user.id)

        with st.form("novo_balde"):
            nome = st.text_input("Nome", key="novo_balde_nome")
            tipo = st.text_input("Tipo (giant/fixo/etc)", key="novo_balde_tipo")
            perc = persisted_number_input("Porcentagem (%)", key="novo_balde_perc", default=0.0, min_value=0.0, max_value=100.0, step=1.0, format="%.2f")
            ok = st.form_submit_button("Criar")
        if ok:
            if not nome:
                st.error("Informe o nome.")
            else:
                b = Bucket(user_id=user.id, name=nome, description="", percent=float(perc), type=(tipo or "generic").lower())
                db.add(b); db.commit()
                st.success("Balde criado.")
                st.cache_data.clear(); st.rerun()

        if buckets:
            st.markdown("### Baldes")
            for b in buckets:
                c1, c2, c3, c4, c5 = st.columns([2,6,3,2,2])
                with c1:
                    st.write(f"**#{b.id}**")
                with c2:
                    st.write(f"{b.name}")
                with c3:
                    st.write(f"{money_br(b.balance)}")
                with c4:
                    if st.button("✏️", key=f"edit_balde_{b.id}", help="Editar balde"):
                        st.session_state.edit_balde_id = b.id
                        st.session_state.edit_balde_nome = b.name
                        st.session_state.edit_balde_tipo = b.type
                        st.session_state.edit_balde_perc = b.percent
                        st.rerun()
                with c5:
                    if st.button("🗑️", key=f"del_balde_{b.id}", help="Excluir balde"):
                        try:
                            db.delete(b); db.commit()
                            st.success(f"Balde '{b.name}' excluído.")
                            st.cache_data.clear(); st.rerun()
                        except Exception as e:
                            db.rollback(); st.error(f"Erro ao excluir: {e}")

            # Formulário de edição de balde, incluindo saldo
            if st.session_state.get("edit_balde_id") is not None:
                st.markdown("### Editar Balde")
                with st.form("form_edit_balde"):
                    nome_edit = st.text_input("Nome", value=st.session_state.edit_balde_nome, key="edit_balde_nome")
                    tipo_edit = st.text_input("Tipo", value=st.session_state.edit_balde_tipo, key="edit_balde_tipo")
                    perc_edit = persisted_number_input("Porcentagem (%)", key="edit_balde_perc", default=float(st.session_state.edit_balde_perc), min_value=0.0, max_value=100.0, step=1.0, format="%.2f")
                    saldo_edit = currency_input("Saldo (R$)", key="edit_balde_saldo", default=float(db.query(Bucket).filter(Bucket.id == st.session_state.edit_balde_id).first().balance))
                    ok_edit = st.form_submit_button("Salvar alterações")
                    if ok_edit:
                        try:
                            balde = db.query(Bucket).filter(Bucket.id == st.session_state.edit_balde_id).first()
                            balde.name = nome_edit
                            balde.type = tipo_edit
                            balde.percent = float(perc_edit)
                            balde.balance = float(saldo_edit)
                            db.add(balde); db.commit()
                            st.success("Balde editado com sucesso.")
                            st.cache_data.clear()
                            for k in ["edit_balde_id", "edit_balde_nome", "edit_balde_tipo", "edit_balde_perc"]:
                                st.session_state.pop(k, None)
                            st.rerun()
                        except Exception as e:
                            db.rollback(); st.error(f"Erro ao editar: {e}")
        else:
            st.info("Nenhum balde cadastrado.")

def page_entradas(user: User):
    st.markdown("## 💰 Entradas e Saídas")
    with get_db() as db:
        buckets = load_buckets(user.id)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Registrar Entrada")
        with st.form("nova_entrada"):
            valor = currency_input("Valor da Entrada", key="entrada_valor", default=0.0)
            dt    = st.date_input("Data da Entrada", value=date.today(), key="entrada_data")
            ok    = st.form_submit_button("Registrar Entrada", use_container_width=True)
        if ok:
            if valor <= 0:
                st.error("Informe um valor maior que zero.")
            else:
                try:
                    with get_db() as db:
                        mov = Movement(user_id=user.id, kind="Receita", amount=float(valor), description="Entrada (rateada)", date=dt)
                        db.add(mov); db.commit(); db.refresh(mov)
                        buckets = load_buckets(user.id)
                        dist = distribute_by_buckets(db, user.id, buckets, float(valor), "Entrada", dt, "Entrada diária", auto=True)
                        # Atualiza saldo dos baldes após entrada
                        for b in buckets:
                            balde = db.query(Bucket).filter(Bucket.id == b.id).first()
                            balde.balance += b.percent/100*float(valor)
                            db.add(balde)
                        db.commit()
                        if not dist:
                            st.error("Falha ao dividir nos baldes.")
                            return
                    st.success("✅ Registrado e dividido nos baldes.")
                    # Mostrar quanto cada balde recebeu
                    st.markdown("### Distribuição nos Baldes")
                    df_dist = pd.DataFrame([{"Balde": b.name, "Recebeu": money_br(b.percent/100*valor)} for b in buckets])
                    st.dataframe(df_dist, hide_index=True, use_container_width=True)
                    st.toast("💸 Registrado!", icon="💸")
                    st.cache_data.clear(); st.stop()
                except Exception as e:
                    st.error(f"Falha ao registrar: {e}")

    with col2:
        st.subheader("Registrar Saída")
        buckets = load_buckets(user.id)
        with st.form("nova_saida"):
            valor_s = currency_input("Valor da Saída", key="saida_valor", default=0.0)
            dt_s    = st.date_input("Data da Saída", value=date.today(), key="saida_data")
            # Pergunta de qual balde saiu o valor
            balde_opcoes = {str(b.id): b.name for b in buckets} if buckets else {}
            balde_id = st.selectbox("De qual balde saiu o valor?", options=list(balde_opcoes.keys()), format_func=lambda x: balde_opcoes.get(x, ""), key="saida_balde_id") if balde_opcoes else None
            ok_s    = st.form_submit_button("Registrar Saída", use_container_width=True)
        if ok_s:
            if valor_s <= 0:
                st.error("Informe um valor maior que zero.")
            elif not balde_id:
                st.error("Selecione o balde de origem da saída.")
            else:
                try:
                    with get_db() as db:
                        mov = Movement(user_id=user.id, kind="Despesa", amount=float(valor_s), description=f"Saída ({balde_opcoes.get(balde_id, '')})", date=dt_s)
                        db.add(mov); db.commit(); db.refresh(mov)
                        buckets = load_buckets(user.id)
                        dist = distribute_by_buckets(db, user.id, buckets, float(valor_s), "Saída", dt_s, f"Saída do balde {balde_opcoes.get(balde_id, '')}", auto=True)
                        # Atualiza saldo do balde escolhido
                        balde = db.query(Bucket).filter(Bucket.id == int(balde_id)).first()
                        if balde:
                            balde.balance -= float(valor_s)
                            db.add(balde)
                            db.commit()
                        if not dist:
                            st.error("Falha ao dividir nos baldes.")
                            return
                    st.success(f"✅ Saída registrada e debitada do balde '{balde_opcoes.get(balde_id, '')}'.")
                    st.toast("💸 Saída registrada!", icon="💸")
                    st.cache_data.clear(); st.stop()
                except Exception as e:
                    st.error(f"Falha ao registrar: {e}")

def page_livro_caixa(user: User):
    st.markdown("## 📚 Livro Caixa")
    movs = load_movements(user.id, 500)
    if not movs:
        st.info("Sem movimentações.")
        return
    # Organiza todas as movimentações em uma tabela única
    df = pd.DataFrame([
        {
            "ID": m.id,
            "Data": date_br(m.date),
            "Descrição": m.description,
            "Tipo": "Receita" if m.kind == "Receita" else "Despesa",
            "Valor": money_br(m.amount if m.kind == "Receita" else -m.amount)
        }
        for m in movs
    ])
    st.markdown("### Movimentações")
    st.dataframe(df, hide_index=True, use_container_width=True)

def page_calendario(user: User):
    st.markdown("## 📅 Calendário")
    with get_db() as db:
        with st.form("conta"):
            desc = st.text_input("Descrição", key="conta_desc")
            val  = currency_input("Valor (R$)", key="conta_val", default=0.0)
            venc = st.date_input("Vencimento", value=date.today(), key="conta_venc")
            crit = st.checkbox("Importante", key="conta_crit")
            ok   = st.form_submit_button("Adicionar")
        if ok:
            if not desc.strip() or val <= 0:
                st.error("Preencha a descrição e valor > 0.")
            else:
                bill = Bill(user_id=user.id, title=desc.strip(), amount=float(val), due_date=venc, is_critical=crit, paid=False)
                db.add(bill); db.commit()
                st.success("Conta adicionada."); st.cache_data.clear(); st.rerun()

        bills = load_bills(user.id)
        if bills:
            df = pd.DataFrame([{
                "ID": b.id, "Descrição": b.title, "Valor": money_br(b.amount),
                "Vencimento": date_br(b.due_date), "Importante": "🔴" if b.is_critical else "⚪", "Pago": "✅" if b.paid else "❌"
            } for b in bills])
            st.dataframe(df, hide_index=True, use_container_width=True)
        else:
            st.info("Nenhuma conta cadastrada.")

def page_config(user: User):
    st.markdown("## ⚙️ Configurações")
    prof = load_profile(user.id)
    with get_db() as db:
        with st.form("perfil"):
            renda = currency_input("Renda Mensal", key="perfil_renda", default=float(prof.monthly_income))
            desp  = currency_input("Despesa Mensal", key="perfil_desp", default=float(prof.monthly_expense))
            ok = st.form_submit_button("Salvar")
        if ok:
            prof.monthly_income  = float(renda)
            prof.monthly_expense = float(desp)
            db.add(prof); db.commit()
            st.success("Perfil atualizado."); st.cache_data.clear(); st.rerun()

# =====================
# Router principal
# =====================
def main():
    # autenticação
    init_auth()
    if not st.session_state.authenticated:
        show_login()
        return

    user: User = st.session_state.user

    with st.sidebar:
        st.markdown("## ☰ Menu")
        if st.button("Sair"):
            logout()
        st.divider()
        menu = st.radio(
            "Navegar",
            ["Dashboard", "Plano de Ataque", "Baldes", "Entradas", "Livro Caixa", "Calendário", "Configurações"],
            index=0, label_visibility="collapsed"
        )

    # roteamento
    if menu == "Dashboard":
        page_dashboard(user)
    elif menu == "Plano de Ataque":
        page_plano_ataque(user)
    elif menu == "Baldes":
        page_baldes(user)
    elif menu == "Entradas":
        page_entradas(user)
    elif menu == "Livro Caixa":
        page_livro_caixa(user)
    elif menu == "Calendário":
        page_calendario(user)
    else:
        page_config(user)

if __name__ == "__main__":
    # pragmas (apenas SQLite)
    try:
        if DB_URL.startswith("sqlite"):
            with engine.connect() as c:
                c.exec_driver_sql("PRAGMA journal_mode=WAL;")
                c.exec_driver_sql("PRAGMA synchronous=NORMAL;")
                c.exec_driver_sql("PRAGMA foreign_keys=ON;")
    except Exception:
        pass
    main()
