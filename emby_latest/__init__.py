"""
Emby Latest Publications system.

Provides a unified interface for collecting, caching, and accessing
the latest movies and series publications from Emby servers.
"""

from emby_latest.manager import get_manager, reset_manager

__all__ = ['get_manager', 'reset_manager']
