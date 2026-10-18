"""Errors that mean something specific to the caller, so the edges can map them without guessing.

Anything that is not one of these (or a typed error from another layer) is a bug, and the API
answers it with a plain 500 that carries no internal detail.
"""

from __future__ import annotations


class InvalidInput(ValueError):
    """The operator's input cannot be used; the message is safe to show to them."""


class ConfigurationError(RuntimeError):
    """The application is not set up for what was asked; the message says what to set."""
