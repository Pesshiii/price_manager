import django_tables2 as tables


class HTMXMixin(tables.Table):
    class Meta:
        template_name = 'core/tables/table_htmx.html'
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request')
        # url to put in get for infinite scroll
        self.url = kwargs.pop('url', None)
        if self.url is None:
            # try to send htmx request to where the table is initialized in case of missing url
            self.url = self.request.path_info
        super().__init__(*args, **kwargs)

class SelectableColumnsMixin(tables.Table):
    def __init__(self, *args, default_columns:list[str], column_choices=list[tuple[str]], selected_columns:list[str]|None=None, **kwargs):
        if selected_columns is None or len(selected_columns) == 0:
            selected_columns = default_columns
        extra_columns = kwargs.pop('extra_columns', None) or []
        extra_columns.extend([
            (
                key,
                tables.Column(
                accessor=key,
                verbose_name=verbose_name,
                default='',
                )
            )
            for key, verbose_name in column_choices
            if '__' in key
        ])
        super().__init__(*args, extra_columns=extra_columns, **kwargs)
        for column_key in dict(column_choices):
            if column_key not in selected_columns and column_key in self.columns:
                self.columns.hide(column_key)

        # ordered list of columns to display
        self.sequence = [column for column in selected_columns if column in self.columns]