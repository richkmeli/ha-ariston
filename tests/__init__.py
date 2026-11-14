"""Tests for Ariston integration."""

# Home Assistant 2026.11+ aliases ``voluptuous`` to ``probatio`` when it is
# first imported. Import it before any test module imports voluptuous so the
# schemas and the exception classes used in assertions are the same objects.
import homeassistant  # noqa: F401
