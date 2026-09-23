"""Login to PM with a Bitrix24 account (OAuth 2.0 of a local Bitrix24 app).

The flow follows https://apidocs.bitrix24.com/settings/oauth/index.html, which
differs from a generic OAuth2 provider in three ways: the authorize page is on
the portal itself, the code is exchanged by a GET to oauth.bitrix.info (the
client secret must never be sent to the portal), and redirect_uri is not sent
at all -- Bitrix24 takes it from the app card.

Tokens are not stored: the access token is used for exactly one user.current
call and dropped. HTTP calls live here so tests can patch `requests.get`.

Identity is the Bitrix24 user ID, kept in core.Bitrix24Account. The e-mail is
only a way to find the PM user for a Bitrix24 user who is not linked yet.
"""
import logging
from urllib.parse import urlencode, urlparse

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

logger = logging.getLogger(__name__)

TIMEOUT = 10


class Bitrix24LoginDenied(Exception):
    """Login refused. str(exc) is the Russian message shown to the user."""


class Bitrix24Unavailable(Bitrix24LoginDenied):
    def __init__(self):
        super().__init__('Bitrix24 сейчас недоступен. Попробуйте позже или войдите по паролю.')


class Bitrix24PasswordRequired(Bitrix24LoginDenied):
    """The e-mail matches a PM user who has a password: they link by logging
    in with it first, then going through Bitrix24 in link mode."""

    def __init__(self):
        super().__init__(
            'В PM уже есть учётная запись с вашим e-mail. Войдите один раз по паролю — '
            'после этого PM предложит привязать Bitrix24, и дальше можно будет входить через него.'
        )


REJECTED = 'Bitrix24 не подтвердил вход. Попробуйте ещё раз.'


def is_configured() -> bool:
    return bool(
        settings.BITRIX24_PORTAL
        and settings.BITRIX24_CLIENT_ID
        and settings.BITRIX24_CLIENT_SECRET
    )


def authorize_url(state: str) -> str:
    query = urlencode({'client_id': settings.BITRIX24_CLIENT_ID, 'state': state})
    return f'https://{settings.BITRIX24_PORTAL}/oauth/authorize/?{query}'


def _get_json(url: str, params: dict) -> dict:
    host = urlparse(url).netloc
    try:
        response = requests.get(url, params=params, timeout=TIMEOUT)
    except requests.RequestException as exc:
        # Log the class only: urllib3 puts the full request URL into the
        # message, and the query string carries client_secret / access_token.
        logger.warning('Bitrix24 request to %s failed: %s', host, type(exc).__name__)
        raise Bitrix24Unavailable from None

    if response.status_code >= 500:
        logger.warning('Bitrix24 %s answered HTTP %s', host, response.status_code)
        raise Bitrix24Unavailable

    try:
        data = response.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        data = {}

    if response.status_code >= 400 or 'error' in data:
        logger.warning(
            'Bitrix24 %s rejected the request: HTTP %s, error=%s',
            host, response.status_code, data.get('error'),
        )
        raise Bitrix24LoginDenied(REJECTED)
    return data


def exchange_code(code: str) -> dict:
    """Trade the one-time code (lives 30 s) for a token on the auth server."""
    token = _get_json(
        f"{settings.BITRIX24_OAUTH_SERVER.rstrip('/')}/oauth/token/",
        {
            'grant_type': 'authorization_code',
            'client_id': settings.BITRIX24_CLIENT_ID,
            'client_secret': settings.BITRIX24_CLIENT_SECRET,
            'code': code,
        },
    )
    endpoint = urlparse(token.get('client_endpoint') or '')
    # The access token is about to be sent to client_endpoint, so it has to be
    # our portal and nothing else.
    if (
        not token.get('access_token')
        or endpoint.scheme != 'https'
        or endpoint.netloc.lower() != settings.BITRIX24_PORTAL.lower()
    ):
        logger.warning('Bitrix24 token for an unexpected endpoint: %s', endpoint.netloc)
        raise Bitrix24LoginDenied(REJECTED)
    return token


def fetch_current_user(client_endpoint: str, access_token: str) -> dict:
    data = _get_json(f"{client_endpoint.rstrip('/')}/user.current", {'auth': access_token})
    profile = data.get('result')
    if not isinstance(profile, dict):
        raise Bitrix24LoginDenied(REJECTED)
    return profile


def _is_employee(profile: dict) -> bool:
    # USER_TYPE is 'employee' for intranet staff; extranet guests, e-mail
    # users and bots get other values. On-premise portals older than the
    # field fall back to "belongs to a department".
    if 'USER_TYPE' in profile:
        return profile['USER_TYPE'] == 'employee'
    return bool(profile.get('UF_DEPARTMENT'))


def _free_username(email: str, bitrix_id) -> str:
    # username is varchar(150), an e-mail may be up to 254.
    User = get_user_model()
    username = email[:150]
    if User.objects.filter(username__iexact=username).exists():
        suffix = f'.b24-{bitrix_id}'
        username = email[:150 - len(suffix)] + suffix
    return username


LINKED_ELSEWHERE = 'Этот аккаунт Bitrix24 уже привязан к другому пользователю PM. Обратитесь к администратору.'


def _deny(bitrix_id, reason: str, message: str):
    logger.info('Bitrix24 login of user %s refused: %s', bitrix_id, reason)
    raise Bitrix24LoginDenied(message)


def _find_account(bitrix_id: int):
    from core.models import Bitrix24Account

    return Bitrix24Account.objects.select_related('user').filter(bitrix_user_id=bitrix_id).first()


def link(user, bitrix_id: int):
    """Tie `user` to `bitrix_id`. Idempotent; refuses to re-point either side."""
    from core.models import Bitrix24Account

    account = _find_account(bitrix_id)
    if account is not None:
        if account.user_id != user.pk:
            _deny(bitrix_id, f'already linked to PM user {account.user_id}', LINKED_ELSEWHERE)
        return user
    if Bitrix24Account.objects.filter(user=user).exists():
        _deny(bitrix_id, f'PM user {user.pk} is linked to another Bitrix24 user',
              'К вашей учётной записи PM уже привязан другой аккаунт Bitrix24. Обратитесь к администратору.')
    try:
        # Savepoint: a lost race must not poison the caller's transaction.
        with transaction.atomic():
            Bitrix24Account.objects.create(user=user, bitrix_user_id=bitrix_id)
    except IntegrityError:
        # Someone linked either side between the checks and the insert.
        account = _find_account(bitrix_id)
        if account is not None and account.user_id == user.pk:
            return user
        _deny(bitrix_id, 'lost a linking race', LINKED_ELSEWHERE)
    logger.info('Bitrix24 user %s linked to PM user %s', bitrix_id, user.pk)
    return user


def _create_user(profile: dict, email: str, bitrix_id: int):
    User = get_user_model()
    try:
        with transaction.atomic():
            user = User(
                username=_free_username(email, bitrix_id),
                email=email,
                first_name=(profile.get('NAME') or '')[:150],
                last_name=(profile.get('LAST_NAME') or '')[:150],
            )
            user.set_unusable_password()
            user.save()
            link(user, bitrix_id)
    except (IntegrityError, Bitrix24LoginDenied):
        # Two first logins of the same employee at once: the other one won,
        # this one's user is rolled back, and both end up in the same account.
        account = _find_account(bitrix_id)
        if account is None:
            raise
        return account.user
    logger.info('Bitrix24 user %s created PM user %s', bitrix_id, user.pk)
    return user


def resolve_user(profile: dict, link_to=None):
    """Map a Bitrix24 profile to a PM user.

    link_to=None is a login: by linked ID, else by e-mail, else a new user if
    the policy allows. link_to=<user> is the logged-in user linking their
    account: it only ever links that user and never switches to another one.
    """
    User = get_user_model()
    raw_id = profile.get('ID')
    try:
        # user.current returns the ID as a string.
        bitrix_id = int(raw_id)
    except (TypeError, ValueError):
        bitrix_id = 0
    if bitrix_id <= 0:
        _deny(raw_id, 'no usable ID', REJECTED)

    if profile.get('ACTIVE') not in (True, 'Y'):
        _deny(bitrix_id, 'inactive in Bitrix24', 'Ваша учётная запись в Bitrix24 отключена.')
    if not _is_employee(profile):
        _deny(bitrix_id, 'not an employee', 'Вход через Bitrix24 доступен только сотрудникам компании.')

    if link_to is not None:
        return link(link_to, bitrix_id)

    account = _find_account(bitrix_id)
    if account is not None:
        # The ID cannot be edited by the employee, so a linked account -- staff
        # included -- is trusted regardless of what the e-mail says now.
        if not account.user.is_active:
            _deny(bitrix_id, 'PM user is inactive', 'Ваша учётная запись в PM отключена.')
        return account.user

    email = (profile.get('EMAIL') or '').strip().lower()
    if not email:
        _deny(bitrix_id, 'no e-mail', 'В профиле Bitrix24 не указан e-mail, войти по нему нельзя.')

    matches = list(User.objects.filter(email__iexact=email)[:2])
    if len(matches) > 1:
        _deny(bitrix_id, 'e-mail matches several PM users',
              'Этот e-mail указан у нескольких пользователей PM. Обратитесь к администратору.')

    if matches:
        user = matches[0]
        if not user.is_active:
            _deny(bitrix_id, 'PM user is inactive', 'Ваша учётная запись в PM отключена.')
        # A Bitrix24 employee can edit the e-mail in their own profile, so an
        # e-mail match alone links only an account that has never had any
        # other way in: one Bitrix24 created, with no password, not staff.
        # Anyone else proves the account is theirs with the password first.
        if user.is_staff or user.is_superuser or user.has_usable_password():
            logger.info('Bitrix24 user %s matches PM user %s by e-mail: password first',
                        bitrix_id, user.pk)
            raise Bitrix24PasswordRequired
        return link(user, bitrix_id)

    # Policy: while PM is young every active Bitrix24 employee gets in, and a
    # PM user is created on first login with full access (PM has no roles).
    # Expected to narrow later -- set BITRIX24_AUTO_CREATE_USERS=false to let
    # in only people who already have a PM account.
    if not settings.BITRIX24_AUTO_CREATE_USERS:
        _deny(bitrix_id, 'no PM user and auto-create is off',
              'У вас нет учётной записи в PM. Обратитесь к администратору.')
    return _create_user(profile, email, bitrix_id)


def user_from_code(code: str, link_to=None):
    token = exchange_code(code)
    profile = fetch_current_user(token['client_endpoint'], token['access_token'])
    return resolve_user(profile, link_to=link_to)

