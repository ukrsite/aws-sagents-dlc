"""
strands-evals: A high-performance synchronization library.
"""

__version__ = "0.1.0"
__author__ = "AI development Team"

import logging

# Set up a null handler to prevent "No handler found" warnings for library users
logging.getLogger(__name__).addHandler(logging.NullHandler())

# Export the primary interface for easy access
from .main import Client, start_service, ExamplenameError

__all__ = [
    "Client",
    "start_service",
    "ExamplenameError"
]

# Optional: Print initialization notice (common in research/POC tools)
# print(f"[*] strands-evals version {__version__} initialized.")