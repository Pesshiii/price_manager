from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from django.views.generic import CreateView, UpdateView

from .forms import DataframeForm
from .models import Dataframe


class DataframeCreate(LoginRequiredMixin, CreateView):
    model = Dataframe
    form_class = DataframeForm
    template_name = "dataframe/create.html"

    def form_valid(self, form):
        messages.success(self.request, "Датафрейм создан.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("dataframe-update", kwargs={"pk": self.object.pk})


class DataframeUpdate(LoginRequiredMixin, UpdateView):
    model = Dataframe
    form_class = DataframeForm
    template_name = "dataframe/update.html"
    pk_url_kwarg = "pk"

    def form_valid(self, form):
        messages.success(self.request, "Датафрейм обновлен.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("dataframe-update", kwargs={"pk": self.object.pk})
