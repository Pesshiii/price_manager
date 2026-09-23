from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.views.generic import DetailView, ListView

from releases.models import Release


def visible_releases(user):
    """Everyone reads published releases; staff also preview drafts."""
    releases = Release.objects.all()
    if not user.is_staff:
        releases = releases.filter(is_published=True)
    return releases


class ReleaseListView(ListView):
    template_name = 'releases/release_list.html'
    context_object_name = 'releases'
    paginate_by = 20

    def get_queryset(self):
        return visible_releases(self.request.user)


class ReleaseDetailView(DetailView):
    template_name = 'releases/release_detail.html'
    context_object_name = 'release'

    def get_object(self, queryset=None):
        return get_object_or_404(visible_releases(self.request.user), version=self.kwargs['version'])


class ReleaseMarkdownView(ReleaseDetailView):
    """The article's Markdown copy as a plain .md file."""

    def render_to_response(self, context, **response_kwargs):
        release = self.object
        heading = f'# Версия {release.version}'
        if release.title:
            heading += f' — {release.title}'
        text = f'{heading}\n\n{release.summary.strip()}\n\n{release.article_markdown}\n'
        return HttpResponse(text, content_type='text/markdown; charset=utf-8')
