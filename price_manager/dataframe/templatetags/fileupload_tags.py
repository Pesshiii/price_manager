from django import template

register = template.Library()


@register.inclusion_tag("dataframe/tags/fileupload.html")
def fileupload(field_name="file_pk", button_text="Загрузить файл", initial_pk=None):
    return {
        "field_name": field_name,
        "button_text": button_text,
        "initial_pk": initial_pk,
    }
