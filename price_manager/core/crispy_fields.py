from crispy_forms.layout import Field

class CustomCheckbox(Field):
    template = 'core/includes/checkbox_field.html'