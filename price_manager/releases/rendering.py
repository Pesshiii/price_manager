import nh3
from markdownify import markdownify

# What an article may keep. Everything else — <script>, <style>, event
# handlers, javascript: URLs — is stripped before the article is stored.
ALLOWED_TAGS = {
    'a', 'abbr', 'b', 'blockquote', 'br', 'code', 'dd', 'del', 'details', 'div',
    'dl', 'dt', 'em', 'figcaption', 'figure', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'hr', 'i', 'img', 'kbd', 'li', 'mark', 'ol', 'p', 'pre', 's', 'small', 'span',
    'strong', 'sub', 'summary', 'sup', 'table', 'tbody', 'td', 'tfoot', 'th',
    'thead', 'tr', 'u', 'ul',
}
ALLOWED_ATTRIBUTES = {
    '*': {'class', 'title'},
    'a': {'href', 'target'},
    'img': {'src', 'alt', 'width', 'height'},
    'td': {'colspan', 'rowspan'},
    'th': {'colspan', 'rowspan'},
}


def clean_html(html: str) -> str:
    """Sanitized article HTML: safe to render with |safe."""
    return nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes={'http', 'https', 'mailto'},
        link_rel='noopener noreferrer',
    ).strip()


def html_to_markdown(html: str) -> str:
    """The Markdown copy of an article, derived from its (clean) HTML."""
    return markdownify(html, heading_style='ATX', bullets='-').strip()
