from django.conf import settings


class Conf(object):
    def __init__(self):
        self.newgateway_settings = getattr(settings, 'NEWGATEWAY_SETTINGS', {})
        self.test_mode = self.newgateway_settings.get('test_mode')
        self.secret_key = self.newgateway_settings.get('secret_key')
        self.callback_url = self.newgateway_settings.get('callback_url')

conf = Conf()
