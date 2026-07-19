from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def homepage(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="marketing_home.html")


@router.get("/how-it-works", response_class=HTMLResponse)
async def how_it_works(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="marketing_how_it_works.html")


@router.get("/for-agencies", response_class=HTMLResponse)
async def for_agencies(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="marketing_for_agencies.html")


@router.get("/pricing", response_class=HTMLResponse)
async def pricing(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="marketing_pricing.html")


@router.get("/intelligence-report", response_class=HTMLResponse)
async def intelligence_report(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="marketing_intelligence_report.html")


@router.get("/whats-coming", response_class=HTMLResponse)
async def whats_coming(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="marketing_whats_coming.html")


@router.get("/trial")
async def trial(request: Request):
    return RedirectResponse(url="/onboard/trial", status_code=301)


@router.get("/thank-you", response_class=HTMLResponse)
async def thank_you(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="marketing_thank_you.html")


@router.get("/terms", response_class=HTMLResponse)
async def terms(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="marketing_terms.html")


# SEO & crawler control
@router.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt():
    """Serve robots.txt — allow marketing pages, block internal app routes."""
    return PlainTextResponse(
        content="""# https://gorampit.com/robots.txt
User-agent: *
Allow: /
Allow: /how-it-works
Allow: /for-agencies
Allow: /pricing
Allow: /intelligence-report
Allow: /whats-coming
Allow: /trial
Allow: /thank-you
Allow: /terms

# Internal application routes — not for indexing
Disallow: /admin
Disallow: /api/
Disallow: /login
Disallow: /register
Disallow: /onboard
Disallow: /home
Disallow: /review
Disallow: /threads
Disallow: /clients
Disallow: /avatars
Disallow: /settings
Disallow: /pipeline
Disallow: /export
Disallow: /dry-run
Disallow: /docs
Disallow: /redoc
Disallow: /openapi.json
Disallow: /health
Disallow: /waitlist/signup
Disallow: /mkt/

# Crawl-delay for polite bots
Crawl-delay: 2

# Sitemap
Sitemap: https://gorampit.com/sitemap.xml
""",
        media_type="text/plain",
    )


@router.get("/llms.txt", response_class=PlainTextResponse)
async def llms_txt():
    """Serve llms.txt — describe site for LLM crawlers in safe marketing language."""
    return PlainTextResponse(
        content="""# RAMP — Reddit Audience & Mentions Platform
# https://gorampit.com

> RAMP is a managed community engagement platform for B2B brands.

## What RAMP Does

RAMP helps marketing teams monitor Reddit conversations relevant to their industry,
discover engagement opportunities, and manage their brand presence across communities.

The platform provides:
- AI-powered subreddit discovery and thread relevance scoring
- Competitor mention monitoring and share-of-voice analysis
- Content strategy generation aligned with community guidelines
- Human-in-the-loop content approval workflows
- Brand visibility tracking across AI search engines (AEO/GEO monitoring)
- Reddit Landscape Reports with actionable insights

## Who It's For

- B2B SaaS marketing teams (cybersecurity, DevOps, fintech)
- Growth and demand generation leaders
- Digital marketing agencies managing multiple client brands
- Founders building thought leadership on Reddit

## Key Principles

- Every piece of content is reviewed and approved by humans before publication
- Community guidelines and subreddit rules are respected
- Transparent, value-driven engagement — not spam
- Brand safety guardrails enforced at the platform level

## Pages

- Homepage: https://gorampit.com/
- How It Works: https://gorampit.com/how-it-works
- For Agencies: https://gorampit.com/for-agencies
- Pricing: https://gorampit.com/pricing
- Intelligence Report: https://gorampit.com/intelligence-report
- Product Roadmap: https://gorampit.com/whats-coming
- Free Trial: https://gorampit.com/trial

## Contact

Website: https://gorampit.com
""",
        media_type="text/plain",
    )


@router.get("/sitemap.xml", response_class=PlainTextResponse)
async def sitemap_xml():
    """Serve sitemap.xml for search engines."""
    return PlainTextResponse(
        content="""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://gorampit.com/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>
  <url><loc>https://gorampit.com/how-it-works</loc><changefreq>monthly</changefreq><priority>0.8</priority></url>
  <url><loc>https://gorampit.com/for-agencies</loc><changefreq>monthly</changefreq><priority>0.8</priority></url>
  <url><loc>https://gorampit.com/pricing</loc><changefreq>monthly</changefreq><priority>0.9</priority></url>
  <url><loc>https://gorampit.com/intelligence-report</loc><changefreq>monthly</changefreq><priority>0.8</priority></url>
  <url><loc>https://gorampit.com/whats-coming</loc><changefreq>weekly</changefreq><priority>0.7</priority></url>
  <url><loc>https://gorampit.com/trial</loc><changefreq>monthly</changefreq><priority>0.9</priority></url>
  <url><loc>https://gorampit.com/terms</loc><changefreq>yearly</changefreq><priority>0.3</priority></url>
</urlset>
""",
        media_type="application/xml",
    )


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
