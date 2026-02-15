from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from .forms import ArticleForm
from .models import Article


class ArticleListView(LoginRequiredMixin, ListView):
    model = Article
    template_name = 'blogapp/article_list.html'
    context_object_name = 'articles'


class ArticleDetailView(LoginRequiredMixin, DetailView):
    model = Article
    template_name = 'blogapp/article_detail.html'
    context_object_name = 'article'


class ArticleCreateView(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = Article
    form_class = ArticleForm
    template_name = 'blogapp/article_form.html'
    success_message = 'Статья создана.'

    def form_valid(self, form):
        form.instance.author = self.request.user
        return super().form_valid(form)


class ArticleAuthorRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.get_object().author_id == self.request.user.id


class ArticleUpdateView(LoginRequiredMixin, ArticleAuthorRequiredMixin, SuccessMessageMixin, UpdateView):
    model = Article
    form_class = ArticleForm
    template_name = 'blogapp/article_form.html'
    success_message = 'Статья обновлена.'

    def get_success_url(self):
        return reverse_lazy('blogapp:article-detail', kwargs={'pk': self.object.pk})
