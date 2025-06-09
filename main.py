# main.py
"""
🌐 FlexiPay Bot
---------------
Sistema completo de movimentação financeira via Telegram com foco em
privacidade, automação e facilidade de uso.
"""

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import logging
from logging.handlers import RotatingFileHandler
import base64
from io import BytesIO

# Módulos internos do projeto
import config      # ⚙️ Configurações, chaves e mensagens
import database    # 🗃️ Operações com banco de dados
import pay         # 💳 Integração com gateway de pagamento
import adm         # 👑 Funções administrativas

# =============================================
# 📜 CONFIGURAÇÃO DE LOGGING
# =============================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler("flexypay.log", maxBytes=5*1024*1024, backupCount=3),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# =============================================
# 🚀 INICIALIZAÇÃO DO BOT
# =============================================
bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN, parse_mode="Markdown")
adm.register_admin_handlers(bot)

logger.info(f"✅ Iniciando {config.NOME_BOT}...")
logger.info(f"   - Modo: {'PRODUÇÃO' if config.PRODUCTION else 'DESENVOLVIMENTO'}")
logger.info(f"   - Admins Configurados: {len(config.ADMIN_TELEGRAM_IDS)}")

# =============================================
# 🎬 FUNÇÃO PARA CRIAR O MENU PRINCIPAL
# =============================================
def criar_menu_principal():
    """Cria e retorna o teclado do menu principal com botões interativos."""
    markup = InlineKeyboardMarkup(row_width=2)
    
    # Botões do menu
    btn_depositar = InlineKeyboardButton("📥 Depositar (PIX)", callback_data="menu_depositar")
    btn_sacar = InlineKeyboardButton("📤 Sacar", callback_data="menu_sacar")
    btn_carteira = InlineKeyboardButton("💼 Minha Carteira", callback_data="menu_carteira")
    btn_taxas = InlineKeyboardButton("💰 Taxas", callback_data="menu_taxas")
    btn_suporte = InlineKeyboardButton("🛎️ Suporte", callback_data="menu_suporte")
    btn_canal = InlineKeyboardButton("📢 Canal", callback_data="menu_canal")

    markup.add(btn_depositar, btn_sacar, btn_carteira, btn_taxas, btn_suporte, btn_canal)
    return markup

# =============================================
# 🏷️ HANDLERS DE COMANDOS DO USUÁRIO
# =============================================

@bot.message_handler(commands=['start', 'help'])
def handle_start(message):
    """
    Handler para /start e /help. Exibe a mensagem de boas-vindas com o menu de botões.
    """
    user = message.from_user
    logger.info(f"👋 Usuário {user.id} ('{user.first_name}') iniciou o bot.")
    database.create_user_if_not_exists(user.id, user.username, user.first_name)
    
    saldo = database.get_balance(user.id)
    
    # Mensagem de boas-vindas com saldo e botões
    welcome_text = (
        f"Olá, *{user.first_name}*!\n"
        f"Seu saldo atual é de *R$ {saldo:.2f}*.\n\n"
        f"👇 Escolha uma opção abaixo para começar:"
    )
    bot.reply_to(message, welcome_text, reply_markup=criar_menu_principal())

# =============================================
# 📞 HANDLER PARA CALLBACKS DOS BOTÕES
# =============================================

@bot.callback_query_handler(func=lambda call: call.data.startswith('menu_'))
def handle_menu_callbacks(call):
    """Processa os cliques nos botões do menu principal."""
    action = call.data.split('_')[1]
    message = call.message

    # Responde ao clique para o Telegram saber que foi processado
    bot.answer_callback_query(call.id)

    if action == "depositar":
        handle_pix_deposit(message, from_button=True)
    elif action == "sacar":
        bot.send_message(message.chat.id, "💸 Para sacar, use o comando no formato:\n`/sacar <sua_chave_pix> <valor_total_a_debitar>`\n\n*Exemplo:*\n`/sacar cpf:123.456.789-00 100`")
    elif action == "carteira":
        handle_carteira(message, from_button=True)
    elif action == "taxas":
        handle_taxa(message, from_button=True)
    elif action == "suporte":
        handle_suporte(message, from_button=True)
    elif action == "canal":
        handle_canal(message, from_button=True)

# =============================================
# LÓGICA DOS COMANDOS
# =============================================
# (As funções abaixo agora podem ser chamadas pelos botões ou pelos comandos)

@bot.message_handler(commands=['carteira'])
def handle_carteira(message, from_button=False):
    """Exibe o saldo atual e informações da carteira do usuário."""
    user = message.from_user
    if not from_button: logger.info(f"👤 Usuário {user.id} consultou a carteira via comando.")
    
    database.create_user_if_not_exists(user.id, user.username, user.first_name)
    saldo = database.get_balance(user.id)
    last_update = database.get_last_transaction_date(user.id)
    
    response = (
        f"💼 *Sua Carteira {config.NOME_BOT}*\n\n"
        f"👤 Titular: {user.first_name}\n"
        f"🆔 ID: `{user.id}`\n\n"
        f"💰 *Saldo Disponível:*\n"
        f"   *R$ {saldo:.2f}*\n\n"
        f"📅 Última movimentação: {last_update}"
    )
    bot.send_message(message.chat.id, response)

@bot.message_handler(commands=['pix'])
def handle_pix_deposit(message, from_button=False):
    """
    Gera uma cobrança PIX para o usuário com uma imagem fixa personalizada.
    Se o 'from_button' for True, apenas exibe as instruções de uso.
    """
    user = message.from_user
    # Loga a ação apenas se for iniciada por um comando de texto
    if not from_button:
        logger.info(f"💰 Usuário {user.id} solicitou um depósito PIX via comando.")
    
    parts = message.text.split()
    
    # Se o comando foi acionado por um botão do menu, dê as instruções
    if from_button:
        bot.send_message(message.chat.id, "📥 Para depositar, use o comando no formato:\n`/pix <valor>`\n\n*Exemplo:*\n`/pix 75.50`")
        return

    # Validação para o comando via texto
    if len(parts) < 2:
        bot.reply_to(message, "⚠️ Formato incorreto!\nUso: `/pix <valor>`\nExemplo: `/pix 50`")
        return

    try:
        # Tenta converter o valor para um número
        valor = float(parts[1].replace(',', '.'))
        
        # Valida se o valor está dentro dos limites definidos em config.py
        if not (config.LIMITE_MINIMO_DEPOSITO <= valor <= config.LIMITE_MAXIMO_DEPOSITO):
            msg = f"⚠️ *Valor fora dos limites!*\nO depósito deve ser entre *R$ {config.LIMITE_MINIMO_DEPOSITO:.2f}* e *R$ {config.LIMITE_MAXIMO_DEPOSITO:.2f}*."
            bot.reply_to(message, msg)
            return

        bot.send_chat_action(message.chat.id, 'typing')
        
        # Chama a função para gerar o pagamento no gateway
        pix_data = pay.generate_pix_payment(valor, user.id, f"Depósito {config.NOME_BOT} ID {user.id}")

        # Verifica se o gateway retornou um erro
        if not pix_data.get('success'):
            bot.reply_to(message, f"❌ *Falha ao gerar PIX.*\nMotivo: {pix_data.get('error', 'Erro desconhecido.')}")
            return

        # Grava a transação no banco de dados com status pendente
        transaction_id = database.record_transaction(
            user_telegram_id=user.id, type="DEPOSIT", amount=valor,
            status=config.STATUS_DEPOSITO_PENDENTE,
            mercado_pago_id=str(pix_data['payment_id'])
        )

        # Prepara o texto completo que irá na legenda da imagem
        msg_pix_caption = (
            f"✅ *PIX Gerado com Sucesso!*\n\n"
            f"Valor a pagar: *R$ {valor:.2f}*\n"
            f"ID da Transação: `{transaction_id}`\n\n"
            f"👇 *Copie o código abaixo e pague no seu app do banco:*\n"
            f"`{pix_data['pix_copy_paste']}`"
        )

        # --- LÓGICA DE ENVIO DA IMAGEM FIXA ---
        # Tenta enviar a sua imagem personalizada com o texto do PIX na legenda.
        try:
            # O nome do arquivo deve ser exatamente o que você salvou na pasta do projeto
            with open('pix.jpg', 'rb') as foto_fixa:
                bot.send_photo(message.chat.id, photo=foto_fixa, caption=msg_pix_caption)
            
            logger.info(f"✅ PIX de R${valor:.2f} enviado com IMAGEM FIXA para usuário {user.id}.")

        except FileNotFoundError:
            # Se a imagem não for encontrada, o bot não trava.
            # Ele envia uma mensagem de texto simples para não perder a transação.
            logger.error("ERRO CRÍTICO: A imagem 'imagem_pix.png' não foi encontrada! Enviando PIX como texto puro.")
            bot.send_message(message.chat.id, msg_pix_caption)
        # --- FIM DA LÓGIca DE ENVIO ---

    except ValueError:
        bot.reply_to(message, "❌ Valor inválido. Use apenas números. Ex: `/pix 50.75`")
    except Exception as e:
        logger.error(f"💥 Erro inesperado em /pix para {user.id}: {e}", exc_info=True)
        bot.reply_to(message, "❌ Ocorreu um erro crítico. Tente novamente mais tarde.")

@bot.message_handler(commands=['sacar'])
def handle_saque(message):
    """Processa uma solicitação de saque."""
    user = message.from_user
    logger.info(f"💸 Usuário {user.id} iniciou uma solicitação de saque.")
    database.create_user_if_not_exists(user.id, user.username, user.first_name)

    parts = message.text.split()
    if len(parts) < 3:
        bot.reply_to(message, "⚠️ *Uso incorreto!*\n`/sacar <sua_chave_pix> <valor_total_a_debitar>`\n\n*Exemplo:*\n`/sacar cpf:12345678900 100`")
        return

    chave_pix = parts[1]
    
    try:
        valor_total_debito = float(parts[2].replace(',', '.'))
        # (Lógica completa de saque que já fizemos)
        if valor_total_debito <= config.TAXA_SAQUE_FIXA:
            bot.reply_to(message, f"❌ O valor a debitar deve ser maior que a taxa fixa de R$ {config.TAXA_SAQUE_FIXA:.2f}.")
            return

        valor_a_receber = round((valor_total_debito - config.TAXA_SAQUE_FIXA) / (1 + config.TAXA_SAQUE_PERCENTUAL), 2)
        
        if valor_a_receber <= 0:
             bot.reply_to(message, f"❌ O valor a debitar é muito baixo e não resulta em um saque válido.")
             return
        
        taxa_final = round(valor_total_debito - valor_a_receber, 2)
        saldo_atual = database.get_balance(user.id)

        if saldo_atual < valor_total_debito:
            bot.reply_to(message, f"❌ *Saldo insuficiente.*\nSeu saldo: *R$ {saldo_atual:.2f}* | Necessário: *R$ {valor_total_debito:.2f}*")
            return

        conn = database.get_db_connection()
        conn.execute("BEGIN")
        try:
            database.update_balance(user.id, -valor_total_debito, conn_ext=conn)
            transaction_id = database.record_transaction(
                conn_ext=conn, user_telegram_id=user.id, type="WITHDRAWAL",
                amount=valor_a_receber, status=config.STATUS_EM_ANALISE, pix_key=chave_pix
            )
            database.record_transaction(
                conn_ext=conn, user_telegram_id=user.id, type="FEE",
                amount=taxa_final, status=config.STATUS_CONCLUIDO,
                admin_notes=f"Taxa referente ao saque ID {transaction_id}"
            )
            conn.commit()
            adm.notify_admin_of_withdrawal_request(transaction_id, user.id, user.first_name, valor_a_receber, chave_pix)
            bot.reply_to(message,
                         f"✅ *Solicitação de saque enviada!*\n\n"
                         f"➖ Débito total: *R$ {valor_total_debito:.2f}*\n"
                         f"💸 Você receberá: *R$ {valor_a_receber:.2f}*\n"
                         f"📋 Taxa: R$ {taxa_final:.2f}\n\n"
                         f"🔑 Chave PIX: `{chave_pix}`\n"
                         f"🆔 ID: `{transaction_id}`")
        except Exception as e_atomic:
            conn.rollback()
            logger.critical(f"💥 Erro atômico no /sacar para {user.id}: {e_atomic}", exc_info=True)
            bot.reply_to(message, "❌ Erro crítico ao registrar sua solicitação. Nenhum valor foi debitado.")
        finally:
            if conn: conn.close()
    except ValueError:
        bot.reply_to(message, "❌ Valor inválido. Ex: `/sacar chave@pix.com 100`")
    except Exception as e:
        logger.error(f"💥 Erro inesperado no /sacar para {user.id}: {e}", exc_info=True)
        bot.reply_to(message, "❌ Ocorreu um erro inesperado.")

@bot.message_handler(commands=['taxa'])
def handle_taxa(message, from_button=False):
    """Exibe as taxas de operação de forma clara para o usuário."""
    if not from_button: logger.info(f"💰 Usuário {message.from_user.id} consultou as taxas.")
    texto_taxas = (
        "💰 *Taxas de Operação*\n\n"
        "📥 *DEPÓSITO:*\n"
        f"• *{config.TAXA_DEPOSITO_PERCENTUAL * 100:.1f}%* sobre o valor depositado.\n"
        "_Ex: Ao depositar R$100, você recebe R$89 em saldo._\n\n"
        "📤 *SAQUE:*\n"
        f"• *{config.TAXA_SAQUE_PERCENTUAL * 100:.1f}%* sobre o valor a receber\n"
        f"• *+ R$ {config.TAXA_SAQUE_FIXA:.2f}* fixos por transação."
    )
    bot.send_message(message.chat.id, texto_taxas)

@bot.message_handler(commands=['suporte'])
def handle_suporte(message, from_button=False):
    """Fornece os canais de suporte ao usuário."""
    if not from_button: logger.info(f"🆘 Usuário {message.from_user.id} solicitou suporte.")
    markup = InlineKeyboardMarkup().add(InlineKeyboardButton(text="🤖 Falar com o Suporte", url=config.BOT_SUPORTE))
    support_msg = (
        f"🛎️ *Suporte {config.NOME_BOT}*\n\n"
        f"Clique no botão para falar com nossa equipe.\n"
        f"Seu ID de usuário: `{message.from_user.id}`"
    )
    bot.send_message(message.chat.id, support_msg, reply_markup=markup, disable_web_page_preview=True)

@bot.message_handler(commands=['canal'])
def handle_canal(message, from_button=False):
    """Envia o link do canal oficial."""
    if not from_button: logger.info(f"📢 Usuário {message.from_user.id} pediu o link do canal.")
    channel_msg = f"📢 *Canal Oficial {config.NOME_BOT}*\n\nAcesse e fique por dentro de todas as novidades:\n{config.CANAL_OFICIAL}"
    bot.send_message(message.chat.id, channel_msg, disable_web_page_preview=True)

# =============================================
# ▶️ INICIAR O BOT
# =============================================
if __name__ == '__main__':
    logger.info("--- BOT INICIADO E PRONTO PARA RECEBER COMANDOS ---")
    try:
        bot.infinity_polling(timeout=30, long_polling_timeout=5)
    except Exception as e:
        logger.critical(f"🆘 O BOT PAROU DE FUNCIONAR! Erro fatal no polling: {e}", exc_info=True)