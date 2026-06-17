from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def homepage(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("marketing_home.html", {"request": request})


@router.get("/how-it-works", response_class=HTMLResponse)
async def how_it_works(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("marketing_how_it_works.html", {"request": request})


@router.get("/for-agencies", response_class=HTMLResponse)
async def for_agencies(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("marketing_for_agencies.html", {"request": request})


@router.get("/pricing", response_class=HTMLResponse)
async def pricing(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("marketing_pricing.html", {"request": request})


@router.get("/intelligence-report", response_class=HTMLResponse)
async def intelligence_report(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("marketing_intelligence_report.html", {"request": request})


@router.get("/whats-coming", response_class=HTMLResponse)
async def whats_coming(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("marketing_whats_coming.html", {"request": request})


@router.get("/thank-you", response_class=HTMLResponse)
async def thank_you(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("marketing_thank_you.html", {"request": request})


# Legacy redirects
@router.get("/mobile", response_class=HTMLResponse)
async def mobile_redirect(request: Request):
    return RedirectResponse(url="/how-it-works", status_code=301)


@router.get("/proxy", response_class=HTMLResponse)
async def proxy_redirect(request: Request):
    return RedirectResponse(url="/for-agencies", status_code=301)


@router.get("/roadmap", response_class=HTMLResponse)
async def roadmap_redirect(request: Request):
    return RedirectResponse(url="/whats-coming", status_code=301)
