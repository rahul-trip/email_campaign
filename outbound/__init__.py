"""Outbound: an engine that researches target companies and drafts personal first emails."""

import warnings

# LangGraph's own import warns about a default that changes in a future release; it is noise on
# every command and nothing we configure.
warnings.filterwarnings("ignore", message=".*allowed_objects.*")
