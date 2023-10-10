from django.conf import settings


class Conf(object):
    def __init__(self):
        self.payu_settings = getattr(settings, 'PAYU_SETTINGS', {})
        self.orders_url = self.payu_settings.get('orders_url')
        self.authorization_url = self.payu_settings.get('authorization_url')
        self.merchant_pos_id = self.payu_settings.get('merchant_pos_id')
        self.client_id = self.payu_settings.get('client_id')
        self.client_secret = self.payu_settings.get('client_secret')
        self.notify_url = self.payu_settings.get('notify_url')
        self.second_key = self.payu_settings.get('second_key')
        self.timeout = self.payu_settings.get('timeout', 60)


conf = Conf()
