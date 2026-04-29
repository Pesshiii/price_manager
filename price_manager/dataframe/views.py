from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render
from django.urls import reverse
from django.views.generic import CreateView, UpdateView, View

from .forms import ConfSourceForm, Form
from .models import Dataframe


class ConfSourceView(LoginRequiredMixin, View):
    template_name = "dataframe/partials/conf_source_form.html"

    def get(self, request, *args, **kwargs):
        form = Form()
        conf_form = form.conf_source_form
        return render(request, self.template_name, {"conf_form": conf_form})


class Create(LoginRequiredMixin, CreateView):
    model = Dataframe
    form_class = Form
    template_name = "dataframe/create.html"

    def form_valid(self, form):
        messages.success(self.request, "Датафрейм создан.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("dtaframe:dataframe-update", kwargs={"slug": self.object.slug})


class Update(LoginRequiredMixin, UpdateView):
    model = Dataframe
    form_class = Form
    template_name = "dataframe/update.html"
    slug_url_kwarg = "slug"

    def form_valid(self, form):
        messages.success(self.request, "Датафрейм обновлен.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("dtaframe:dataframe-update", kwargs={"slug": self.object.slug})
