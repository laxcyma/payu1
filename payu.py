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
from .utils import PayUTransactionStatus
from .utils import PayUUtils

LOG = logging.getLogger(__name__)


class PayUClient:
    def payment_panel(request):
        if request.method == "POST":
            name = request.POST.get('name','')
            payamt = int(request.POST.get('payamt','')) * 100        
            client = razorpay.Client(auth=('rzp_test_5QkTsF3niAwffV','xF80OdawVjiIU3IJwgEzuEn8'))
            response_payment = client.order.create(dict(amount=payamt,currency='INR'))
            
            order_id = response_payment['id']
            order_status = response_payment['status']
            if order_status == 'created':
                payrazor = razorpayment(name=name,amount=payamt,order_id=order_id)
                payrazor.save()
                response_payment['name'] = name
                print(response_payment)
                context = {
                    'payment':response_payment,
                    'key_id':'rzp_test_5QkTsF3niAwffV'
    
                }
                return render(request, 'templates/index.html', context)
        # Create a Razorpay Order
        return render(request, 'templates/index.html')
    
# example =  {'id': 'order_Mjd5DMLJlcw7GZ', 'entity': 'order', 'amount': 10000, 'amount_paid': 0, 'amount_due': 10000, 'currency': 'INR', 'receipt': None, 'offer_id': None, 'status': 'created', 'attempts': 0, 'notes': [], 'created_at': 1696313248}

@csrf_exempt
def payment_status(request):
    if request.method == 'POST':
        response = request.POST
        print(response)
        params_dict = {
            'razorpay_order_id': response.get('razorpay_order_id'),
            'razorpay_payment_id': response.get('razorpay_payment_id'),
            'razorpay_signature': response.get('razorpay_signature')
        }

        client = razorpay.Client(auth=('rzp_test_5QkTsF3niAwffV', 'xF80OdawVjiIU3IJwgEzuEn8'))

        try:
            status = client.utility.verify_payment_signature(params_dict)
            if status:
                payrazor = razorpayment.objects.get(order_id=response.get('razorpay_order_id'))
                payrazor.razorpay_payment_id = response.get('razorpay_payment_id')
                payrazor.paid = True
                payrazor.save()
                return render(request, 'templates/paymentsuccess.html')
            else:
                return render(request, 'templates/paymentfail.html')
        except Exception as e:
            print(str(e))
            return render(request, 'templates/paymentfail.html')
    else:
        return HttpResponse("Invalid request method")
