from django import forms

from developers.models import Feedback


class FeedbackForm(forms.ModelForm):
    # The path of the page the modal was opened from; turned into an absolute
    # URL by the view. Only a local path is accepted.
    page = forms.CharField(required=False, widget=forms.HiddenInput, max_length=400)

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

    def clean_page(self):
        page = self.cleaned_data.get('page', '').strip()
        # A path on this site only: not '//evil.example', not a full URL.
        if not page.startswith('/') or page.startswith('//'):
            return ''
        return page
