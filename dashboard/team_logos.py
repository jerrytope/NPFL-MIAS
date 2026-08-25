"""
Team crest lookup, shared by the public dashboard and the Super Computer page.

The index is built by listing the actual files in the logos static directory
rather than from a hand-maintained name->filename dict. That dict had drifted
from disk: it claimed 'doma united.png', 'inter lagos.png' and
'sporting lagos.png' while the real files are 'Doma United.png',
'Inter Lagos.png' and 'Sporting Lagos.png'. Windows ignores filename case so
it looked fine locally, but production is Ubuntu, where those three resolved
to 404s and rendered as broken images. Reading the directory makes that class
of bug impossible — drop a new crest in and it is picked up by name.
"""

import os

from django.conf import settings
from django.templatetags.static import static

LOGO_EXTENSIONS = ('.png', '.webp', '.jpg', '.jpeg', '.svg')

_LOGO_INDEX_CACHE = None


def _logo_dir():
    """The static dir holding the crests (settings.STATICFILES_DIRS[0])."""
    dirs = getattr(settings, 'STATICFILES_DIRS', None) or []
    return str(dirs[0]) if dirs else None


def get_logo_index(force_refresh=False):
    """
    {normalized_team_name: filename} for every crest on disk.

    Normalization is a lowercased, stripped basename, which is enough to match
    all 20 current clubs regardless of how each file happens to be capitalised.
    Cached in-process for this worker, like ratings.get_all_career_stats().
    """
    global _LOGO_INDEX_CACHE
    if _LOGO_INDEX_CACHE is not None and not force_refresh:
        return _LOGO_INDEX_CACHE

    index = {}
    directory = _logo_dir()
    if directory and os.path.isdir(directory):
        for filename in os.listdir(directory):
            base, ext = os.path.splitext(filename)
            if ext.lower() in LOGO_EXTENSIONS:
                index.setdefault(base.strip().lower(), filename)

    _LOGO_INDEX_CACHE = index
    return _LOGO_INDEX_CACHE


def get_logo_url(team_name):
    """
    Static URL for a club's crest, or None if it has no file.

    None is meaningful: the UI falls back to a styled initials badge, so a
    newly promoted club without a crest still renders sensibly.
    """
    if not team_name:
        return None

    filename = get_logo_index().get(str(team_name).strip().lower())
    return static(filename) if filename else None


def get_logo_url_map(team_names):
    """
    {lowercased_team_name: url_or_None} for a batch of clubs — one index
    lookup per name, no repeated directory scans.
    """
    index = get_logo_index()
    urls = {}
    for name in team_names:
        key = str(name).strip().lower()
        filename = index.get(key)
        urls[key] = static(filename) if filename else None
    return urls
