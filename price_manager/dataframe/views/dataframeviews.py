from pathlib import Path

import pandas as pd
from django.db import OperationalError, ProgrammingError
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.generic import CreateView, TemplateView, UpdateView

from core.tables import HTMXMixin

from ..models import Dataframe
from ..forms import DataFrameForm

class DataframeCreate(CreateView):
    template_name='dataframe/create.html'
    form_class = DataFrameForm
    def get_success_url(self):
        return reverse('dataframe:create')
    model = Dataframe

class DataframeUpdate(UpdateView):
    template_name='dataframe/form.html'
    form_class = DataFrameForm
    def get_success_url(self):
        return reverse('dataframe:update', kwargs={'pk': self.object.pk})
    model = Dataframe