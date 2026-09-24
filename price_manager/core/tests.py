import ast
from datetime import timedelta
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.db import connection
from django.shortcuts import resolve_url
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from price_manager.celery import app as celery_app
from price_manager.settings import celery as celery_settings

from .models import Bitrix24Account, PersistentNotification, TaskRunHistory
from .task_runner import execute_locked_task


def _make_history(task_name: str) -> TaskRunHistory:
    now = timezone.now()
    return TaskRunHistory.objects.create(
        task_name=task_name,
        status="success",
        started_at=now,
        finished_at=now,
        duration_ms=0,
    )


class ExecuteLockedTaskAtomicTests(TransactionTestCase):
    """The `atomic` flag must control the transaction and nothing else.

    Uses TransactionTestCase because django.test.TestCase wraps every test in
    its own transaction, which would make `connection.in_atomic_block` True
    inside the runner no matter what the flag does.
    """

    def setUp(self):
        cache.clear()

    def test_runner_holds_a_transaction_by_default(self):
        seen = []

        execute_locked_task(
            task_name="test.atomic_default",
            lock_ttl=60,
            runner=lambda: seen.append(connection.in_atomic_block),
        )

        self.assertEqual(seen, [True])

    def test_runner_holds_no_transaction_when_atomic_false(self):
        seen = []

        execute_locked_task(
            task_name="test.atomic_false",
            lock_ttl=60,
            runner=lambda: seen.append(connection.in_atomic_block),
            atomic=False,
        )

        self.assertEqual(seen, [False])

    def test_atomic_false_still_takes_the_lock(self):
        # Hold the lock the way a concurrent worker would, then confirm a
        # non-transactional run is still gated by it.
        lock_key = "task-lock:test.lock_kept"
        self.assertTrue(cache.add(lock_key, "held-elsewhere", 60))
        seen = []

        payload = execute_locked_task(
            task_name="test.lock_kept",
            lock_ttl=60,
            runner=lambda: seen.append(1),
            atomic=False,
        )

        self.assertEqual(seen, [])
        self.assertEqual(payload["status"], "skipped")
        self.assertEqual(payload["reason"], "lock_exists")
        # The loser must not clear the holder's lock.
        self.assertEqual(cache.get(lock_key), "held-elsewhere")
        cache.delete(lock_key)

    def test_atomic_false_keeps_writes_made_before_an_error(self):
        def _runner():
            _make_history("test.partial")
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            execute_locked_task(
                task_name="test.rollback",
                lock_ttl=60,
                runner=_runner,
                atomic=False,
            )

        self.assertTrue(TaskRunHistory.objects.filter(task_name="test.partial").exists())
        self.assertFalse(cache.get("task-lock:test.rollback"))

    def test_default_still_rolls_back_writes_made_before_an_error(self):
        def _runner():
            _make_history("test.partial")
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            execute_locked_task(
                task_name="test.rollback",
                lock_ttl=60,
                runner=_runner,
            )

        self.assertFalse(TaskRunHistory.objects.filter(task_name="test.partial").exists())
        # The error-path history row is written outside the runner's transaction,
        # so it survives the rollback.
        self.assertTrue(TaskRunHistory.objects.filter(task_name="test.rollback", status="error").exists())


class CeleryBeatScheduleTests(SimpleTestCase):
    """The two ways a CELERY_BEAT_SCHEDULE entry silently stops running.

    Neither raises anywhere: beat just schedules less than the file appears to
    say, and the only symptom is a task that quietly stops showing up in
    TaskRunHistory. Commit e0a5070 hit the first one -- it added a
    delete_outdated_logs entry under the key 'update-logs' that was already
    taken, so main_product_manager.update_logs stopped being scheduled while
    the file still listed it.
    """

    def test_no_entry_is_overwritten_by_a_duplicate_key(self):
        # Has to read the source, not settings.CELERY_BEAT_SCHEDULE. By the time
        # the module is imported the duplicate is already gone: the dict just
        # holds one fewer entry, every remaining key is distinct, and nothing
        # runtime-visible says a task went missing.
        tree = ast.parse(Path(celery_settings.__file__).read_text(encoding='utf-8'))
        literal = next(
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(getattr(t, 'id', None) == 'CELERY_BEAT_SCHEDULE' for t in node.targets)
        )
        keys = [key.value for key in literal.keys]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        self.assertEqual(duplicates, [], f'CELERY_BEAT_SCHEDULE keys repeated: {duplicates}')
        self.assertEqual(len(keys), len(settings.CELERY_BEAT_SCHEDULE))

    def test_every_scheduled_task_is_registered(self):
        # autodiscover_tasks() is lazy; nothing has forced the app tasks modules
        # to import in a test process.
        celery_app.loader.import_default_modules()
        for key, entry in settings.CELERY_BEAT_SCHEDULE.items():
            with self.subTest(entry=key):
                self.assertIn(entry['task'], celery_app.tasks)


BITRIX24_SETTINGS = dict(
    BITRIX24_PORTAL='company.bitrix24.kz',
    BITRIX24_CLIENT_ID='local.app.1',
    BITRIX24_CLIENT_SECRET='s3cret',
    BITRIX24_OAUTH_SERVER='https://oauth.bitrix.info',
    BITRIX24_AUTO_CREATE_USERS=True,
)


def _bitrix24_profile(**overrides):
    profile = {
        'ID': '42',
        'ACTIVE': True,
        'USER_TYPE': 'employee',
        'UF_DEPARTMENT': [1],
        'NAME': 'Иван',
        'LAST_NAME': 'Петров',
        'EMAIL': 'ivan@example.com',
    }
    profile.update(overrides)
    return profile


def _json_response(payload, status=200):
    response = mock.Mock(status_code=status)
    response.json.return_value = payload
    return response


def _fake_bitrix24(profile=None, token=None):
    """side_effect for requests.get: the token server, then user.current."""
    token = token or {
        'access_token': 'tok',
        'client_endpoint': 'https://company.bitrix24.kz/rest/',
    }

    def get(url, params=None, timeout=None):
        if url == 'https://oauth.bitrix.info/oauth/token/':
            return _json_response(token)
        if url == 'https://company.bitrix24.kz/rest/user.current':
            return _json_response({'result': profile or _bitrix24_profile()})
        raise AssertionError(f'unexpected request to {url}')

    return get


@override_settings(**BITRIX24_SETTINGS)
class Bitrix24LoginTests(TestCase):
    """core/bitrix24.py + the two views. requests.get is always patched."""

    def start_login(self, next_url=None):
        """Walk the first leg and return the state PM put into the session."""
        url = reverse('bitrix24-login')
        if next_url is not None:
            url += '?' + urlencode({'next': next_url})
        self.client.get(url)
        return self.client.session['bitrix24_oauth_state']

    def callback(self, state, code='the-code', **patch_kwargs):
        with mock.patch('core.bitrix24.requests.get', **patch_kwargs) as get:
            response = self.client.get(
                reverse('bitrix24-callback'), {'code': code, 'state': state}
            )
        return response, get

    def logged_in_user_id(self):
        return self.client.session.get('_auth_user_id')

    def error_messages(self, response):
        return [str(m) for m in get_messages(response.wsgi_request)]

    # --- first leg ---------------------------------------------------------

    def test_login_redirects_to_portal_with_state(self):
        response = self.client.get(reverse('bitrix24-login'))
        self.assertEqual(response.status_code, 302)
        location = urlparse(response['Location'])
        self.assertEqual(
            (location.scheme, location.netloc, location.path),
            ('https', 'company.bitrix24.kz', '/oauth/authorize/'),
        )
        query = parse_qs(location.query)
        self.assertEqual(query['client_id'], ['local.app.1'])
        self.assertEqual(query['state'], [self.client.session['bitrix24_oauth_state']])
        # redirect_uri comes from the app card; client_secret never leaves PM.
        self.assertNotIn('redirect_uri', query)
        self.assertNotIn('s3cret', response['Location'])

    @override_settings(BITRIX24_CLIENT_SECRET='')
    def test_both_views_404_when_not_configured(self):
        self.assertEqual(self.client.get(reverse('bitrix24-login')).status_code, 404)
        self.assertEqual(self.client.get(reverse('bitrix24-callback')).status_code, 404)

    def test_anonymous_requests_pass_the_login_gate(self):
        # LoginRequiredMiddleware would answer both with a redirect to
        # accounts/login/?next=...; getting the views' own answers proves the
        # LOGIN_EXEMPT_URLS entries work.
        response = self.client.get(reverse('bitrix24-login'))
        self.assertEqual(urlparse(response['Location']).netloc, 'company.bitrix24.kz')
        self.assertEqual(self.client.post(reverse('bitrix24-callback')).status_code, 200)

    # --- callback: request integrity ---------------------------------------

    def test_callback_without_login_leg_is_refused_before_any_request(self):
        response, get = self.callback(state='forged', side_effect=_fake_bitrix24())
        self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)
        get.assert_not_called()
        self.assertIsNone(self.logged_in_user_id())

    def test_callback_with_wrong_state_is_refused(self):
        self.start_login()
        _, get = self.callback(state='not-the-one', side_effect=_fake_bitrix24())
        get.assert_not_called()
        self.assertIsNone(self.logged_in_user_id())

    def test_state_is_single_use(self):
        state = self.start_login()
        self.callback(state, side_effect=_fake_bitrix24())
        self.client.logout()
        _, get = self.callback(state, side_effect=_fake_bitrix24())
        get.assert_not_called()

    def test_non_ascii_state_is_refused_not_a_500(self):
        self.start_login()
        response, _ = self.callback(state='состояние', side_effect=_fake_bitrix24())
        self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)

    def test_token_for_another_portal_is_refused(self):
        state = self.start_login()
        token = {'access_token': 'tok', 'client_endpoint': 'https://evil.bitrix24.kz/rest/'}
        _, get = self.callback(state, side_effect=_fake_bitrix24(token=token))
        self.assertEqual(get.call_count, 1)  # user.current is never called
        self.assertIsNone(self.logged_in_user_id())

    def test_token_exchange_goes_to_the_auth_server_not_the_portal(self):
        state = self.start_login()
        _, get = self.callback(state, side_effect=_fake_bitrix24())
        url, = get.call_args_list[0].args
        params = get.call_args_list[0].kwargs['params']
        self.assertEqual(url, 'https://oauth.bitrix.info/oauth/token/')
        self.assertEqual(params['client_secret'], 's3cret')
        self.assertEqual(params['code'], 'the-code')
        for call in get.call_args_list[1:]:
            self.assertNotIn('s3cret', str(call))

    def test_rejected_code_shows_a_message(self):
        state = self.start_login()
        response, _ = self.callback(
            state, return_value=_json_response({'error': 'invalid_grant'}, status=400)
        )
        self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)
        self.assertIn('Bitrix24 не подтвердил вход', ' '.join(self.error_messages(response)))

    def test_network_failure_shows_unavailable_and_does_not_log_the_secret(self):
        state = self.start_login()
        error = requests.ConnectionError(
            'Max retries exceeded with url: /oauth/token/?client_secret=s3cret'
        )
        with self.assertLogs('core.bitrix24', level='WARNING') as logs:
            response, _ = self.callback(state, side_effect=error)
        self.assertIn('недоступен', ' '.join(self.error_messages(response)))
        self.assertNotIn('s3cret', '\n'.join(logs.output))

    def test_install_post_is_acknowledged(self):
        response = self.client.post(reverse('bitrix24-callback'), {'auth[access_token]': 'x'})
        self.assertEqual(response.status_code, 200)

    # --- callback: who gets in ---------------------------------------------

    def test_new_employee_gets_a_pm_user_and_is_logged_in(self):
        state = self.start_login()
        response, _ = self.callback(state, side_effect=_fake_bitrix24())
        user = User.objects.get(email='ivan@example.com')
        self.assertEqual(self.logged_in_user_id(), str(user.pk))
        self.assertEqual(user.username, 'ivan@example.com')
        self.assertEqual((user.first_name, user.last_name), ('Иван', 'Петров'))
        self.assertFalse(user.has_usable_password())
        self.assertFalse(user.is_staff)
        self.assertRedirects(
            response, resolve_url(settings.LOGIN_REDIRECT_URL), fetch_redirect_response=False
        )

    def test_existing_user_is_matched_by_email_ignoring_case(self):
        # No usable password: a user Bitrix24 itself created before IDs were stored.
        existing = User.objects.create_user('ivan', email='Ivan@Example.com')
        state = self.start_login()
        self.callback(state, side_effect=_fake_bitrix24())
        self.assertEqual(self.logged_in_user_id(), str(existing.pk))
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(existing.bitrix24_account.bitrix_user_id, 42)

    def test_new_user_is_linked_by_id(self):
        state = self.start_login()
        self.callback(state, side_effect=_fake_bitrix24())
        account = Bitrix24Account.objects.get()
        self.assertEqual((account.bitrix_user_id, account.user.email), (42, 'ivan@example.com'))

    def test_email_match_with_a_password_asks_for_the_password_first(self):
        User.objects.create_user('ivan', email='ivan@example.com', password='x')
        state = self.start_login(next_url='/shopping-tabs/')
        response, _ = self.callback(state, side_effect=_fake_bitrix24())
        self.assertIsNone(self.logged_in_user_id())
        self.assertFalse(Bitrix24Account.objects.exists())
        self.assertIn('Войдите один раз по паролю', self.error_messages(response)[0])

        # Login page, whose next is the link page, whose next is the original page.
        location = urlparse(response['Location'])
        self.assertEqual(location.path, reverse('login'))
        link_next = urlparse(parse_qs(location.query)['next'][0])
        self.assertEqual(link_next.path, reverse('bitrix24-link'))
        self.assertEqual(parse_qs(link_next.query)['next'], ['/shopping-tabs/'])

        # The password login then really lands on the link page -- the link is
        # offered even with BITRIX24_LINK_REQUIRED off (the default here).
        login_response = self.client.post(
            response['Location'], {'username': 'ivan', 'password': 'x'}
        )
        self.assertRedirects(
            login_response, parse_qs(location.query)['next'][0], fetch_redirect_response=False
        )
        self.assertContains(self.client.get(login_response['Location']), 'Привязать Bitrix24')

    # --- callback: linked by ID --------------------------------------------

    def link(self, user, bitrix_id=42):
        return Bitrix24Account.objects.create(user=user, bitrix_user_id=bitrix_id)

    def test_linked_id_wins_over_a_changed_email(self):
        linked = User.objects.create_user('ivan', email='ivan@example.com', password='x')
        User.objects.create_user('colleague', email='colleague@example.com')
        self.link(linked)
        state = self.start_login()
        self.callback(state, side_effect=_fake_bitrix24(
            profile=_bitrix24_profile(EMAIL='colleague@example.com')
        ))
        self.assertEqual(self.logged_in_user_id(), str(linked.pk))

    def test_linked_id_lets_staff_in_and_needs_no_email(self):
        admin = User.objects.create_user('boss', email='boss@example.com', password='x', is_staff=True)
        self.link(admin)
        state = self.start_login()
        self.callback(state, side_effect=_fake_bitrix24(profile=_bitrix24_profile(EMAIL='')))
        self.assertEqual(self.logged_in_user_id(), str(admin.pk))

    def test_linked_but_inactive_pm_user_is_refused(self):
        self.link(User.objects.create_user('ivan', email='ivan@example.com', is_active=False))
        state = self.start_login()
        self.callback(state, side_effect=_fake_bitrix24())
        self.assertIsNone(self.logged_in_user_id())

    def test_linked_but_inactive_in_bitrix24_is_refused(self):
        self.link(User.objects.create_user('ivan', email='ivan@example.com'))
        state = self.start_login()
        self.callback(state, side_effect=_fake_bitrix24(profile=_bitrix24_profile(ACTIVE=False)))
        self.assertIsNone(self.logged_in_user_id())

    def test_unusable_id_is_refused(self):
        for bad_id in ('', 'abc', '0', None):
            with self.subTest(bad_id=bad_id):
                state = self.start_login()
                self.callback(state, side_effect=_fake_bitrix24(profile=_bitrix24_profile(ID=bad_id)))
                self.assertIsNone(self.logged_in_user_id())
                self.assertEqual(User.objects.count(), 0)

    # --- callback: link mode (already logged in) ---------------------------

    def test_logged_in_user_links_their_account(self):
        user = User.objects.create_user('ivan', email='other@example.com', password='x')
        self.client.force_login(user)
        state = self.start_login(next_url='/shopping-tabs/')
        response, _ = self.callback(state, side_effect=_fake_bitrix24())
        self.assertRedirects(response, '/shopping-tabs/', fetch_redirect_response=False)
        self.assertEqual(self.logged_in_user_id(), str(user.pk))
        self.assertEqual(user.bitrix24_account.bitrix_user_id, 42)
        # No new user, even though the e-mails differ.
        self.assertEqual(User.objects.count(), 1)

    def test_link_mode_never_switches_user(self):
        owner = User.objects.create_user('owner', email='ivan@example.com')
        self.link(owner)
        user = User.objects.create_user('ivan', password='x')
        self.client.force_login(user)
        state = self.start_login()
        response, _ = self.callback(state, side_effect=_fake_bitrix24())
        self.assertRedirects(response, reverse('bitrix24-link'), fetch_redirect_response=False)
        self.assertEqual(self.logged_in_user_id(), str(user.pk))
        self.assertFalse(Bitrix24Account.objects.filter(user=user).exists())

    def test_link_mode_refuses_a_second_bitrix24_account(self):
        user = User.objects.create_user('ivan', password='x')
        self.link(user, bitrix_id=7)
        self.client.force_login(user)
        state = self.start_login()
        self.callback(state, side_effect=_fake_bitrix24())
        self.assertEqual(user.bitrix24_account.bitrix_user_id, 7)
        self.assertFalse(Bitrix24Account.objects.filter(bitrix_user_id=42).exists())

    def test_relinking_the_same_account_is_a_no_op(self):
        user = User.objects.create_user('ivan', password='x')
        self.link(user)
        self.client.force_login(user)
        state = self.start_login()
        response, _ = self.callback(state, side_effect=_fake_bitrix24())
        self.assertRedirects(
            response, resolve_url(settings.LOGIN_REDIRECT_URL), fetch_redirect_response=False
        )
        self.assertEqual(Bitrix24Account.objects.count(), 1)

    def test_safe_next_is_honoured_and_foreign_next_is_dropped(self):
        state = self.start_login(next_url='/shopping-tabs/')
        response, _ = self.callback(state, side_effect=_fake_bitrix24())
        self.assertRedirects(response, '/shopping-tabs/', fetch_redirect_response=False)

        self.client.logout()
        state = self.start_login(next_url='https://evil.example/')
        response, _ = self.callback(state, side_effect=_fake_bitrix24())
        self.assertRedirects(
            response, resolve_url(settings.LOGIN_REDIRECT_URL), fetch_redirect_response=False
        )

    def test_refusals(self):
        old_box = _bitrix24_profile(UF_DEPARTMENT=[])
        del old_box['USER_TYPE']
        cases = {
            'inactive in Bitrix24': _bitrix24_profile(ACTIVE=False),
            'extranet guest': _bitrix24_profile(USER_TYPE='extranet'),
            'no department on an old box': old_box,
            'blank e-mail': _bitrix24_profile(EMAIL=''),
        }
        for label, profile in cases.items():
            with self.subTest(label):
                state = self.start_login()
                response, _ = self.callback(state, side_effect=_fake_bitrix24(profile=profile))
                self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)
                self.assertIsNone(self.logged_in_user_id())
                self.assertEqual(User.objects.count(), 0)
                self.assertTrue(self.error_messages(response))

    def test_ambiguous_email_is_refused(self):
        User.objects.create_user('a', email='ivan@example.com')
        User.objects.create_user('b', email='IVAN@example.com')
        state = self.start_login()
        self.callback(state, side_effect=_fake_bitrix24())
        self.assertIsNone(self.logged_in_user_id())

    def test_email_match_never_hands_over_an_admin_account(self):
        for flags in ({'is_staff': True}, {'is_superuser': True}):
            with self.subTest(**flags):
                User.objects.all().delete()
                User.objects.create_user('admin', email='ivan@example.com', **flags)
                state = self.start_login()
                self.callback(state, side_effect=_fake_bitrix24())
                self.assertIsNone(self.logged_in_user_id())

    def test_inactive_pm_user_is_refused(self):
        User.objects.create_user('ivan', email='ivan@example.com', is_active=False)
        state = self.start_login()
        self.callback(state, side_effect=_fake_bitrix24())
        self.assertIsNone(self.logged_in_user_id())

    @override_settings(BITRIX24_AUTO_CREATE_USERS=False)
    def test_closed_policy_lets_in_only_existing_users(self):
        state = self.start_login()
        self.callback(state, side_effect=_fake_bitrix24())
        self.assertIsNone(self.logged_in_user_id())
        self.assertEqual(User.objects.count(), 0)

        existing = User.objects.create_user('ivan', email='ivan@example.com')
        state = self.start_login()
        self.callback(state, side_effect=_fake_bitrix24())
        self.assertEqual(self.logged_in_user_id(), str(existing.pk))

    def test_username_collision_gets_a_suffix(self):
        User.objects.create_user('ivan@example.com', email='other@example.com')
        state = self.start_login()
        self.callback(state, side_effect=_fake_bitrix24())
        user = User.objects.get(email='ivan@example.com')
        self.assertEqual(user.username, 'ivan@example.com.b24-42')

    # --- login page --------------------------------------------------------

    def test_login_page_shows_the_button_only_when_configured(self):
        self.assertContains(self.client.get(reverse('login')), 'Войти через Bitrix24')
        with self.settings(BITRIX24_PORTAL=''):
            self.assertNotContains(self.client.get(reverse('login')), 'Войти через Bitrix24')


@override_settings(BITRIX24_LINK_REQUIRED=True, **BITRIX24_SETTINGS)
class Bitrix24LinkRequiredMiddlewareTests(TestCase):
    """core.middleware.Bitrix24LinkRequiredMiddleware + the link page."""

    page = '/shopping-tabs/'

    def setUp(self):
        self.user = User.objects.create_user('ivan', email='ivan@example.com', password='x')
        self.client.force_login(self.user)

    def link_target(self, next_url):
        return reverse('bitrix24-link') + '?' + urlencode({'next': next_url})

    def test_unlinked_user_is_sent_to_link_and_back(self):
        response = self.client.get(self.page + '?q=1')
        self.assertRedirects(response, self.link_target(self.page + '?q=1'), fetch_redirect_response=False)

    def test_htmx_request_gets_a_client_redirect_to_the_page_it_was_on(self):
        response = self.client.get(
            '/notifications/panel/',
            HTTP_HX_REQUEST='true',
            HTTP_HX_CURRENT_URL='http://testserver' + self.page,
        )
        self.assertEqual(response['HX-Redirect'], self.link_target(self.page))

    def test_post_is_redirected_without_next(self):
        response = self.client.post(reverse('shopping-tab-list'))
        self.assertRedirects(response, reverse('bitrix24-link'), fetch_redirect_response=False)

    def test_linked_user_passes(self):
        Bitrix24Account.objects.create(user=self.user, bitrix_user_id=42)
        self.assertEqual(self.client.get(self.page).status_code, 200)

    def test_superuser_is_exempt(self):
        self.client.force_login(User.objects.create_superuser('root', 'r@example.com', 'x'))
        self.assertEqual(self.client.get(self.page).status_code, 200)

    def test_inert_when_off_or_not_configured(self):
        for overrides in ({'BITRIX24_LINK_REQUIRED': False}, {'BITRIX24_CLIENT_SECRET': ''}):
            with self.subTest(**overrides), self.settings(**overrides):
                self.assertEqual(self.client.get(self.page).status_code, 200)

    def test_exempt_paths(self):
        self.assertEqual(self.client.get(reverse('bitrix24-link')).status_code, 200)
        login_leg = self.client.get(reverse('bitrix24-login'))
        self.assertEqual(urlparse(login_leg['Location']).netloc, 'company.bitrix24.kz')
        self.assertEqual(self.client.post(reverse('bitrix24-callback')).status_code, 200)
        self.assertEqual(self.client.get(reverse('toast-messages')).status_code, 200)
        # /admin/ answers for itself (here: a redirect to its own login).
        self.assertNotIn('bitrix24', self.client.get('/admin/')['Location'])
        self.client.post(reverse('logout'))
        self.assertIsNone(self.client.session.get('_auth_user_id'))

    def test_link_page_offers_the_button_with_next(self):
        response = self.client.get(reverse('bitrix24-link'), {'next': self.page})
        self.assertContains(response, reverse('bitrix24-login') + '?next=/shopping-tabs/')

    def test_link_page_drops_a_foreign_next(self):
        response = self.client.get(reverse('bitrix24-link'), {'next': 'https://evil.example/'})
        # Only the link button is checked: the navbar's feedback button carries
        # the current URL, query included, as its own (encoded) page parameter.
        self.assertContains(response, f'href="{reverse("bitrix24-login")}"')
        self.assertEqual(response.context['next'], '')

    def test_link_page_says_when_already_linked(self):
        Bitrix24Account.objects.create(user=self.user, bitrix_user_id=42)
        self.assertContains(self.client.get(reverse('bitrix24-link')), 'уже привязан')

    @override_settings(BITRIX24_CLIENT_SECRET='')
    def test_link_page_404_when_not_configured(self):
        self.assertEqual(self.client.get(reverse('bitrix24-link')).status_code, 404)


class PersistentNotificationDeleteAllTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('owner', password='x')
        self.other = User.objects.create_user('other', password='x')
        for i in range(3):
            PersistentNotification.objects.create(user=self.user, message=f'msg {i}')
        PersistentNotification.objects.create(user=self.other, message='foreign')
        self.client.force_login(self.user)

    def test_deletes_only_own_notifications(self):
        response = self.client.post(reverse('persistent-notifications-delete-all'))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(PersistentNotification.objects.filter(user=self.user).exists())
        self.assertEqual(PersistentNotification.objects.filter(user=self.other).count(), 1)
        self.assertContains(response, 'Нет сохранённых уведомлений.')
        self.assertContains(response, 'id="persistent-notifications-badge" hx-swap-oob="true"')

    def test_get_is_not_allowed(self):
        response = self.client.get(reverse('persistent-notifications-delete-all'))

        self.assertEqual(response.status_code, 405)
        self.assertEqual(PersistentNotification.objects.filter(user=self.user).count(), 3)

    def test_button_shown_only_when_there_are_notifications(self):
        url = reverse('persistent-notifications-delete-all')
        panel = reverse('persistent-notifications-panel')
        self.assertContains(self.client.get(panel), url)

        PersistentNotification.objects.filter(user=self.user).delete()
        self.assertNotContains(self.client.get(panel), url)


class PersistentNotificationLifetimeTests(TestCase):
    """Сроки жизни: обычные — от первого показа, выгрузки и обновления — вручную."""

    def setUp(self):
        self.user = User.objects.create_user('reader', password='x')
        self.client.force_login(self.user)
        self.panel = reverse('persistent-notifications-panel')

    def _create(self, level='success', kind='regular', **kwargs):
        return PersistentNotification.objects.create(
            user=self.user, level=level, kind=kind, message=f'{level} {kind}', **kwargs)

    def test_closed_panel_poll_does_not_start_the_countdown(self):
        notification = self._create()

        self.client.get(self.panel, {'seen': 'false'})

        notification.refresh_from_db()
        self.assertIsNone(notification.seen_at)
        self.assertIsNone(notification.expires_at)

    def test_ttl_after_first_show_by_level(self):
        expected = {
            'success': timedelta(seconds=10),
            'info': timedelta(seconds=10),
            'warning': timedelta(minutes=10),
            'danger': timedelta(minutes=10),
        }
        notifications = {level: self._create(level=level) for level in expected}

        response = self.client.get(self.panel, {'seen': 'true'})

        self.assertContains(response, 'data-expires-in-ms=', count=4)
        for level, ttl in expected.items():
            notification = notifications[level]
            notification.refresh_from_db()
            self.assertEqual(notification.expires_at - notification.seen_at, ttl, level)

    def test_second_show_does_not_extend_the_lifetime(self):
        notification = self._create()
        self.client.get(self.panel, {'seen': 'true'})
        notification.refresh_from_db()
        first_expiry = notification.expires_at

        self.client.get(self.panel, {'seen': 'true'})

        notification.refresh_from_db()
        self.assertEqual(notification.expires_at, first_expiry)

    def test_manual_kinds_never_expire(self):
        notifications = [self._create(kind=kind) for kind in ('export', 'release', 'confirmation')]

        response = self.client.get(self.panel, {'seen': 'true'})

        self.assertNotContains(response, 'data-expires-in-ms=')
        for notification in notifications:
            notification.refresh_from_db()
            self.assertIsNotNone(notification.seen_at)
            self.assertIsNone(notification.expires_at)

    def test_expired_notifications_are_hidden(self):
        now = timezone.now()
        self._create(seen_at=now - timedelta(seconds=11), expires_at=now - timedelta(seconds=1))
        alive = self._create(level='warning', seen_at=now, expires_at=now + timedelta(minutes=10))

        self.assertEqual(list(PersistentNotification.objects.visible()), [alive])
        response = self.client.get(self.panel)
        self.assertContains(response, 'warning regular')
        self.assertNotContains(response, 'success regular')

    def test_cleanup_deletes_expired_and_long_unseen_regular_only(self):
        from .tasks import cleanup_persistent_notifications_task

        now = timezone.now()
        self._create(seen_at=now - timedelta(minutes=1), expires_at=now - timedelta(seconds=1))
        fresh = self._create()
        stale_unseen = self._create()
        stale_export = self._create(kind='export')
        PersistentNotification.objects.filter(pk__in=[stale_unseen.pk, stale_export.pk]).update(
            created_at=now - timedelta(hours=settings.PERSISTENT_NOTIFICATION_TTL_HOURS + 1))

        cleanup_persistent_notifications_task()

        self.assertEqual(
            set(PersistentNotification.objects.values_list('pk', flat=True)),
            {fresh.pk, stale_export.pk},
        )

    def test_toast_message_counts_as_shown(self):
        from django.contrib import messages
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.template import Context, Template
        from django.test import RequestFactory

        request = RequestFactory().get('/')
        request.user = self.user
        request.session = self.client.session
        storage = FallbackStorage(request)
        request._messages = storage
        messages.success(request, 'Сохранено')
        Template('{% load toast_tags %}{% for m in msgs %}{% persist_notification m %}{% endfor %}').render(
            Context({'request': request, 'msgs': list(storage)}))

        notification = PersistentNotification.objects.get(user=self.user)
        self.assertEqual(notification.expires_at - notification.seen_at, timedelta(seconds=10))
