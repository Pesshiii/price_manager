from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

User = get_user_model()


@override_settings(SECURE_SSL_REDIRECT=False)
class ArticleApiBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='author', password='p')
        cls.other = User.objects.create_user(username='other', password='p')

    def setUp(self):
        self.client.force_login(self.author)

    def _create(self, title='Title', content='Body'):
        return self.client.post(
            reverse('articles_api:article-list'),
            {'title': title, 'content': content},
            content_type='application/json',
        )


class AnonymousAccessTests(ArticleApiBase):
    def setUp(self):
        pass  # not logged in

    def test_list_requires_auth(self):
        resp = self.client.get(reverse('articles_api:article-list'))
        self.assertEqual(resp.status_code, 401)

    def test_detail_requires_auth(self):
        self.client.force_login(self.author)
        pk = self.client.post(
            reverse('articles_api:article-list'),
            {'title': 'T', 'content': 'C'},
            content_type='application/json',
        ).json()['id']
        self.client.logout()

        resp = self.client.get(reverse('articles_api:article-detail', args=[pk]))
        self.assertEqual(resp.status_code, 401)


class ArticleCrudTests(ArticleApiBase):
    def test_create(self):
        resp = self._create('Hello', '# Hello World')
        self.assertEqual(resp.status_code, 201, resp.content[:300])
        data = resp.json()
        self.assertEqual(data['title'], 'Hello')
        self.assertEqual(data['author']['username'], 'author')

    def test_author_set_from_request_user(self):
        resp = self._create()
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['author']['id'], self.author.id)

    def test_list_excludes_content(self):
        self._create()
        resp = self.client.get(reverse('articles_api:article-list'))
        self.assertEqual(resp.status_code, 200)
        results = resp.json()
        self.assertGreater(len(results), 0)
        self.assertNotIn('content', results[0])

    def test_retrieve_includes_content(self):
        pk = self._create('Detail', 'Full content').json()['id']
        resp = self.client.get(reverse('articles_api:article-detail', args=[pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('content', resp.json())
        self.assertEqual(resp.json()['content'], 'Full content')

    def test_patch(self):
        pk = self._create('Original', 'Text').json()['id']
        resp = self.client.patch(
            reverse('articles_api:article-detail', args=[pk]),
            {'title': 'Updated'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['title'], 'Updated')

    def test_delete(self):
        pk = self._create().json()['id']
        resp = self.client.delete(reverse('articles_api:article-detail', args=[pk]))
        self.assertEqual(resp.status_code, 204)


class ArticlePermissionTests(ArticleApiBase):
    def setUp(self):
        super().setUp()
        self.article_pk = self._create('My article', 'Content').json()['id']
        self.client.force_login(self.other)

    def test_patch_by_non_author_forbidden(self):
        resp = self.client.patch(
            reverse('articles_api:article-detail', args=[self.article_pk]),
            {'title': 'Hacked'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_delete_by_non_author_forbidden(self):
        resp = self.client.delete(
            reverse('articles_api:article-detail', args=[self.article_pk])
        )
        self.assertEqual(resp.status_code, 403)

    def test_read_by_non_author_allowed(self):
        resp = self.client.get(
            reverse('articles_api:article-detail', args=[self.article_pk])
        )
        self.assertEqual(resp.status_code, 200)

    def test_put_not_allowed(self):
        resp = self.client.put(
            reverse('articles_api:article-detail', args=[self.article_pk]),
            {'title': 'x', 'content': 'y'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 405)
