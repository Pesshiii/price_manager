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
        return {'page': self.request.GET.get('page', '')}

    def form_valid(self, form):
        feedback = form.save(commit=False)
        feedback.author = self.request.user
        page = form.cleaned_data.get('page')
        feedback.page_url = self.request.build_absolute_uri(page)[:500] if page else ''
        feedback.save()
        dispatch_after_commit(send_feedback_task, feedback.pk)
        return render(
            self.request,
            'developers/partials/feedback_sent.html',
            {'feedback': feedback},
        )
