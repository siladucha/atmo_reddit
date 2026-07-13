"""Telegram Bot integration — draft review channel.

Single bot serves both ops alerts (existing) and draft review (new).
Routing is based on User role: owner/partner → ops + review, client_* → review only.
"""
