# database.py (Versão Melhorada)
"""
🗃️ Módulo de Banco de Dados
---------------------------
Responsável por todas as interações com o banco de dados SQLite.
Inclui criação de tabelas, CRUD de usuários e transações.
"""
import sqlite3
import logging
from datetime import datetime
import config

logger = logging.getLogger(__name__)

def get_db_connection():
    """
    Cria e retorna uma nova conexão com o banco de dados.
    Configura o row_factory para permitir acesso às colunas por nome.
    """
    try:
        conn = sqlite3.connect(config.DB_NAME, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        logger.critical(f"FATAL: Não foi possível conectar ao banco de dados '{config.DB_NAME}': {e}", exc_info=True)
        raise

def init_db():
    """
    Inicializa o banco de dados, criando as tabelas 'users' e 'transactions' se não existirem.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Tabela de Usuários: armazena informações básicas e o saldo.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                balance REAL DEFAULT 0.00,
                created_at TEXT NOT NULL
            )
        ''')
        # Tabela de Transações: armazena um registro de cada operação financeira.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_telegram_id INTEGER NOT NULL,
                type TEXT NOT NULL, -- 'DEPOSIT', 'WITHDRAWAL', 'FEE', 'AJUSTE_MANUAL'
                amount REAL NOT NULL,
                status TEXT NOT NULL,
                pix_key TEXT,
                mercado_pago_id TEXT,
                admin_notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_telegram_id) REFERENCES users (telegram_id)
            )
        ''')
        conn.commit()
    logger.info("✅ Banco de dados inicializado e verificado com sucesso.")

def create_user_if_not_exists(telegram_id, username, first_name):
    """Cria um novo usuário no banco de dados se ele ainda não existir."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        try:
            cursor.execute(
                "INSERT OR IGNORE INTO users (telegram_id, username, first_name, balance, created_at) VALUES (?, ?, ?, 0.00, ?)",
                (telegram_id, username, first_name, now)
            )
            conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"👤 Novo usuário criado: ID={telegram_id}, Nome='{first_name}'.")
        except sqlite3.Error as e:
            logger.error(f"❌ Erro ao tentar criar usuário {telegram_id}: {e}", exc_info=True)

def get_balance(telegram_id):
    """Busca e retorna o saldo de um usuário específico."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT balance FROM users WHERE telegram_id = ?", (telegram_id,))
            result = cursor.fetchone()
            return result['balance'] if result else 0.00
        except sqlite3.Error as e:
            logger.error(f"❌ Erro ao buscar saldo para {telegram_id}: {e}", exc_info=True)
            return 0.00

def update_balance(telegram_id, amount_change, conn_ext=None):
    """
    Atualiza o saldo de um usuário. Permite conexão externa para transações atômicas.
    
    Args:
        telegram_id (int): ID do usuário no Telegram.
        amount_change (float): Valor a ser somado (positivo para crédito, negativo para débito).
        conn_ext (sqlite3.Connection, optional): Conexão externa para operações atômicas.
    """
    conn = conn_ext or get_db_connection()
    try:
        cursor = conn.cursor()
        # Usar SELECT FOR UPDATE em bancos mais robustos para evitar race conditions
        cursor.execute("SELECT balance FROM users WHERE telegram_id = ?", (telegram_id,))
        result = cursor.fetchone()
        current_balance = result['balance'] if result else 0.0
        
        new_balance = current_balance + amount_change
        
        if new_balance < 0:
            logger.warning(f"⚠️ Tentativa de deixar saldo negativo para {telegram_id}. Saldo Atual: {current_balance}, Mudança: {amount_change}")
            return False

        cursor.execute("UPDATE users SET balance = ? WHERE telegram_id = ?", (new_balance, telegram_id))
        
        if not conn_ext:
            conn.commit()
            conn.close()

        logger.info(f"💰 Saldo de {telegram_id} atualizado. De R${current_balance:.2f} para R${new_balance:.2f} (Mudança: {amount_change:+.2f}).")
        return True
    except sqlite3.Error as e:
        logger.error(f"❌ Erro ao atualizar saldo para {telegram_id}: {e}", exc_info=True)
        if conn_ext is None and conn: conn.rollback()
        return False
    finally:
        if conn_ext is None and conn: conn.close()

def record_transaction(**kwargs):
    """
    Registra uma nova transação no banco de dados. Usa uma conexão externa se fornecida.
    Ex: record_transaction(user_telegram_id=1, type='DEPOSIT', amount=50, status='PAGO')
    """
    conn = kwargs.pop('conn_ext', None) or get_db_connection()
    
    kwargs.setdefault('pix_key', None)
    kwargs.setdefault('mercado_pago_id', None)
    kwargs.setdefault('admin_notes', None)
    now = datetime.now().isoformat()
    kwargs['created_at'] = now
    kwargs['updated_at'] = now

    try:
        cursor = conn.cursor()
        columns = ', '.join(kwargs.keys())
        placeholders = ', '.join(['?'] * len(kwargs))
        sql = f"INSERT INTO transactions ({columns}) VALUES ({placeholders})"
        
        cursor.execute(sql, tuple(kwargs.values()))
        transaction_id = cursor.lastrowid
        
        if 'conn_ext' not in kwargs: # Se a conexão é local, commita e fecha
            conn.commit()
            conn.close()

        logger.info(f"📄 Transação {transaction_id} (Tipo: {kwargs['type']}, Valor: {kwargs['amount']}) registrada para usuário {kwargs['user_telegram_id']}.")
        return transaction_id
    except sqlite3.Error as e:
        logger.error(f"❌ Erro ao registrar transação para {kwargs.get('user_telegram_id')}: {e}", exc_info=True)
        if 'conn_ext' not in kwargs and conn: conn.rollback()
        return None
    finally:
        if 'conn_ext' not in kwargs and conn: conn.close()

def update_transaction_status(transaction_id, new_status, **kwargs):
    """Atualiza o status e outros campos de uma transação existente."""
    conn = kwargs.pop('conn_ext', None) or get_db_connection()
    
    fields_to_update = ["status = ?", "updated_at = ?"]
    values = [new_status, datetime.now().isoformat()]

    if 'mp_id' in kwargs:
        fields_to_update.append("mercado_pago_id = ?")
        values.append(kwargs['mp_id'])
    if 'admin_notes' in kwargs:
        fields_to_update.append("admin_notes = ?")
        values.append(kwargs['admin_notes'])
    
    values.append(transaction_id)
    
    try:
        cursor = conn.cursor()
        sql = f"UPDATE transactions SET {', '.join(fields_to_update)} WHERE id = ?"
        cursor.execute(sql, tuple(values))

        if 'conn_ext' not in kwargs:
            conn.commit()
            conn.close()
        
        logger.info(f"🔄 Status da transação {transaction_id} atualizado para '{new_status}'.")
        return True
    except sqlite3.Error as e:
        logger.error(f"❌ Erro ao atualizar status da transação {transaction_id}: {e}", exc_info=True)
        if 'conn_ext' not in kwargs and conn: conn.rollback()
        return False
    finally:
        if 'conn_ext' not in kwargs and conn: conn.close()

def get_transaction_details(transaction_id):
    """Busca todos os detalhes de uma transação pelo seu ID."""
    with get_db_connection() as conn:
        try:
            return conn.cursor().execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,)).fetchone()
        except sqlite3.Error as e:
            logger.error(f"❌ Erro ao buscar detalhes da transação {transaction_id}: {e}", exc_info=True)
            return None

def get_pending_withdrawals():
    """Retorna todas as transações de saque com status 'EM ANÁLISE'."""
    with get_db_connection() as conn:
        try:
            return conn.cursor().execute("SELECT * FROM transactions WHERE type = 'WITHDRAWAL' AND status = ?", (config.STATUS_EM_ANALISE,)).fetchall()
        except sqlite3.Error as e:
            logger.error(f"❌ Erro ao buscar saques pendentes: {e}", exc_info=True)
            return []

def calculate_profits():
    """Calcula o lucro total somando todas as transações do tipo 'FEE'."""
    with get_db_connection() as conn:
        try:
            result = conn.cursor().execute("SELECT SUM(amount) FROM transactions WHERE type = 'FEE' AND status = ?", (config.STATUS_CONCLUIDO,)).fetchone()
            return result[0] if result and result[0] is not None else 0.00
        except sqlite3.Error as e:
            logger.error(f"❌ Erro ao calcular lucro: {e}", exc_info=True)
            return 0.00

def get_fee_for_withdrawal(withdrawal_transaction_id):
    """Busca o valor da taxa associada a uma transação de saque específica."""
    with get_db_connection() as conn:
        try:
            note = f"Taxa referente ao saque ID {withdrawal_transaction_id}"
            result = conn.cursor().execute("SELECT amount FROM transactions WHERE type = 'FEE' AND admin_notes = ?", (note,)).fetchone()
            return result['amount'] if result else 0.00
        except sqlite3.Error as e:
            logger.error(f"❌ Erro ao buscar taxa para o saque {withdrawal_transaction_id}: {e}", exc_info=True)
            return 0.00

def get_user_info(telegram_id):
    """Busca informações básicas de um usuário (como o nome)."""
    with get_db_connection() as conn:
        try:
            # Retorna o objeto Row inteiro para flexibilidade
            return conn.cursor().execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
        except sqlite3.Error as e:
            logger.error(f"❌ Erro ao buscar info do usuário {telegram_id}: {e}", exc_info=True)
            return None

def get_last_transaction_date(telegram_id):
    """
    [NOVO] Busca a data da última transação atualizada de um usuário.
    """
    with get_db_connection() as conn:
        try:
            result = conn.cursor().execute(
                "SELECT updated_at FROM transactions WHERE user_telegram_id = ? ORDER BY updated_at DESC LIMIT 1",
                (telegram_id,)
            ).fetchone()
            if result:
                # Formata a data para um formato mais legível
                return datetime.fromisoformat(result['updated_at']).strftime('%d/%m/%Y %H:%M')
            return "Nenhuma transação"
        except sqlite3.Error as e:
            logger.error(f"❌ Erro ao buscar última data de transação para {telegram_id}: {e}", exc_info=True)
            return "Erro ao consultar"

# Inicializa o banco de dados na primeira importação do módulo
init_db()