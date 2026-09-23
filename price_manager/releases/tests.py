from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import PersistentNotification
from releases.models import Release
from releases.tasks import LINK_TEXT, build_message, notify_release


def make_release(**kwargs):
    defaults = {
        'version': '1.4.0',
        'summary': 'Приоритеты поставщиков теперь нумеруются 1…N.',
        'article_html': '<p>Первый абзац.</p><p>Второй абзац.</p>',
    }
    defaults.update(kwargs)
    # Patch out the dispatch: tests call notify_release() directly.
    with mock.patch('releases.tasks.notify_release_task'):
        return Release.objects.create(**defaults)


class ReleaseDispatchTests(TestCase):
    def save(self, release):
        with mock.patch('releases.tasks.notify_release_task') as task, \
                self.captureOnCommitCallbacks(execute=True):
            release.save()
        return task

    def test_draft_is_not_announced(self):
        task = self.save(Release(version='1.0', summary='s', article_html='<p>a</p>'))
        task.delay.assert_not_called()

    def test_publishing_dispatches_once_after_commit(self):
        release = make_release()
        release.is_published = True
        task = self.save(release)
        task.delay.assert_called_once_with(release.pk)

    def test_editing_an_announced_release_does_not_re_announce(self):
        release = make_release(is_published=True)
        notify_release(release.pk)
        release.refresh_from_db()
        release.article_html = '<p>Исправленный текст.</p>'
        task = self.save(release)
        task.delay.assert_not_called()


class NotifyReleaseTests(TestCase):
    def setUp(self):
        self.users = [User.objects.create_user(f'user{i}') for i in range(3)]
        self.inactive = User.objects.create_user('gone', is_active=False)

    def test_every_active_user_gets_the_summary_with_a_link(self):
        release = make_release(is_published=True, title='Приоритеты')

        self.assertEqual(notify_release(release.pk), 3)

        notifications = PersistentNotification.objects.all()
        self.assertEqual({n.user_id for n in notifications}, {u.pk for u in self.users})
        for notification in notifications:
            self.assertEqual(notification.link, '/releases/1.4.0/')
            self.assertEqual(notification.link_text, LINK_TEXT)
            self.assertIn('Вышла версия 1.4.0: Приоритеты', notification.message)
            self.assertIn('нумеруются 1…N', notification.message)
        release.refresh_from_db()
        self.assertIsNotNone(release.notified_at)

    def test_second_run_sends_nothing(self):
        release = make_release(is_published=True)
        notify_release(release.pk)
        self.assertEqual(notify_release(release.pk), 0)
        self.assertEqual(PersistentNotification.objects.count(), 3)

    def test_draft_and_missing_release_send_nothing(self):
        draft = make_release()
        self.assertEqual(notify_release(draft.pk), 0)
        self.assertEqual(notify_release(draft.pk + 1000), 0)
        self.assertFalse(PersistentNotification.objects.exists())

    def test_message_is_escaped(self):
        # The notification panel renders message with |safe.
        release = make_release(summary='<script>alert(1)</script>', title='<b>x</b>')
        message = build_message(release)
        self.assertNotIn('<script>', message)
        self.assertNotIn('<b>x</b>', message)
        self.assertIn('&lt;script&gt;', message)


class ArticleStorageTests(TestCase):
    def test_markdown_copy_is_built_from_html(self):
        release = make_release(article_html=(
            '<h2>Что изменилось</h2><ul><li><strong>цены</strong></li><li>остатки</li></ul>'
            '<p>Подробнее — <a href="/products/">каталог</a>.</p>'
        ))
        self.assertIn('## Что изменилось', release.article_markdown)
        self.assertIn('- **цены**', release.article_markdown)
        self.assertIn('- остатки', release.article_markdown)
        self.assertIn('[каталог](/products/)', release.article_markdown)

    def test_markdown_copy_follows_every_html_edit(self):
        release = make_release()
        release.article_html = '<p>Новый текст.</p>'
        with mock.patch('releases.tasks.notify_release_task'):
            release.save(update_fields=['article_html'])
        release.refresh_from_db()
        self.assertEqual(release.article_markdown, 'Новый текст.')

    def test_html_is_sanitized_before_storage(self):
        release = make_release(article_html=(
            '<script>alert(1)</script><p onclick="x()">ok</p>'
            '<a href="javascript:alert(1)">a</a><table><tr><td>2</td></tr></table>'
        ))
        release.refresh_from_db()
        for stored in (release.article_html, release.article_markdown):
            self.assertNotIn('<script', stored)
            self.assertNotIn('alert(1)', stored)
            self.assertNotIn('onclick', stored)
            self.assertIn('ok', stored)
        self.assertInHTML('<td>2</td>', release.article_html)


class ReleaseViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('manager')
        self.client.force_login(self.user)
        self.published = make_release(version='1.4.0', is_published=True, title='Опубликованная')
        self.draft = make_release(version='1.5.0', title='Черновая')

    def test_list_shows_only_published_to_managers(self):
        response = self.client.get(reverse('release-list'))
        self.assertContains(response, 'Опубликованная')
        self.assertNotContains(response, 'Черновая')

    def test_detail_renders_article(self):
        response = self.client.get(self.published.get_absolute_url())
        self.assertContains(response, '<p>Первый абзац.</p>', html=True)
        self.assertContains(response, '<p>Второй абзац.</p>', html=True)

    def test_markdown_copy_is_served_as_md(self):
        response = self.client.get(reverse('release-markdown', args=['1.4.0']))
        self.assertEqual(response['Content-Type'], 'text/markdown; charset=utf-8')
        text = response.content.decode()
        self.assertTrue(text.startswith('# Версия 1.4.0 — Опубликованная'))
        self.assertIn('Первый абзац.', text)
        self.assertEqual(self.client.get(reverse('release-markdown', args=['1.5.0'])).status_code, 404)

    def test_draft_is_hidden_from_managers_and_visible_to_staff(self):
        url = self.draft.get_absolute_url()
        self.assertEqual(self.client.get(url).status_code, 404)

        self.user.is_staff = True
        self.user.save()
        self.assertContains(self.client.get(url), 'Черновик')
        self.assertContains(self.client.get(reverse('release-list')), 'Черновая')


class ReleaseAdminTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_login(self.admin)

    def test_publish_action_announces_drafts_only(self):
        draft = make_release(version='2.0')
        announced = make_release(version='1.9', is_published=True)
        with mock.patch('releases.tasks.notify_release_task') as task, \
                self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('admin:releases_release_changelist'), {
                'action': 'publish',
                '_selected_action': [draft.pk, announced.pk],
            })
        draft.refresh_from_db()
        self.assertTrue(draft.is_published)
        task.delay.assert_called_once_with(draft.pk)

    def test_add_form_sets_author(self):
        with mock.patch('releases.tasks.notify_release_task'), \
                self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('admin:releases_release_add'), {
                'version': '3.0',
                'title': '',
                'released_at': '2026-09-23',
                'summary': 'Кратко',
                'article_html': '<p>Статья</p>',
            })
        release = Release.objects.get(version='3.0')
        self.assertEqual(release.author, self.admin)
        self.assertEqual(release.article_markdown, 'Статья')
