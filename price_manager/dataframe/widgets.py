from django import forms


class DataframeChoiceWidget(forms.Select):
    """Reusable widget for picking a Dataframe with a 'Create new' button.

    Pair with the modal partial `dataframe/partials/_modal_create.html`
    in the parent template; the button triggers HTMX to load the modal
    fragment, and the created Dataframe pk is delivered to the parent
    via the HX-Trigger `dataframe:created` event.
    """

    template_name = 'dataframe/widgets/dataframe_select.html'

    def __init__(self, *args, **kwargs):
        attrs = kwargs.pop('attrs', None) or {}
        attrs.setdefault('class', 'form-select')
        attrs.setdefault('data-dataframe-select', '1')
        kwargs['attrs'] = attrs
        super().__init__(*args, **kwargs)
