"""Backward-compatible Jinja2Templates wrapper.

Starlette 1.3.0+ changed TemplateResponse signature:
  OLD: TemplateResponse(name=..., context={"request": req, ...})
  NEW: TemplateResponse(request, name=..., context={...})

This module provides a drop-in Jinja2Templates subclass that accepts BOTH styles,
so existing code (hundreds of call sites) doesn't need to change.
"""

from typing import Any, Mapping

from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.templating import Jinja2Templates as _Jinja2Templates
from starlette.templating import _TemplateResponse


class Jinja2Templates(_Jinja2Templates):
    """Jinja2Templates with backward-compatible TemplateResponse."""

    def TemplateResponse(  # noqa: N802
        self,
        # Accept request as positional OR let it come from context/kwargs
        *args: Any,
        **kwargs: Any,
    ) -> _TemplateResponse:
        """Render template — supports both old and new Starlette calling conventions.

        Old style (pre-1.3.0):
            templates.TemplateResponse(name="x.html", context={"request": req, ...})
            templates.TemplateResponse("x.html", {"request": req, ...})

        New style (1.3.0+):
            templates.TemplateResponse(request, name="x.html", context={...})
            templates.TemplateResponse(request=req, name="x.html", context={...})
        """
        request = None
        name = None
        context = None
        status_code = kwargs.pop("status_code", 200)
        headers = kwargs.pop("headers", None)
        media_type = kwargs.pop("media_type", None)
        background = kwargs.pop("background", None)

        # Parse positional args
        if args:
            if isinstance(args[0], Request):
                # New style: TemplateResponse(request, name, context, ...)
                request = args[0]
                if len(args) > 1:
                    name = args[1]
                if len(args) > 2:
                    context = args[2]
            elif isinstance(args[0], str):
                # Old positional style: TemplateResponse("template.html", {"request": ...})
                name = args[0]
                if len(args) > 1:
                    context = args[1]
            else:
                # Fallback: treat first arg as name
                name = args[0]
                if len(args) > 1:
                    context = args[1]

        # Parse keyword args (override positional)
        if "request" in kwargs:
            request = kwargs.pop("request")
        if "name" in kwargs:
            name = kwargs.pop("name")
        if "context" in kwargs:
            context = kwargs.pop("context")

        # If request not found yet, try to extract from context
        if request is None and context and "request" in context:
            request = context["request"]

        if request is None:
            raise TypeError(
                "TemplateResponse requires a 'request' argument — "
                "pass it as first positional arg, as request= kwarg, "
                "or include it in context dict."
            )

        if name is None:
            raise TypeError("TemplateResponse requires a 'name' argument.")

        context = context or {}
        context.setdefault("request", request)

        for context_processor in self.context_processors:
            context.update(context_processor(request))

        template = self.get_template(name)
        return _TemplateResponse(
            template,
            context,
            status_code=status_code,
            headers=headers,
            media_type=media_type,
            background=background,
        )
