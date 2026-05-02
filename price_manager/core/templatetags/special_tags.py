from django import template
from product_price_manager.models import PRICE_TYPES

register = template.Library()

@register.filter
def get_item(dictionary, key):
  return dictionary.get(key, "")

@register.filter
def make_range(value):
  """Позволяет в шаблоне писать {% for i in 5|make_range %} ... {% endfor %}"""
  return range(int(value))

@register.filter
def stringformat(left, right):
  return f'{left}'+f'{right}'

@register.filter
def get_len(obj):
  return len(obj)

@register.filter
def is_in(left, right):
  return left in right

@register.filter
def get(obj, indx):
  return obj[indx]


@register.filter
def subtract(a, b):
  return (b) - (a)


@register.filter
def percent_added(num):
  return num*100 + 100

@register.filter
def margin(first, second):
  if first == 0:
    return 0
  return (float(first) - float(second))/float(first) * 100


@register.filter
def price_type(name):
  if name in PRICE_TYPES.keys():
    return PRICE_TYPES[name]
  else: return 'Странная цена'

@register.filter
def values_list(queryset, value):
  return map(str, queryset.values_list(value, flat=True))

@register.filter
def intersection(a,b):
  return not set(a).intersection(set(b)) == set()
from django.utils.safestring import mark_safe
from django.urls import reverse

@register.simple_tag
def fileupload(input_name='file_id', button_text='Загрузить файл'):
  modal_id = f'file-upload-modal-{input_name}'.replace('[', '-').replace(']', '-')
  trigger_id = f'file-upload-trigger-{input_name}'.replace('[', '-').replace(']', '-')
  hidden_id = f'file-upload-hidden-{input_name}'.replace('[', '-').replace(']', '-')
  html = f"""
<button type=\"button\" id=\"{trigger_id}\" class=\"btn btn-outline-primary\"
        data-bs-toggle=\"modal\" data-bs-target=\"#{modal_id}\"
        hx-get=\"{reverse('select-file')}\"
        hx-target=\"#{modal_id} .modal-content\" hx-swap=\"innerHTML\">{button_text}</button>

<input type=\"hidden\" id=\"{hidden_id}\" name=\"{input_name}\" value=\"\" />

<div id=\"{modal_id}\" class=\"modal fade\" tabindex=\"-1\" aria-hidden=\"true\">
  <div class=\"modal-dialog modal-lg\">
    <div class=\"modal-content\"></div>
  </div>
</div>

<script>
window.handleFileSelected = function(event) {{
  const xhr = event.detail.xhr;
  if (!xhr || xhr.status < 200 || xhr.status >= 300) return;
  const filePk = (xhr.responseText || '').trim();
  if (!filePk) return;
  const hiddenInput = document.getElementById('{hidden_id}');
  const triggerButton = document.getElementById('{trigger_id}');
  if (hiddenInput) hiddenInput.value = filePk;
  if (triggerButton) triggerButton.remove();
  const modalEl = document.getElementById('{modal_id}');
  if (modalEl && window.bootstrap) {{
    const modalInstance = bootstrap.Modal.getInstance(modalEl);
    if (modalInstance) modalInstance.hide();
  }}
}};
</script>
"""
  return mark_safe(html)
