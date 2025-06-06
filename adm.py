# adm.py (Versão Melhorada)
"""
👑 Módulo Administrativo
------------------------
Contém todos os handlers e funções para o painel de administração do bot.
Permite visualizar e gerenciar saques, verificar lucros e outras tarefas.
"""
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import logging
import config
import database
import pay

logger = logging.getLogger(__name__)
bot = None  # Instância global do bot, inicializada por register_admin_handlers

def register_admin_handlers(bot_instance):
    """
    Registra todos os handlers de comandos e callbacks relacionados ao admin.
    Esta função é chamada em main.py para injetar a instância do bot.
    """
    global bot
    bot = bot_instance

    def is_admin(user_id):
        """Verifica se um ID de usuário pertence a um administrador."""
        return user_id in config.ADMIN_TELEGRAM_IDS

    # -------------------------------------
    # COMANDO PRINCIPAL DO PAINEL ADMIN
    # -------------------------------------
    @bot.message_handler(commands=['admin', 'adm'])
    def handle_admin_command(message):
        """Exibe o painel de administração se o usuário for um admin."""
        if not is_admin(message.from_user.id):
            bot.reply_to(message, "❌ Acesso negado. Este comando é restrito.")
            logger.warning(f"⚠️ Tentativa de acesso não autorizado ao /admin por user_id: {message.from_user.id}")
            return

        logger.info(f"👑 Admin {message.from_user.id} acessou o painel.")
        markup = InlineKeyboardMarkup(row_width=1)
        btn_pending = InlineKeyboardButton("💰 Ver Saques Pendentes", callback_data="admin_view_pending")
        btn_profit = InlineKeyboardButton("📈 Ver Lucro com Taxas", callback_data="admin_view_profit")
        markup.add(btn_pending, btn_profit)
        bot.send_message(message.chat.id, "⚙️ *Painel do Administrador*", reply_markup=markup)

    # -------------------------------------
    # HANDLERS PARA BOTÕES DO PAINEL
    # -------------------------------------
    @bot.callback_query_handler(func=lambda call: call.data.startswith("admin_view_"))
    def handle_admin_view_actions(call):
        """Processa cliques nos botões 'Ver Saques' e 'Ver Lucro'."""
        if not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "❌ Ação não permitida!", show_alert=True)
            return

        action = call.data.split("_")[2]
        admin_id = call.from_user.id
        
        if action == "pending":
            logger.info(f"👑 Admin {admin_id} solicitou a lista de saques pendentes.")
            bot.answer_callback_query(call.id, "Buscando saques pendentes...")
            pending_withdrawals = database.get_pending_withdrawals()
            
            if not pending_withdrawals:
                bot.edit_message_text("✅ Nenhum saque pendente no momento.", call.message.chat.id, call.message.message_id)
                return
            
            bot.edit_message_text(f" encontrei {len(pending_withdrawals)} saques. Enviando detalhes...", call.message.chat.id, call.message.message_id)
            for trx in pending_withdrawals:
                user_info = database.get_user_info(trx['user_telegram_id'])
                notify_admin_of_withdrawal_request(
                    transaction_id=trx['id'],
                    user_telegram_id=trx['user_telegram_id'],
                    user_first_name=user_info['first_name'] if user_info else f"ID {trx['user_telegram_id']}",
                    amount=trx['amount'],
                    pix_key=trx['pix_key'],
                    target_admin_id=admin_id # Envia apenas para o admin que solicitou
                )

        elif action == "profit":
            logger.info(f"👑 Admin {admin_id} solicitou o relatório de lucros.")
            bot.answer_callback_query(call.id, "Calculando lucro...")
            total_profit = database.calculate_profits()
            bot.edit_message_text(
                f"📈 *Lucro Total Acumulado*\n\nO lucro total gerado a partir de todas as taxas de serviço é de: *R$ {total_profit:.2f}*",
                call.message.chat.id, call.message.message_id
            )

    # -------------------------------------
    # HANDLER PARA AÇÕES DE SAQUE (APROVAR/REJEITAR)
    # -------------------------------------
    @bot.callback_query_handler(func=lambda call: call.data.startswith("admin_withdraw_"))
    def handle_admin_withdrawal_action(call):
        """Processa a aprovação ou rejeição de uma solicitação de saque."""
        admin_id = call.from_user.id
        if not is_admin(admin_id):
            bot.answer_callback_query(call.id, "❌ Ação não permitida!", show_alert=True)
            return

        try:
            _, _, action, transaction_id_str = call.data.split("_")
            transaction_id = int(transaction_id_str)
        except ValueError:
            logger.error(f"Erro ao parsear callback_data: {call.data}")
            bot.answer_callback_query(call.id, "❌ Erro no formato do comando.", show_alert=True)
            return

        transaction = database.get_transaction_details(transaction_id)
        if not transaction or transaction['status'] != config.STATUS_EM_ANALISE:
            bot.answer_callback_query(call.id, "⚠️ Transação não encontrada ou já processada.", show_alert=True)
            bot.edit_message_text("Esta solicitação já foi tratada por outro administrador ou não é mais válida.", call.message.chat.id, call.message.message_id, reply_markup=None)
            return
        
        user_telegram_id = transaction['user_telegram_id']
        original_amount = transaction['amount']

        if action == "approve":
            logger.info(f"👑 Admin {admin_id} iniciou APROVAÇÃO do saque {transaction_id} no valor de R${original_amount:.2f}.")
            bot.answer_callback_query(call.id, "⏳ Processando pagamento...")
            bot.edit_message_text(f"⏳ Processando pagamento para saque ID `{transaction_id}` (R${original_amount:.2f})...", call.message.chat.id, call.message.message_id, reply_markup=None)
            database.update_transaction_status(transaction_id, config.STATUS_EM_ANDAMENTO)
            
            payout_result = pay.process_payout(
                transaction_id_local=transaction_id,
                amount=original_amount,
                pix_key_receiver=transaction['pix_key'],
                description=f"Saque {config.NOME_BOT} ID {transaction_id}"
            )

            if payout_result.get('success'):
                payout_id = payout_result.get('payout_id')
                database.update_transaction_status(transaction_id, config.STATUS_CONCLUIDO, mp_id=payout_id)
                bot.send_message(user_telegram_id, f"✅ Seu saque de R${original_amount:.2f} foi *APROVADO* e o pagamento foi enviado!\nID da transação: `{transaction_id}`")
                bot.edit_message_text(f"✅ Saque ID `{transaction_id}` (R${original_amount:.2f}) *APROVADO E PAGO*.\nID do Gateway: `{payout_id}`", call.message.chat.id, call.message.message_id)
                logger.info(f"✅ Saque {transaction_id} APROVADO e pago pelo admin {admin_id}.")
            else:
                error_msg = payout_result.get('message', 'Erro desconhecido')
                database.update_transaction_status(transaction_id, config.STATUS_FALHA_PAGAMENTO, admin_notes=f"Admin {admin_id} tentou aprovar. Gateway: {error_msg}")
                fee_amount = database.get_fee_for_withdrawal(transaction_id)
                total_to_refund = original_amount + fee_amount
                
                if database.update_balance(user_telegram_id, total_to_refund):
                    bot.send_message(user_telegram_id, f"⚠️ *Atenção:* Ocorreu uma falha no envio do seu saque de R${original_amount:.2f} (ID: `{transaction_id}`). O valor total de *R${total_to_refund:.2f}* foi estornado ao seu saldo. Por favor, tente novamente mais tarde ou contate o suporte.")
                    bot.edit_message_text(f"❌ *FALHA NO PAGAMENTO* para saque ID `{transaction_id}`.\nMotivo: {error_msg}\n\n*O valor total (saque + taxa) foi estornado ao saldo do usuário.*", call.message.chat.id, call.message.message_id)
                    logger.error(f"❌ Falha no pagamento do saque {transaction_id} (Admin: {admin_id}). Valor estornado ao usuário.")
                else:
                    logger.critical(f"🆘 CRÍTICO: FALHA NO PAGAMENTO do saque {transaction_id} E FALHA AO ESTORNAR o saldo para o usuário {user_telegram_id}. INTERVENÇÃO MANUAL URGENTE!")
                    bot.edit_message_text(f"🆘 *CRÍTICO:* Falha no pagamento para saque ID `{transaction_id}` E *FALHA AO ESTORNAR O SALDO*. Contate o suporte técnico imediatamente!", call.message.chat.id, call.message.message_id)

        elif action == "reject":
            logger.info(f"👑 Admin {admin_id} iniciou REJEIÇÃO do saque {transaction_id}.")
            bot.answer_callback_query(call.id, "🚫 Rejeitando e estornando valor...")
            fee_amount = database.get_fee_for_withdrawal(transaction_id)
            total_to_refund = original_amount + fee_amount
            
            if database.update_balance(user_telegram_id, total_to_refund):
                admin_notes = f"Rejeitado pelo administrador {admin_id}."
                database.update_transaction_status(transaction_id, config.STATUS_RECUSADO, admin_notes=admin_notes)
                bot.edit_message_text(f"🚫 Saque ID `{transaction_id}` *RECUSADO*. O valor de R$ {total_to_refund:.2f} foi estornado com sucesso ao usuário.", call.message.chat.id, call.message.message_id, reply_markup=None)
                bot.send_message(user_telegram_id, f"❌ Sua solicitação de saque de R${original_amount:.2f} (ID: `{transaction_id}`) foi *RECUSADA*. O valor total debitado de R${total_to_refund:.2f} foi devolvido integralmente ao seu saldo.")
                logger.info(f"🚫 Saque {transaction_id} REJEITADO pelo admin {admin_id}. Valor estornado.")
            else:
                logger.critical(f"🆘 CRÍTICO: FALHA AO ESTORNAR saldo para o saque rejeitado {transaction_id} (Admin: {admin_id}). INTERVENÇÃO MANUAL URGENTE!")
                bot.edit_message_text(f"🆘 *CRÍTICO:* Saque ID `{transaction_id}` rejeitado, MAS FALHOU AO ESTORNAR O SALDO. Contate o suporte técnico imediatamente!", call.message.chat.id, call.message.message_id)


def notify_admin_of_withdrawal_request(transaction_id, user_telegram_id, user_first_name, amount, pix_key, target_admin_id=None):
    """
    Envia uma mensagem de notificação para os administradores sobre um novo saque.
    Se target_admin_id for especificado, envia apenas para ele.
    """
    admin_list = [target_admin_id] if target_admin_id else config.ADMIN_TELEGRAM_IDS
    if not admin_list:
        logger.warning(f"⚠️ Nenhum administrador para notificar sobre o saque {transaction_id}.")
        return

    markup = InlineKeyboardMarkup(row_width=2)
    btn_approve = InlineKeyboardButton("✅ Aprovar Pagamento", callback_data=f"admin_withdraw_approve_{transaction_id}")
    btn_reject = InlineKeyboardButton("❌ Recusar e Estornar", callback_data=f"admin_withdraw_reject_{transaction_id}")
    markup.add(btn_approve, btn_reject)

    message_text = (
        f"⚠️ *Nova Solicitação de Saque Pendente:*\n\n"
        f"👤 *Usuário:* {user_first_name} (`{user_telegram_id}`)\n"
        f"🆔 *ID da Transação:* `{transaction_id}`\n\n"
        f"💸 *Valor a Pagar (Líquido):* `R$ {amount:.2f}`\n"
        f"🔑 *Chave PIX:* `{pix_key}`"
    )

    for admin_id in admin_list:
        try:
            bot.send_message(admin_id, message_text, reply_markup=markup)
            logger.info(f"📬 Notificação de saque {transaction_id} enviada ao admin ID: {admin_id}.")
        except Exception as e:
            logger.error(f"❌ Erro ao enviar notificação de saque {transaction_id} para admin ID {admin_id}: {e}")