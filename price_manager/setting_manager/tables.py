from django.utils.html import format_html, mark_safe
import django_tables2 as tables

from common.utils import get_field_details
from setting_manager.forms import LinkForm
from setting_manager.models import Dict, Link, Setting


class SettingListTable(tables.Table):
    actions = tables.TemplateColumn(
        template_name='supplier/setting/actions.html',
        orderable=False,
        verbose_name='Действия',
        attrs={'td': {'class': 'text-right'}},
    )
    name = tables.LinkColumn('upload', args=['setting-update', tables.A('pk')])

    class Meta:
        model = Setting
        fields = [field for field in get_field_details(model).keys()]
        template_name = 'django_tables2/bootstrap5.html'
        attrs = {'class': 'table table-auto table-stripped table-hover clickable-rows'}


class LinkListTable(tables.Table):
    class Meta:
        model = Link
        fields = [field for field in get_field_details(model).keys()]
        template_name = 'django_tables2/bootstrap5.html'
        attrs = {'class': 'table table-auto table-stripped table-hover clickable-rows'}


class HTMLColumn(tables.Column):
    def render_header(self, bound_column, **kwargs):
        return mark_safe(str(bound_column.header))


def get_link_create_table():
    class LinkCreateTable(tables.Table):
        class Meta:
            template_name = 'django_tables2/bootstrap5.html'
            attrs = {'class': 'table table-auto table-striped table-bordered'}

        def __init__(self, *args, **kwargs):
            columns = kwargs.pop('columns', None) or []
            links = kwargs.pop('links', {})
            for i, column_name in enumerate(columns):
                initial = {'key': links.get(column_name, ''), 'value': column_name}
                self.base_columns[column_name] = HTMLColumn(
                    verbose_name=format_html(
                        '''
                            <div class="header-content">
                                <div class="header-title">
                                    <span>{}</span>
                                    <div class="header-widget">{}</div>
                                </div>
                            </div>
                        ''',
                        column_name,
                        LinkForm(initial=initial, prefix=f'link-form-{i}').as_p(),
                    ),
                    orderable=False,
                )
            super().__init__(*args, **kwargs)

    return LinkCreateTable


class DictFormTable(tables.Table):
    key = tables.TemplateColumn('{% load special_tags %}{{ record|get:"key" }}', verbose_name='Если', orderable=False)
    value = tables.TemplateColumn('{% load special_tags %}{{ record|get:"value" }}', verbose_name='То', orderable=False)
    DELETE = tables.TemplateColumn(
        """{% load special_tags %}<button type="submit" class="btn btn-danger" name="delete" value="{{ record|get:'btn' }}"><i class=\"bi bi-x\"></i></button>""",
        verbose_name='',
        orderable=False,
    )

    class Meta:
        attrs = {'class': 'table-auto'}


def get_upload_list_table():
    class UploadListTable(tables.Table):
        class Meta:
            template_name = 'django_tables2/bootstrap5.html'
            attrs = {'class': 'table table-auto table-striped table-bordered'}

        def __init__(self, *args, **kwargs):
            links = dict(kwargs.pop('links', None) or {})
            for column, field in links.items():
                self.base_columns[column] = tables.Column(verbose_name=f'{column}/{field}')
            super().__init__(*args, **kwargs)

    return UploadListTable
