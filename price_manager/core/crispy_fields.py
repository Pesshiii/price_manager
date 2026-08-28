from crispy_forms.layout import Field
from crispy_forms.utils import TEMPLATE_PACK

class CustomCheckbox(Field):
    template = 'core/includes/checkbox_field.html'


class OobField(Field):
    """A Field that renders with `oob=True` in its template context.

    Used to opt a normally-rendered field template into emitting
    `hx-swap-oob`, for cases where the field is being re-swapped into a
    DOM that was already seeded with matching ids by a prior, non-oob
    render of the same template.
    """
    def render(self, form, context, template_pack=TEMPLATE_PACK, extra_context=None, **kwargs):
        extra_context = extra_context or {}
        extra_context['oob'] = True
        return super().render(form, context, template_pack=template_pack, extra_context=extra_context, **kwargs)