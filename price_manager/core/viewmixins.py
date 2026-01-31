#https://gist.github.com/Tobi-De/31535e7434956b6269afac84e147cfce

class HtmxView:
    success_url = ""

    @property
    def htmx_template(self) -> str:
        raise NotImplementedError

    @property
    def htmx_partial(self) -> str:
        raise NotImplementedError

    @property
    def template_name(self) -> str:
        return self.htmx_partial if self.request.htmx else self.htmx_template  # noqa