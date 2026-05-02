from django import template

register = template.Library()


@register.inclusion_tag("product/tags/create_content_type.html")
def create_content_type(field_name="content_type_pk", button_text="Создать новый", initial_pk=None):
    return {
        "field_name": field_name,
        "button_text": button_text,
        "initial_pk": initial_pk,
    }
