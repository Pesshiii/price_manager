from crispy_forms.layout import Field

class CustomCheckbox(Field):
    template = 'core/includes/checkbox_field.html'


class CustomRadio(Field):
    """Searchable, scrollable single-choice list — same look as CustomCheckbox,
    but for a plain ModelChoiceField (radio inputs, one value)."""
    template = 'core/includes/radio_field.html'

