from django.utils.translation import gettext_lazy as _
from django.apps import AppConfig


class PayUConfig(AppConfig):
    name = "fleio.billing.gateways.payu"
    verbose_name = _("Razorpay")
    fleio_module_type = 'payment_gateway'
    module_settings = {'capabilities': {
        'can_process_payments': True,
        'returns_fee_information': False,
        'supports_recurring_payments': False,
    }}
