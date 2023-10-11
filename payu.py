import decimal
import json
import logging
import requests
from django.db import transaction as django_db_transaction
from django.http import HttpResponseRedirect
from django.utils.timezone import now as utcnow
from django.utils.translation import gettext_lazy as _
from ipware.ip import get_client_ip
from rest_framework.response import Response

from fleio.activitylog.utils.activity_helper import activity_helper
from fleio.billing.gateways import exceptions as gateway_exceptions
from fleio.billing.gateways.decorators import gateway_action
from fleio.billing.gateways.decorators import staff_gateway_action
from fleio.billing.invoicing.tasks import invoice_add_payment
from fleio.billing.invoicing.tasks import invoice_refund_payment
from fleio.billing.models import Gateway
from fleio.billing.models import Invoice
from fleio.billing.models import Transaction
from fleio.billing.models.transaction import TransactionStatus
from fleio.billing.serializers import AddTransactionSerializer
from fleio.core.models import Client
from .conf import conf
from .utils import RazorpayTransactionStatus
from .utils import RazorpayUtils

from django.http import JsonResponse

LOG = logging.getLogger(__name__)


class PayUClient:
    def __init__(self, invoice_id=None, request=None):
        self.invoice_id = invoice_id
        self.request = request
    
    def create_order(self):
        if not self.invoice_id:
            raise Exception('Cannot process request without invoice details.')
        db_invoice = Invoice.objects.filter(id=self.invoice_id).first()
        if not db_invoice:
            raise Exception('Cannot process request for an invoice that does not exist.')

        amount_in_paise = int(db_invoice.balance * 100)  # Amount in paise (Razorpay's requirement)
    
        order_data = {
            'amount': amount_in_paise,
            'currency': 'INR',  # Replace with the appropriate currency code
            'receipt': 'order_rcptid_11',
            'payment_capture': 1  # Auto-capture payments
        }
    
        order = client.order.create(data=order_data)
        return order

    def capture_order(self, order_id):
        try:
            payment = client.payment.fetch(order_id)
            if payment['status'] == 'authorized':
                client.payment.capture(order_id)
                return True
            else:
                raise Exception('Order cannot be captured.')
        except Exception as e:
            raise Exception('Order capture failed: {}'.format(str(e)))
    		
		
    def refund(self, order_id, amount):
        try:
            refund_data = {
                'amount': amount  # Amount in paise (Razorpay's requirement)
            }
            refund = client.refund.create(order_id, refund_data)
            return refund
        except Exception as e:
            raise Exception('Refund failed: {}'.format(str(e)))
    #Razorpay does not explicitly support order cancellation

@gateway_action(methods=['GET'])
def pay_invoice(request):
    invoice_id = request.query_params.get('invoice')
    try:
        invoice = Invoice.objects.get(pk=invoice_id, client=request.user.get_active_client(request=request))
    except Invoice.DoesNotExist:
        raise gateway_exceptions.GatewayException(_('Invoice {} does not exist').format(invoice_id))
    
	call_create_order = create_order()
	order_id =	 call_create_order['id']
	if order_id:
		return redirect(f"https://checkout.razorpay.com/v1/pay/{order_id}")
    
    return redirect('razorpay_payment_page')  # Replace with the URL to the Razorpay payment page.

@staff_gateway_action(
    methods=['GET'], requires_redirect=True,
    transaction_statuses=(Transaction.TRANSACTION_STATUS.PREAUTH,)
)

def capture(request):
    transaction_id = request.query_params.get('transaction')
    try:
        transaction = Transaction.objects.get(id=transaction_id)
        transaction.status = TransactionStatus.CONFIRMED
        transaction.save()
        return Response({'detail': 'Ok'})
    except Transaction.DoesNotExist:
        raise gateway_exceptions.GatewayException('Invalid transaction ID')
        
@staff_gateway_action(
    methods=['GET'], requires_redirect=True,
    transaction_statuses=(Transaction.TRANSACTION_STATUS.CONFIRMED, Transaction.TRANSACTION_STATUS.PREAUTH)
)

def refund(request):
    gateway = Gateway.objects.get(name='razorpay')
    transaction_id = request.query_params.get('transaction')
    transaction = Transaction.objects.get(id=transaction_id)
    invoice = transaction.invoice

    if transaction.status == Transaction.TRANSACTION_STATUS.CONFIRMED:
        activity_helper.start_generic_activity(
            category_name='razorpay', activity_class='razorpay payment refund',
            invoice_id=invoice.id
        )
        # Create a Razorpay refund

        # Initialize the Razorpay client
        client = razorpay.Client(auth=("rzp_test_5QkTsF3niAwffV", "xF80OdawVjiIU3IJwgEzuEn8"))

        # Amount to refund in paise
        refund_amount = int(Decimal(transaction.amount) * 100)

        # Create a Razorpay refund
        try:
            refund = client.refund.create({
                "payment_id": transaction.external_id,  # The payment ID of the original payment
                "amount": refund_amount,
                "speed": "optimum",  # Choose the speed of the refund
            })
        except Exception as e:
            activity_helper.end_activity(failed=True, details=str(e))
            raise gateway_exceptions.GatewayException('Invalid Razorpay refund action: {}'.format(str(e)))

        # Handle the refund response
        if refund.get('status') == 'processed':
            # Record refund details in your database
            refund_data = {
                'invoice': invoice.id,
                'external_id': refund.get('id'),
                'amount': str(Decimal(refund.get('amount')) / 100),  # Convert back to your currency format
                'currency': refund.get('currency'),
                'gateway': gateway.pk,
                'fee': gateway.get_fee(amount=transaction.amount),
                'date_initiated': refund.get('created_at'),
                'extra': {
                    'refundId': refund.get('id'),
                },
                'refunded_transaction': transaction.pk,
                'status': TransactionStatus.REFUNDED
            }

            transaction_serializer = AddTransactionSerializer(data=refund_data)

            try:
                with django_db_transaction.atomic():
                    transaction_serializer.is_valid(raise_exception=True)
                    new_transaction = transaction_serializer.save()

                activity_helper.end_activity()
                return Response({'detail': 'Ok'})

            except Exception as e:
                error_message = 'Failed to mark Razorpay transaction {} as refunded: {}'.format(
                    transaction.external_id, e
                )
                LOG.error(error_message)
                activity_helper.end_activity(failed=True, details=error_message)
                raise gateway_exceptions.GatewayException(
                    _('Failed to mark transaction as refunded. Check logs for more details.')
                )
        else:
            error_message = 'Failed to refund transaction. {}'.format(refund.get('error_description'))
            activity_helper.end_activity(failed=True, details=error_message)
            raise gateway_exceptions.GatewayException(error_message)
    else:
        # Handle cancellation request for when the transaction was not yet confirmed
        # This may be logged in a callback
        try:
            # Implement cancellation logic here if required
            pass
        except Exception as e:
            raise gateway_exceptions.GatewayException('Invalid Razorpay refund action: {}'.format(str(e)))
        return Response({'detail': 'Ok'})

def callback(request):
    # Parse the request body as JSON
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'detail': 'Invalid JSON payload'}, status=400)

    # Verify the Razorpay signature to ensure the request is from Razorpay
    razorpay_webhook_secret = "https://fleio_host/razorpay-webhook"  # Replace with your actual Razorpay webhook secret
    client = razorpay.Client(auth=("rzp_test_5QkTsF3niAwffV", "xF80OdawVjiIU3IJwgEzuEn8"))
    signature = request.headers.get('x-razorpay-signature')

    try:
        client.utility.verify_webhook_signature(request.body.decode(), signature, razorpay_webhook_secret)
    except ValueError:
        return JsonResponse({'detail': 'Invalid Razorpay signature'}, status=400)
		
    invoice_id = RazorpayUtils.get_invoice_id_from_external_order_id(external_order_id=order_details.get('extOrderId'))
    # Extract relevant data from the payload
    order_id = payload.get('payload').get('payment').get('entity').get('id')
    invoice_id = invoice_id 

    # Handle the different Razorpay payment statuses
    payment_status = payload.get('payload').get('payment').get('entity').get('status')
    total_amount = Decimal(payload.get('payload').get('payment').get('entity').get('amount')) / 100  # Convert back to your currency format
	
	
	
	
    if payment_status == 'captured':
        #---------
		existing_transaction = Transaction.objects.filter(
        external_id=external_id,
        gateway=gateway,
        refunded_transaction__isnull=True).first()
	
		if existing_transaction:
			# Update the transaction status and mark invoice as paid (still needs capture if automatic capture is not
			# enabled in Razorpay) if client successfully made the payment
			existing_transaction.status = RazorpayTransactionStatus.to_transaction_model_status.get(transaction_status)
			existing_transaction.save(update_fields=['status'])
			if (transaction_status == RazorpayTransactionStatus.waiting_for_confirmation or
					(transaction_status == RazorpayTransactionStatus.completed and existing_transaction.invoice and
					 existing_transaction.invoice.is_unpaid())):
				activity_helper.start_generic_activity(
					category_name='razorpay', activity_class='razorpay payment',
					invoice_id=invoice_id
				)
				invoice_add_payment(
					invoice_id=invoice_id, amount=total_amount,
					currency_code=order_details.get('currencyCode'), transaction_id=existing_transaction.id,
				)
				activity_helper.end_activity()
				return Response({'detail': 'Ok'})
			elif transaction_status == RazorpayTransactionStatus.pending:
				serializer_data = {
					'invoice': invoice_id,
					'external_id': external_id,
					'amount': total_amount,
					'currency': order_details.get('currencyCode'),
					'gateway': gateway.pk,
					'fee': gateway.get_fee(amount=decimal.Decimal(total_amount)),
					'date_initiated': order_details.get('orderCreateDate'),
					'extra': {},
					'status': RazorpayTransactionStatus.to_transaction_model_status.get(transaction_status)
				}
			add_transaction_serializer = AddTransactionSerializer(data=serializer_data)
			if add_transaction_serializer.is_valid(raise_exception=False):
				add_transaction_serializer.save()
			else:
				LOG.error('Razorpay transaction error: {}'.format(add_transaction_serializer.errors))
				raise gateway_exceptions.InvoicePaymentException('Transaction error', invoice_id=invoice_id)
			
			#--------
		return JsonResponse({'detail': 'Payment captured'}, status=200)

    elif payment_status == 'failed':
        # process refund for pre-auth transaction
        existing_transaction = Transaction.objects.filter(
            external_id=external_id,
            gateway=gateway,
            refunded_transaction__isnull=True
        ).first()
        if not existing_transaction:
            raise gateway_exceptions.GatewayException(
                'Could not process cancellation notification because there is no transaction to refund')
			new_refund_transaction = {
				'invoice': invoice_id,
				'external_id': external_id,
				'amount': str(total_amount),
				'currency': order_details.get('currencyCode'),
				'gateway': gateway.pk,
				'fee': gateway.get_fee(amount=decimal.Decimal(total_amount)),
				'date_initiated': utcnow(),
				'extra': {},
				'refunded_transaction': existing_transaction.pk,
				'status': TransactionStatus.REFUNDED
			}
			transaction_serializer = AddTransactionSerializer(data=new_refund_transaction)
			activity_helper.start_generic_activity(
				category_name='razorpay', activity_class='razorpay payment refund',
				invoice_id=existing_transaction.invoice.id
			)

			try:
				with django_db_transaction.atomic():
					transaction_serializer.is_valid(raise_exception=True)
					new_transaction = transaction_serializer.save()
					invoice_refund_payment(
						transaction_id=existing_transaction.id,
						amount=total_amount,
						to_client_credit=False,
						new_transaction_id=new_transaction.pk
					)

				activity_helper.end_activity()
				return Response({'detail': 'Ok'})

			except Exception as e:
				error_message = 'Failed to mark Payu transaction {} as refunded: {}'.format(
					existing_transaction.external_id, e
				)
				LOG.error(error_message)
				activity_helper.end_activity(failed=True, details=error_message)
				raise gateway_exceptions.GatewayException(
					_('Failed to mark transaction as refunded.')
				)
        return JsonResponse({'detail': 'Payment failed'}, status=200)

    # Add more conditions for other payment statuses as needed
    else:
        return JsonResponse({'detail': 'Unknown payment status'}, status=200)
		
		
		
