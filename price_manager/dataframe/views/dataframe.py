from pathlib import Path

import pandas as pd
from django.db import OperationalError, ProgrammingError
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, TemplateView, UpdateView

from core.tables import HTMXMixin

from ..forms import DataframeForm
from ..models import Dataframe, FileModel
