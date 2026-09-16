"""Align the existing FBM bottom order-flow controls to the browser working set.

History owns the date scope. The bottom controls own only how many matching rows
are shown at once. They never submit /fbm, query the DB, call a marketplace or
change the selected History period.
"""
from __future__ import annotations


_PAGE_SIZE = 15
_PAGE_SIZES = (15, 30, 50, 100)


def _expand_control(html: str, *, visible_limit: int, has_more: bool) -> str:
    """Render the existing bottom flow as browser-local presentation controls."""
    del visible_limit, has_more
    options = "".join(
        f'<option value="{size}"{" selected" if size == _PAGE_SIZE else ""}>{size}</option>'
        for size in _PAGE_SIZES
    )
    control = (
        '<div class="card-footer d-flex justify-content-between align-items-center flex-wrap gap-2" id="bt38FbmOrderFlow">'
        '<span class="small text-muted bt38-table-count">Showing matching FBM orders</span>'
        '<div class="d-flex gap-2 align-items-center">'
        '<label class="small text-muted mb-0" for="bt38ResultsPerPageSelect">Show</label>'
        f'<select id="bt38ResultsPerPageSelect" class="form-select form-select-sm" style="width:auto" aria-label="FBM orders per page">{options}</select>'
        '<nav class="bt38-page-nav d-flex gap-1" aria-label="FBM order pages">'
        '<button class="btn btn-sm btn-outline-secondary bt38-page-link" id="bt38FbmPreviousPage" type="button">Previous</button>'
        '<span class="small text-muted bt38-page-status align-self-center px-1">Page 1</span>'
        '<button class="btn btn-sm btn-outline-secondary bt38-page-link" id="bt38FbmNextPage" type="button">Next</button>'
        '</nav>'
        '</div></div>'
    )
    marker = "</tbody></table></div>\n</div>"
    if marker not in html:
        return html
    return html.replace(marker, f"</tbody></table></div>\n{control}\n</div>", 1)


def install_governed_fbm_render_budget_alignment(app) -> None:
    if getattr(app, "_bt38_fbm_render_budget_alignment_installed", False):
        return

    from services import governed_fbm_page_alignment as page_alignment

    # The page/session working set is established by the existing FBM event/session
    # path. Do not replace it with the old 15-row request-scoped DB snapshot.
    page_alignment._expand_control = _expand_control

    app._bt38_fbm_render_budget_alignment_installed = True
    app.logger.info(
        "BT38 FBM bottom flow aligned: History owns scope; 15/30/50/100 and Previous/Next are browser-local; no expansion GET/DB read"
    )
