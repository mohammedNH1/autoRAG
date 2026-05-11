from django import template

register = template.Library()


@register.simple_tag
def user_image_url(user):
    """Return the user's profile image URL, or empty string if none."""
    if user is None or not getattr(user, 'is_authenticated', False):
        return ''
    profile = getattr(user, 'profile', None)
    image = getattr(profile, 'image', None) if profile else None
    if not image:
        return ''
    try:
        return image.url
    except ValueError:
        return ''
