# database.py (Versão para PostgreSQL)
"""
🗃️ Módulo de Banco de Dados
---------------------------
Responsável por todas as interações com o banco de dados PostgreSQL.
Inclui criação de tabelas, CRUD de usuários e transações.
"""
import psycopg2
from psycopg2.extras import DictCursor
import logging
from datetime import datetime
import config

logger = logging.getLogger(__name__)

def get_db_connection():
    """
    Cria e retorna uma nova conexão com o banco de dados PostgreSQL.
    Configura o DictCursor para permitir acesso às colunas por nome.
    """
    try:
        conn = psycopg2.connect(config.DATABASE_URL)
        return conn
    except psycopg2.OperationalError as e:
        logger.critical(f"FATAL: Não foi possível conectar ao banco de dados PostgreSQL: {e}", exc_info=True)
        raise

def init_db():
    """
    Inicializa o banco de dados, criando as tabelas se não existirem.
    """
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # Tabela de Usuários
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    balance REAL DEFAULT 0.00,
                    created_at TIMESTAMPTZ NOT NULL
                )
            ''')
            # Tabela de Transações
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS transactions (
                    id SERIAL PRIMARY KEY,
                    user_telegram_id BIGINT NOT NULL,
                    type TEXT NOT NULL,
                    amount REAL NOT NULL,
                    status TEXT NOT NULL,
                    pix_key TEXT,
                    mercado_pago_id TEXT,
                    admin_notes TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    FOREIGN KEY (user_telegram_id) REFERENCES users (telegram_id)
                )
            ''')
        conn.commit()
    logger.info("✅ Banco de dados PostgreSQL inicializado e verificado com sucesso.")

def admin_set_balance(user_telegram_id, new_balance):
    """[ADMIN] Define um novo saldo para um usuário."""
    with get_db_connection() as conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE users SET balance = %s WHERE telegram_id = %s",
                    (new_balance, user_telegram_id)
                )
                if cursor.rowcount > 0:
                    record_transaction(
                        user_telegram_id=user_telegram_id, type='AJUSTE_MANUAL',
                        amount=new_balance, status='CONCLUIDO',
                        admin_notes=f"Saldo definido para R${new_balance:.2f} por um admin."
                    )
                    conn.commit()
                    return True
                return False
        except psycopg2.Error as e:
            logger.error(f"❌ Erro no DB ao setar saldo para {user_telegram_id}: {e}", exc_info=True)
            conn.rollback()
            return False

def get_users_with_balance():
    """[ADMIN] Retorna todos os usuários com saldo maior que zero."""
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            try:
                cursor.execute("SELECT telegram_id, first_name, username, balance FROM users WHERE balance > 0 ORDER BY balance DESC")
                return cursor.fetchall()
            except psycopg2.Error as e:
                logger.error(f"❌ Erro ao buscar usuários com saldo: {e}", exc_info=True)
                return []

def create_user_if_not_exists(telegram_id, username, first_name):
    """Cria um novo usuário se ele não existir."""
    now = datetime.now()
    with get_db_connection() as conn:
        try:
            with conn.cursor() as cursor:
                sql = """
                    INSERT INTO users (telegram_id, username, first_name, balance, created_at)
                    VALUES (%s, %s, %s, 0.00, %s)
                    ON CONFLICT (telegram_id) DO NOTHING;
                """
                cursor.execute(sql, (telegram_id, username, first_name, now))
                if cursor.rowcount > 0:
                    logger.info(f"👤 Novo usuário criado: ID={telegram_id}, Nome='{first_name}'.")
            conn.commit()
        except psycopg2.Error as e:
            logger.error(f"❌ Erro ao tentar criar usuário {telegram_id}: {e}", exc_info=True)
            conn.rollback()

def get_balance(telegram_id):
    """Busca e retorna o saldo de um usuário."""
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            try:
                cursor.execute("SELECT balance FROM users WHERE telegram_id = %s", (telegram_id,))
                result = cursor.fetchone()
                return result['balance'] if result else 0.00
            except psycopg2.Error as e:
                logger.error(f"❌ Erro ao buscar saldo para {telegram_id}: {e}", exc_info=True)
                return 0.00

def update_balance(telegram_id, amount_change, conn_ext=None):
    """Atualiza o saldo de um usuário."""
    conn = conn_ext or get_db_connection()
    try:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            cursor.execute("SELECT balance FROM users WHERE telegram_id = %s FOR UPDATE", (telegram_id,))
            result = cursor.fetchone()
            current_balance = result['balance'] if result else 0.0
            new_balance = current_balance + amount_change
            if new_balance < 0:
                logger.warning(f"⚠️ Tentativa de deixar saldo negativo para {telegram_id}.")
                return False
            cursor.execute("UPDATE users SET balance = %s WHERE telegram_id = %s", (new_balance, telegram_id))
            if not conn_ext: conn.commit()
            logger.info(f"💰 Saldo de {telegram_id} atualizado. De R${current_balance:.2f} para R${new_balance:.2f} (Mudança: {amount_change:+.2f}).")
            return True
    except psycopg2.Error as e:
        logger.error(f"❌ Erro ao atualizar saldo para {telegram_id}: {e}", exc_info=True)
        if conn_ext is None and conn: conn.rollback()
        return False
    finally:
        if conn_ext is None and conn: conn.close()

def record_transaction(**kwargs):
    """Registra uma nova transação no banco de dados."""
    conn = kwargs.pop('conn_ext', None) or get_db_connection()
    now = datetime.now()
    kwargs.setdefault('pix_key', None); kwargs.setdefault('mercado_pago_id', None); kwargs.setdefault('admin_notes', None)
    kwargs['created_at'] = now; kwargs['updated_at'] = now
    try:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            columns = ', '.join(kwargs.keys())
            placeholders = ', '.join(['%s'] * len(kwargs))
            sql = f"INSERT INTO transactions ({columns}) VALUES ({placeholders}) RETURNING id"
            cursor.execute(sql, tuple(kwargs.values()))
            transaction_id = cursor.fetchone()['id']
            if 'conn_ext' not in kwargs: conn.commit()
            logger.info(f"📄 Transação {transaction_id} (Tipo: {kwargs['type']}) registrada para usuário {kwargs['user_telegram_id']}.")
            return transaction_id
    except psycopg2.Error as e:
        logger.error(f"❌ Erro ao registrar transação para {kwargs.get('user_telegram_id')}: {e}", exc_info=True)
        if 'conn_ext' not in kwargs and conn: conn.rollback()
        return None
    finally:
        if 'conn_ext' not in kwargs and conn: conn.close()

def update_transaction_status(transaction_id, new_status, **kwargs):
    """Atualiza o status e outros campos de uma transação."""
    conn = kwargs.pop('conn_ext', None) or get_db_connection()
    fields_to_update = ["status = %s", "updated_at = %s"]
    values = [new_status, datetime.now()]
    if 'mp_id' in kwargs:
        fields_to_update.append("mercado_pago_id = %s")
        values.append(kwargs['mp_id'])
    if 'admin_notes' in kwargs:
        fields_to_update.append("admin_notes = %s")
        values.append(kwargs['admin_notes'])
    values.append(transaction_id)
    try:
        with conn.cursor() as cursor:
            sql = f"UPDATE transactions SET {', '.join(fields_to_update)} WHERE id = %s"
            cursor.execute(sql, tuple(values))
            if 'conn_ext' not in kwargs: conn.commit()
        logger.info(f"🔄 Status da transação {transaction_id} atualizado para '{new_status}'.")
        return True
    except psycopg2.Error as e:
        logger.error(f"❌ Erro ao atualizar status da transação {transaction_id}: {e}", exc_info=True)
        if 'conn_ext' not in kwargs and conn: conn.rollback()
        return False
    finally:
        if 'conn_ext' not in kwargs and conn: conn.close()

def get_transaction_details(transaction_id):
    """Busca todos os detalhes de uma transação pelo seu ID."""
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            try:
                cursor.execute("SELECT * FROM transactions WHERE id = %s", (transaction_id,))
                return cursor.fetchone()
            except psycopg2.Error as e:
                logger.error(f"❌ Erro ao buscar detalhes da transação {transaction_id}: {e}", exc_info=True)
                return None

# Funções restantes (get_pending_withdrawals, calculate_profits, etc.) com placeholders %s
def get_pending_withdrawals():
    """Retorna todas as transações de saque com status 'EM ANÁLISE'."""
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            try:
                cursor.execute("SELECT * FROM transactions WHERE type = 'WITHDRAWAL' AND status = %s", (config.STATUS_EM_ANALISE,))
                return cursor.fetchall()
            except psycopg2.Error as e:
                logger.error(f"❌ Erro ao buscar saques pendentes: {e}", exc_info=True)
                return []

def calculate_profits():
    """Calcula o lucro total somando todas as transações do tipo 'FEE'."""
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            try:
                cursor.execute("SELECT SUM(amount) FROM transactions WHERE type = 'FEE' AND status = %s", (config.STATUS_CONCLUIDO,))
                result = cursor.fetchone()
                return result[0] if result and result[0] is not None else 0.00
            except psycopg2.Error as e:
                logger.error(f"❌ Erro ao calcular lucro: {e}", exc_info=True)
                return 0.00

def get_fee_for_withdrawal(withdrawal_transaction_id):
    """Busca o valor da taxa associada a uma transação de saque."""
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            try:
                note = f"Taxa referente ao saque ID {withdrawal_transaction_id}"
                cursor.execute("SELECT amount FROM transactions WHERE type = 'FEE' AND admin_notes = %s", (note,))
                result = cursor.fetchone()
                return result['amount'] if result else 0.00
            except psycopg2.Error as e:
                logger.error(f"❌ Erro ao buscar taxa para o saque {withdrawal_transaction_id}: {e}", exc_info=True)
                return 0.00

def get_user_info(telegram_id):
    """Busca informações básicas de um usuário."""
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            try:
                cursor.execute("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
                return cursor.fetchone()
            except psycopg2.Error as e:
                logger.error(f"❌ Erro ao buscar info do usuário {telegram_id}: {e}", exc_info=True)
                return None

def get_last_transaction_date(telegram_id):
    """Busca a data da última transação atualizada de um usuário."""
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            try:
                cursor.execute("SELECT updated_at FROM transactions WHERE user_telegram_id = %s ORDER BY updated_at DESC LIMIT 1", (telegram_id,))
                result = cursor.fetchone()
                if result:
                    return result['updated_at'].strftime('%d/%m/%Y %H:%M')
                return "Nenhuma transação"
            except psycopg2.Error as e:
                logger.error(f"❌ Erro ao buscar última data de transação para {telegram_id}: {e}", exc_info=True)
                return "Erro ao consultar"

init_db()