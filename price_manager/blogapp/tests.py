from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Article


class BlogArticleViewsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='author',
            password='pass12345',
        )
        self.other_user = get_user_model().objects.create_user(
            username='other',
            password='pass12345',
        )
        self.article = Article.objects.create(
            title='Test title',
            content='Test content',
            author=self.user,
        )

    def test_article_list_available_for_authenticated_user(self):
        self.client.login(username='author', password='pass12345')

        response = self.client.get(reverse('blogapp:article-list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.article.title)

    def test_article_creation_sets_author(self):
        self.client.login(username='author', password='pass12345')

        response = self.client.post(
            reverse('blogapp:article-create'),
            data={'title': 'New post', 'content': 'Body'},
        )

        self.assertEqual(response.status_code, 302)
        created_article = Article.objects.get(title='New post')
        self.assertEqual(created_article.author, self.user)

    def test_author_can_update_own_article(self):
        self.client.login(username='author', password='pass12345')

        response = self.client.post(
            reverse('blogapp:article-update', kwargs={'pk': self.article.pk}),
            data={'title': 'Updated title', 'content': 'Updated content'},
        )

        self.assertEqual(response.status_code, 302)
        self.article.refresh_from_db()
        self.assertEqual(self.article.title, 'Updated title')

    def test_non_author_cannot_edit_article(self):
        self.client.login(username='other', password='pass12345')

        response = self.client.get(reverse('blogapp:article-update', kwargs={'pk': self.article.pk}))

        self.assertEqual(response.status_code, 403)
