from django import template

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
def margin(first, second):
  if first == 0:
    return 0
  return (float(first) - float(second))/float(first) * 100