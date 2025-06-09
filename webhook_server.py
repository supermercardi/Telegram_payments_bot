# webhook_server.py
from flask import Flask, request, jsonify
import logging
import json
import config
import database
import pay

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/webhook/mp', methods=['POST'])
def mercadopago_webhook():
    data = request.json
    logger.info(f"Webhook recebido: {json.dumps(data, indent=2)}")

    if data and data.get("type") == "payment":
        payment_id_mp = data.get("data", {}).get("id")
        if not payment_id_mp:
            logger.warning("Webhook de pagamento recebido sem ID.")
            return jsonify({"status": "error", "message": "No payment ID"}), 400

        try:
            payment_details = pay.get_payment_details(payment_id_mp)
            if not payment_details:
                logger.error(f"Não foi possível obter detalhes do pagamento MP ID: {payment_id_mp}")
                return jsonify({"status": "error", "message": "Failed to get payment details"}), 500

            status_mp = payment_details.get("status")
            valor_pago = payment_details.get("transaction_amount")
            mp_id_str = str(payment_details.get("id"))

            # <<< ALTERAÇÃO: Trocando '?' por '%s' na consulta >>>
            conn = database.get_db_connection()
            # Usando DictCursor para acessar colunas por nome
            cursor = conn.cursor(cursor_factory=database.DictCursor)
            cursor.execute("SELECT * FROM transactions WHERE mercado_pago_id = %s AND status = %s", 
                           (mp_id_str, config.STATUS_DEPOSITO_PENDENTE))
            transaction = cursor.fetchone()
            conn.close()

            if not transaction:
                logger.warning(f"Transação PENDENTE não encontrada para o MP ID: {mp_id_str}.")
                return jsonify({"status": "ok", "message": "Transaction already processed or not found"}), 200

            if status_mp == "approved":
                user_id = transaction['user_telegram_id']
                valor_deposito = transaction['amount']

                if float(valor_pago) != float(valor_deposito):
                    logger.error(f"Divergência de valor para MP ID {mp_id_str}! Esperado: {valor_deposito}, Pago: {valor_pago}")
                    database.update_transaction_status(transaction['id'], "ERRO_DIVERGENCIA", admin_notes=f"Esperado R${valor_deposito}, pago R${valor_pago}")
                    return jsonify({"status": "error", "message": "Amount mismatch"}), 400

                taxa_deposito = valor_deposito * config.TAXA_DEPOSITO_PERCENTUAL
                valor_liquido = valor_deposito - taxa_deposito

                conn_atomic = database.get_db_connection()
                try:
                    database.update_balance(user_id, valor_liquido, conn_ext=conn_atomic)
                    database.record_transaction(
                        user_telegram_id=user_id, type="FEE", amount=taxa_deposito,
                        status=config.STATUS_CONCLUIDO,
                        admin_notes=f"Taxa de depósito referente à transação ID {transaction['id']}",
                        conn_ext=conn_atomic
                    )
                    database.update_transaction_status(transaction['id'], config.STATUS_DEPOSITO_PAGO, conn_ext=conn_atomic)
                    conn_atomic.commit()
                    logger.info(f"Depósito ID {transaction['id']} para user {user_id} APROVADO. Valor creditado: R${valor_liquido:.2f}")
                except Exception as e:
                    if conn_atomic: conn_atomic.rollback()
                    logger.critical(f"FALHA CRÍTICA ao processar depósito para MP ID {mp_id_str}: {e}")
                finally:
                    if conn_atomic: conn_atomic.close()
            else:
                logger.info(f"Pagamento MP ID {mp_id_str} não foi aprovado. Status: {status_mp}")
                database.update_transaction_status(transaction['id'], status_mp.upper())

            return jsonify({"status": "ok"}), 200
        except Exception as e:
            logger.error(f"Erro ao processar webhook: {e}", exc_info=True)
            return jsonify({"status": "error", "message": "Internal server error"}), 500
    
    return jsonify({"status": "ignored", "message": "Not a payment notification"}), 200

if __name__ == '__main__':
    app.run(port=5000, debug=True)