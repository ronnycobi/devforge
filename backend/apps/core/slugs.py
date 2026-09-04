"""Shared slug helper.

Generates a URL-safe slug that is unique within an optional scope (e.g. unique
per organization, or per project), disambiguating collisions with a numeric
suffix. Used by any model that carries a human-facing slug.
"""
from django.utils.text import slugify


def unique_slug(model, name, *, field="slug", scope=None, instance=None, fallback="item"):
    """Return a slug for `name` unique within `scope`.

    - `model`: the model class to check against.
    - `field`: the slug field name.
    - `scope`: dict of filters bounding uniqueness (e.g. {"organization": org}).
      Omit for global uniqueness.
    - `instance`: exclude this instance (so re-saving keeps its slug).
    - `fallback`: base used when `name` slugifies to empty.
    """
    base = slugify(name) or fallback
    qs = model._default_manager.all()
    if instance is not None and instance.pk:
        qs = qs.exclude(pk=instance.pk)
    if scope:
        qs = qs.filter(**scope)

    slug = base
    i = 2
    while qs.filter(**{field: slug}).exists():
        slug = f"{base}-{i}"
        i += 1
    return slug
