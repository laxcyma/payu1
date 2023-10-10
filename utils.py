import hashlib
import random
import string

from fleio.billing.models.transaction import TransactionStatus

from .conf import conf


class PayUTransactionStatus:
    pending = 'PENDING'
    completed = 'COMPLETED'
    waiting_for_confirmation = 'WAITING_FOR_CONFIRMATION'
    refunded = 'REFUNDED'
    canceled = 'CANCELED'

    to_transaction_model_status = {
        pending: TransactionStatus.WAITING,
        completed: TransactionStatus.CONFIRMED,
        waiting_for_confirmation: TransactionStatus.PREAUTH,
    }


class PayUUtils:
    @staticmethod
    def validate_open_payu_signature(open_payu_signature, body) -> bool:
        if not open_payu_signature:
            return False
        open_payu_signature = open_payu_signature.strip()
        try:
            open_payu_signature_as_dict = dict(item.split("=") for item in open_payu_signature.split(';'))
        except Exception as e:
            del e  # unused
            return False
        incoming_signature = open_payu_signature_as_dict.get('signature')
        stripped = body.decode('utf-8').strip()
        concatenated = stripped + conf.second_key
        concatenated = concatenated.strip()
        algorithm = open_payu_signature_as_dict.get('algorithm', 'md5')
        expected_signature = hashlib.new(name=algorithm, data=concatenated.encode('utf-8')).hexdigest()
        if expected_signature == incoming_signature:
            return True
        return False

    @staticmethod
    def get_payu_amount_in_fleio_amount(amount) -> float:
        if not isinstance(amount, int):
            amount = int(amount)
        return amount / 100

    @staticmethod
    def get_fleio_amount_in_payu_amount(amount) -> float:
        return int(amount * 100)

    @staticmethod
    def generate_external_order_id(invoice_id: str) -> str:
        # we need to generate a unique string using the invoice id as extOrderId has to be unique and if someone
        # does not complete payment, the order has to be re-created with a different extOrderId
        # the first part before the dash is the invoice id and the rest is the random generated 16 characters string
        random_string = ''.join(
            random.choice(  # nosec B311
                string.ascii_uppercase + string.ascii_lowercase + string.digits
            ) for _ in range(16)
        )
        return '{}-{}'.format(invoice_id, random_string)

    @staticmethod
    def get_invoice_id_from_external_order_id(external_order_id: str) -> str:
        content = external_order_id.split('-')  # type: list
        return content[0]
