from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.services.ab_tests import get_default_variants, get_tests_for_page, ACTIVE_TESTS

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def homepage(request: Request) -> HTMLResponse:
    """Render the homepage with hero section and product cards."""
    return templates.TemplateResponse(request=request, name="marketing_home.html")


@router.get("/mobile", response_class=HTMLResponse)
async def mobile_page(request: Request) -> HTMLResponse:
    """Render the Mobile landing page with default variant pricing."""
    defaults = get_default_variants()
    tests = get_tests_for_page("mobile")
    # Build variant display values for template (no-JS fallback)
    variant_display = {}
    for test in tests:
        default_variant_name = defaults[test.test_name]
        for v in test.variants:
            if v.name == default_variant_name:
                variant_display[test.test_name] = v.display_value
                break
    return templates.TemplateResponse(
        request=request,
        name="marketing_mobile.html",
        context={"variants": variant_display, "tests": tests},
    )


@router.get("/proxy", response_class=HTMLResponse)
async def proxy_page(request: Request) -> HTMLResponse:
    """Render the Proxy landing page with default variant pricing."""
    defaults = get_default_variants()
    tests = get_tests_for_page("proxy")
    variant_display = {}
    for test in tests:
        default_variant_name = defaults[test.test_name]
        for v in test.variants:
            if v.name == default_variant_name:
                variant_display[test.test_name] = v.display_value
                break
    return templates.TemplateResponse(
        request=request,
        name="marketing_proxy.html",
        context={"variants": variant_display, "tests": tests},
    )


@router.get("/thank-you", response_class=HTMLResponse)
async def thank_you_page(request: Request) -> HTMLResponse:
    """Render the thank-you confirmation page."""
    return templates.TemplateResponse(request=request, name="marketing_thank_you.html")
