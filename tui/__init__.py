"""Textual-based TUI for the OpenSubtitles subtitle downloader.

This package is a new presentation + orchestration layer over the existing
backends in ``library/``. ``library/*`` is never imported by widgets directly;
Provider adapters are the only layer that touches backend clients.
"""
