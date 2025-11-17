from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView


class InstructionsView(LoginRequiredMixin, TemplateView):
    template_name = 'main/instructions.html'
