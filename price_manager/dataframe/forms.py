from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Div, Field, Submit, HTML, Button
from django.core.exceptions import ObjectDoesNotExist

from .models import FileModel, Dataframe

from django.urls import reverse


class FileForm(forms.ModelForm):
    class Meta:
        model = FileModel
        fields = ("file",)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper(self)
        self.helper.form_method = 'post'
        self.helper.attrs = {
                'enctype':'multipart/form-data',
                'hx-post': reverse('dataframe:filecreate'),
                'hx-swap':'innerHTML',
                'hx-target':'#SelectFile .modal-body',
                }
        self.helper.layout = Layout(
            Field('File'),
            Submit(
                name='submit', 
                value='Выбрать',
                data_bs_toggle="modal",
                data_bs_target="#SelectFileModal",)
        )

class SelectFileForm(forms.ModelForm):
    pk = forms.IntegerField(widget=forms.widgets.HiddenInput())
    class Meta:
        model = FileModel
        fields = ("pk",)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper(self)
        self.helper.form_method = 'post'
        if not self.instance:
            raise ObjectDoesNotExist()
        self.helper.attrs = {
                'hx-post': reverse('dataframe:fileitem', kwargs={'pk':self.instance.pk}),
                'hx-swap':'innerHTML',
                'hx-target':'#SelectFile .modal-body',
                }
        self.helper.layout = Layout(
            Field('pk'),
            Submit(
                name='submit', 
                value='Выбрать',
                data_bs_toggle="modal",
                data_bs_target="#SelectFileModal",)
        )

class FileInput(forms.ModelForm):
    pk = forms.IntegerField(widget=forms.widgets.HiddenInput())
    class Meta:
        model = FileModel
        fields = ("pk",)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper(self)
        self.helper.form_tag=False
        if not self.instance:
            raise ObjectDoesNotExist()
        self.helper.layout = Layout(
            Field('pk')
        )

class DataFrameForm(forms.ModelForm):
    class Meta:
        model = Dataframe
        fields = ('name',)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper(self)
        self.helper.form_method = 'post'
        self.helper.attrs={
            'hx-post':"{% url 'dataframe:create' %}",
            'hx-swap':"innerHTML",
            'hx-trigger':"change delay:250ms",
        }
        self.helper.layout = Layout(
            Field('name'),
            Div(
                Button(
                    name="button",
                    value="Добавить файл",
                    hx_get=reverse("dataframe:filelist"),
                    hx_target="#SelectFileContent",
                    hx_swap="innerHTML",
                    data_bs_toggle="modal",
                    data_bs_target="#SelectFileModal",
                ),
                HTML('''
                        <div class="modal fade" id="SelectFileModal" tabindex="-1" aria-hidden="true">
                            <div class="modal-dialog modal-lg">
                                <div class="modal-content">
                                    <div class="modal-header">
                                        <h5 class="modal-title">Выбор файла</h5>
                                        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                                    </div>
                                    <div class="modal-body" id="SelectFileContent">
                                    </div>
                                </div>
                            </div>
                        </div>
                    '''),
                css_id="FileInput"
            )
        )