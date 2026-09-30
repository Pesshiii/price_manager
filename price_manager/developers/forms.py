from django import forms

from developers.models import Feedback


class FeedbackForm(forms.ModelForm):
    # Paths turned into absolute URLs by the view; only local paths are accepted.
    # page — the browser's address when the modal was opened;
    # rendered_page — the page the navbar (and so the button) was rendered for.
    # They differ once HTMX has rewritten the address after the page load.
    page = forms.CharField(required=False, widget=forms.HiddenInput, max_length=400)
    rendered_page = forms.CharField(required=False, widget=forms.HiddenInput, max_length=400)

    class Meta:
        model = Feedback
        fields = ('message',)
        labels = {'message': 'Что случилось или что улучшить?'}
        widgets = {
            'message': forms.Textarea(attrs={
                'rows': 6,
                'placeholder': 'Опишите ошибку или идею: что делали, что ожидали, что получилось.',
                'autofocus': True,
            }),
        }

    @staticmethod
    def _local_path(value):
        value = (value or '').strip()
        # A path on this site only: not '//evil.example', not a full URL.
        if not value.startswith('/') or value.startswith('//'):
            return ''
        return value

    def clean_page(self):
        return self._local_path(self.cleaned_data.get('page'))

    def clean_rendered_page(self):
        return self._local_path(self.cleaned_data.get('rendered_page'))
