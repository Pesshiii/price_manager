from django import template

register = template.Library()


@register.simple_tag
def group_head_row(table, row):
  """BoundRow заголовка группы pim_id, либо None, если строка её не открывает.

  Существует потому, что шаблон не может позвать метод таблицы с аргументом, а
  заголовок надо построить именно по текущей строке. BoundRow, а не готовый
  HTML: так ячейки заголовка проходят обычный рендер django-tables2 и
  автоматически совпадают с видимыми колонками и их порядком.
  """
  builder = getattr(table, 'group_head_row', None)
  if builder is None:
    return None
  return builder(row.record)
