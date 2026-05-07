#https://gist.github.com/Tobi-De/31535e7434956b6269afac84e147cfce

class HtmxMixin:
    success_url = ""
    htmx_template = None

    @property
    def htmx_partial(self) -> str:
        return f'{self.htmx_template}#partial'

    @property
    def template_name(self) -> str:
        return self.htmx_partial if self.request.htmx else self.htmx_template