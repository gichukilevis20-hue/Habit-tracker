import base64
import json
from decimal import Decimal
from urllib import error, parse, request

from django.conf import settings
from django.utils import timezone


class DarajaError(Exception):
    pass


PLACEHOLDER_MPESA_VALUES = {
    '',
    'n/a',
    'na',
    'none',
    'null',
    'changeme',
    'your-shortcode',
    'your-passkey',
    'your-consumer-key',
    'your-consumer-secret',
    'your-public-url',
}


def _clean_mpesa_setting(value):
    cleaned_value = str(value or '').strip()
    if cleaned_value.lower() in PLACEHOLDER_MPESA_VALUES:
        return ''
    return cleaned_value


def _get_mpesa_setting(name):
    return _clean_mpesa_setting(getattr(settings, name, ''))


def daraja_configuration_errors():
    issues = []

    consumer_key = _get_mpesa_setting('MPESA_CONSUMER_KEY')
    consumer_secret = _get_mpesa_setting('MPESA_CONSUMER_SECRET')
    shortcode = _get_mpesa_setting('MPESA_SHORTCODE')
    passkey = _get_mpesa_setting('MPESA_PASSKEY')
    callback_url = _get_mpesa_setting('MPESA_CALLBACK_URL')

    if not consumer_key:
        issues.append('MPESA_CONSUMER_KEY is missing.')
    if not consumer_secret:
        issues.append('MPESA_CONSUMER_SECRET is missing.')
    if not shortcode:
        issues.append('MPESA_SHORTCODE is missing.')
    elif not shortcode.isdigit():
        issues.append('MPESA_SHORTCODE must be numeric.')
    if not passkey:
        issues.append('MPESA_PASSKEY is missing.')
    if not callback_url:
        issues.append('MPESA_CALLBACK_URL is missing. Set it to your public HTTPS /mpesa/callback/ URL.')
    elif 'example.com' in callback_url.lower():
        issues.append('MPESA_CALLBACK_URL still points to example.com. Replace it with your public HTTPS /mpesa/callback/ URL.')
    elif not callback_url.startswith('https://'):
        issues.append('MPESA_CALLBACK_URL must use HTTPS so Daraja can reach it.')

    return issues


def daraja_is_configured():
    return not daraja_configuration_errors()


def _daraja_base_url():
    environment = settings.MPESA_ENVIRONMENT.lower()
    if environment == 'live':
        return 'https://api.safaricom.co.ke'
    return 'https://sandbox.safaricom.co.ke'


def _request_json(url, headers=None, data=None):
    req = request.Request(url, headers=headers or {}, data=data)
    with request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode('utf-8'))


def _access_token():
    consumer_key = _get_mpesa_setting('MPESA_CONSUMER_KEY')
    consumer_secret = _get_mpesa_setting('MPESA_CONSUMER_SECRET')
    credentials = f"{consumer_key}:{consumer_secret}".encode('utf-8')
    token = base64.b64encode(credentials).decode('utf-8')
    url = f"{_daraja_base_url()}/oauth/v1/generate?grant_type=client_credentials"
    headers = {'Authorization': f'Basic {token}'}
    payload = _request_json(url, headers=headers)
    access_token = payload.get('access_token')
    if not access_token:
        raise DarajaError('Daraja access token was not returned.')
    return access_token


def _stk_password(timestamp):
    shortcode = _get_mpesa_setting('MPESA_SHORTCODE')
    passkey = _get_mpesa_setting('MPESA_PASSKEY')
    raw_password = f"{shortcode}{passkey}{timestamp}".encode('utf-8')
    return base64.b64encode(raw_password).decode('utf-8')


def initiate_mpesa_stk_push(phone_number, amount, account_reference, description):
    config_issues = daraja_configuration_errors()
    if config_issues:
        raise DarajaError(' '.join(config_issues))

    normalized_phone_number = ''.join(character for character in str(phone_number or '') if character.isdigit())
    if len(normalized_phone_number) != 12 or not normalized_phone_number.startswith('254'):
        raise DarajaError('Use a valid Kenyan M-Pesa phone number in 2547XXXXXXXX format.')

    timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
    endpoint = f"{_daraja_base_url()}/mpesa/stkpush/v1/processrequest"
    numeric_amount = max(1, int(Decimal(amount)))
    shortcode = _get_mpesa_setting('MPESA_SHORTCODE')
    payload = {
        'BusinessShortCode': shortcode,
        'Password': _stk_password(timestamp),
        'Timestamp': timestamp,
        'TransactionType': settings.MPESA_TRANSACTION_TYPE,
        'Amount': numeric_amount,
        'PartyA': normalized_phone_number,
        'PartyB': _get_mpesa_setting('MPESA_PARTYB') or shortcode,
        'PhoneNumber': normalized_phone_number,
        'CallBackURL': _get_mpesa_setting('MPESA_CALLBACK_URL'),
        'AccountReference': account_reference[:12],
        'TransactionDesc': description[:50],
    }
    headers = {
        'Authorization': f'Bearer {_access_token()}',
        'Content-Type': 'application/json',
    }

    try:
        encoded_payload = json.dumps(payload).encode('utf-8')
        return _request_json(endpoint, headers=headers, data=encoded_payload)
    except error.HTTPError as exc:
        details = exc.read().decode('utf-8', errors='ignore')
        raise DarajaError(f'Daraja request failed: {details or exc.reason}') from exc
    except error.URLError as exc:
        raise DarajaError(f'Unable to reach Daraja: {exc.reason}') from exc


def extract_stk_callback_details(payload):
    callback = payload.get('Body', {}).get('stkCallback', {})
    metadata_items = callback.get('CallbackMetadata', {}).get('Item', [])
    metadata = {}

    for item in metadata_items:
        name = item.get('Name')
        if name:
            metadata[name] = item.get('Value')

    return {
        'merchant_request_id': callback.get('MerchantRequestID'),
        'checkout_request_id': callback.get('CheckoutRequestID'),
        'result_code': callback.get('ResultCode'),
        'result_desc': callback.get('ResultDesc'),
        'metadata': metadata,
    }


def build_bitcoin_uri(wallet_address, amount):
    params = parse.urlencode({'amount': amount})
    return f"bitcoin:{wallet_address}?{params}"
