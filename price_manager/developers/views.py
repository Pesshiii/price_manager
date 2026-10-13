from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render
from django.views.generic import CreateView

from core.task_runner import dispatch_after_commit
from developers.forms import FeedbackForm
from developers.models import Feedback
from developers.tasks import send_feedback_task


class FeedbackCreateView(LoginRequiredMixin, CreateView):
    """Modal form opened from the navbar on any page.

    Success renders a thank-you into the same modal instead of the usual
    HttpResponseClientRefresh: the modal sits over whatever page the user was
    working on, and a reload there would throw away their filters and scroll.
    """

    model = Feedback
    form_class = FeedbackForm
    template_name = 'developers/partials/feedback_form.html'

    def get_initial(self):
        return {
            'page': self.request.GET.get('page', ''),
            'rendered_page': self.request.GET.get('rendered_page', ''),
        }

    def form_valid(self, form):
        feedback = form.save(commit=False)
        feedback.author = self.request.user
        feedback.page_url = self._absolute_url(form.cleaned_data.get('page'))
        feedback.rendered_url = self._absolute_url(form.cleaned_data.get('rendered_page'))
        feedback.save()
        dispatch_after_commit(send_feedback_task, feedback.pk)
        return render(
            self.request,
            'developers/partials/feedback_sent.html',
            {'feedback': feedback},
        )

    def _absolute_url(self, path):
        if not path:
            return ''
        # nginx forwards Host and X-Forwarded-Proto (deploy/nginx.conf.example),
        # so this is the public https address, not the container's.
        return self.request.build_absolute_uri(path)[:500]
