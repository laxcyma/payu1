import random
import string
# For Signature validation
import hmac
import hashlib

from fleio.billing.models.transaction import TransactionStatus

from .conf import conf

class RazorpayTransactionStatus:
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


class RazorpayUtils:
    @staticmethod
    def validate_razorpay_signature(razorpay_signature, body) -> bool:
        try:
            # Calculate the HMAC-SHA256 signature of the request body using the webhook secret
            calculated_signature = hmac.new(webhook_secret.encode('utf-8'), request_body, hashlib.sha256).hexdigest()

            # Compare the calculated signature with the signature received in the request
            return hmac.compare_digest(calculated_signature, razorpay_signature)
        except Exception as e:
            return False
        

    @staticmethod
    def get_razorpay_amount_in_fleio_amount(amount) -> float:
        if not isinstance(amount, int):
            amount = int(amount)
        return amount / 100

    @staticmethod
    def get_fleio_amount_in_razorpay_amount(amount) -> int:
        # Implement the conversion logic from your currency format to Razorpay amount (in paise)
        return int(amount * 100)

    @staticmethod
    def generate_external_order_id(invoice_id: str) -> str:
        # Generate a unique string for the external order ID
        random_string = ''.join(random.choice(string.ascii_uppercase + string.ascii_lowercase + string.digits) for _ in range(16))
        return f'{invoice_id}-{random_string}'		

    @staticmethod
    def get_invoice_id_from_external_order_id(external_order_id: str) -> str:
        # Extract the invoice ID from the external order ID
        content = external_order_id.split('-')
        return content[0]

