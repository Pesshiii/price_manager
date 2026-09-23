from unittest import mock

import requests
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from developers import bitrix24
from developers.models import Feedback
from developers.tasks import build_title, send_feedback_task

WEBHOOK = 'https://company.bitrix24.kz/rest/1/s3cretcode/'
FEEDBACK_SETTINGS = {
    'BITRIX24_FEEDBACK_WEBHOOK': WEBHOOK,
    'BITRIX24_FEEDBACK_RESPONSIBLE_ID': 42,
}


def _response(status=200, payload=None):
    response = mock.Mock(status_code=status)
    if payload is None:
        response.json.side_effect = ValueError
    else:
        response.json.return_value = payload
    return response


def _created(task_id):
    return _response(payload={'result': {'task': {'id': str(task_id), 'title': '…'}}})


class FeedbackFormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ivan', 'ivan@example.com', 'pw', first_name='Иван')
        self.client.force_login(self.user)
        self.url = reverse('developers-feedback')

    def post(self, data):
        with mock.patch('developers.views.send_feedback_task') as task, \
                self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.url, data, HTTP_HX_REQUEST='true')
        return response, task

    def test_get_renders_form_with_page_prefilled(self):
        response = self.client.get(self.url, {'page': '/supplier/?q=abc'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="/supplier/?q=abc"')

    def test_each_message_is_saved_and_dispatched_on_its_own(self):
        _, first_task = self.post({'message': 'Первая', 'page': '/supplier/'})
        _, second_task = self.post({'message': 'Вторая', 'page': '/supplier/'})

        first, second = Feedback.objects.order_by('pk')
        self.assertEqual((first.message, second.message), ('Первая', 'Вторая'))
        self.assertEqual(first.author, self.user)
        self.assertEqual(first.status, Feedback.Status.PENDING)
        self.assertEqual(first.page_url, 'http://testserver/supplier/')
        first_task.delay.assert_called_once_with(first.pk)
        second_task.delay.assert_called_once_with(second.pk)

    def test_success_renders_thank_you_not_a_reload(self):
        response, _ = self.post({'message': 'Сломалась выгрузка'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('HX-Refresh', response)
        self.assertContains(response, 'Сообщение отправлено')

    def test_blank_message_is_rejected(self):
        response, task = self.post({'message': '   '})
        self.assertContains(response, 'is-invalid')
        self.assertFalse(Feedback.objects.exists())
        task.delay.assert_not_called()

    def test_foreign_page_is_dropped(self):
        for page in ('https://evil.example/x', '//evil.example/x'):
            self.post({'message': 'x', 'page': page})
        self.assertEqual(set(Feedback.objects.values_list('page_url', flat=True)), {''})

    def test_anonymous_is_sent_to_login(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response['Location'])


@override_settings(**FEEDBACK_SETTINGS)
class SendFeedbackTaskTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('ivan', 'ivan@example.com', 'pw')
        self.feedback = Feedback.objects.create(
            author=self.user, message='Не грузится прайс\nподробности', page_url='http://pm/supplier/',
        )

    def run_task(self, **patch_kwargs):
        with mock.patch('developers.bitrix24.requests.post', **patch_kwargs) as post:
            # .apply() runs eagerly, retries included, without a broker.
            result = send_feedback_task.apply(args=[self.feedback.pk])
        self.feedback.refresh_from_db()
        return result, post

    def test_creates_task_for_the_responsible_developer(self):
        result, post = self.run_task(return_value=_created(777))

        self.assertTrue(result.successful())
        self.assertEqual(self.feedback.status, Feedback.Status.SENT)
        self.assertEqual(self.feedback.bitrix_task_id, 777)
        self.assertIsNotNone(self.feedback.sent_at)

        post.assert_called_once()
        self.assertEqual(post.call_args.args[0], WEBHOOK + 'tasks.task.add.json')
        fields = post.call_args.kwargs['json']['fields']
        self.assertEqual(fields['RESPONSIBLE_ID'], 42)
        self.assertEqual(fields['TITLE'], f'Обратная связь PM #{self.feedback.pk}: Не грузится прайс')
        self.assertIn('ivan@example.com', fields['DESCRIPTION'])
        self.assertIn('http://pm/supplier/', fields['DESCRIPTION'])
        self.assertIn('подробности', fields['DESCRIPTION'])

    def test_already_sent_is_not_sent_twice(self):
        self.run_task(return_value=_created(777))
        _, post = self.run_task(return_value=_created(778))
        post.assert_not_called()
        self.assertEqual(self.feedback.bitrix_task_id, 777)

    def test_rejection_marks_failed_without_retrying(self):
        result, post = self.run_task(
            return_value=_response(400, {'error': 'ERROR_CORE', 'error_description': 'Нет прав'})
        )
        self.assertTrue(result.failed())
        post.assert_called_once()
        self.assertEqual(self.feedback.status, Feedback.Status.FAILED)
        self.assertIn('Нет прав', self.feedback.error)

    def test_outage_is_retried_then_marked_failed(self):
        result, post = self.run_task(side_effect=requests.ConnectionError(WEBHOOK))
        self.assertTrue(result.failed())
        self.assertEqual(post.call_count, 1 + send_feedback_task.max_retries)
        self.assertEqual(self.feedback.status, Feedback.Status.FAILED)
        # The webhook URL carries its secret code and must not leak into the row.
        self.assertNotIn('s3cretcode', self.feedback.error)

    def test_outage_then_recovery_sends_once(self):
        result, post = self.run_task(side_effect=[_response(503), _created(900)])
        self.assertTrue(result.successful())
        self.assertEqual(post.call_count, 2)
        self.assertEqual(self.feedback.status, Feedback.Status.SENT)
        self.assertEqual(self.feedback.error, '')

    @override_settings(BITRIX24_FEEDBACK_WEBHOOK='')
    def test_not_configured_keeps_message_and_calls_nothing(self):
        _, post = self.run_task()
        post.assert_not_called()
        self.assertEqual(self.feedback.status, Feedback.Status.FAILED)
        self.assertIn('не настроена', self.feedback.error)

    def test_title_is_truncated(self):
        self.feedback.message = 'а' * 200
        title = build_title(self.feedback)
        self.assertTrue(title.endswith('…'))
        self.assertLess(len(title), 120)


@override_settings(**FEEDBACK_SETTINGS)
class FeedbackAdminTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin', 'a@example.com', 'pw')
        self.client.force_login(self.admin)

    def test_resend_requeues_only_unsent(self):
        failed = Feedback.objects.create(message='a', status=Feedback.Status.FAILED, error='boom')
        sent = Feedback.objects.create(message='b', status=Feedback.Status.SENT, bitrix_task_id=5)

        with mock.patch('developers.admin.send_feedback_task') as task, \
                self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                reverse('admin:developers_feedback_changelist'),
                {'action': 'resend', '_selected_action': [failed.pk, sent.pk]},
            )

        task.delay.assert_called_once_with(failed.pk)
        failed.refresh_from_db()
        self.assertEqual((failed.status, failed.error), (Feedback.Status.PENDING, ''))

    def test_changelist_renders(self):
        Feedback.objects.create(message='a', status=Feedback.Status.SENT, bitrix_task_id=5)
        response = self.client.get(reverse('admin:developers_feedback_changelist'))
        self.assertEqual(response.status_code, 200)


class Bitrix24ClientTests(TestCase):
    @override_settings(**FEEDBACK_SETTINGS)
    def test_missing_task_id_is_an_error(self):
        with mock.patch('developers.bitrix24.requests.post', return_value=_response(payload={'result': {}})):
            with self.assertRaises(bitrix24.Bitrix24Error):
                bitrix24.create_task('t', 'd', 42)
