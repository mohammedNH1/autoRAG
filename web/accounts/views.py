from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from urllib.parse import urlparse, urlencode
import re

from .models import UserProfile

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _safe_back_url(request, fallback):
    """Resolve a same-host `back_url` for the profile page.

    Priority:
      1. ?next=… query/form param.
      2. Referer header (only if it points back into our host and isn't the
         profile page itself, to avoid trapping the user).
      3. The given fallback (typically workspace list).
    """
    candidates = [request.GET.get("next"), request.POST.get("next"),
                  request.META.get("HTTP_REFERER")]
    profile_path = reverse("accounts:profile")
    for raw in candidates:
        if not raw:
            continue
        parsed = urlparse(raw)
        # Same-host or relative path only — refuse absolute URLs to other hosts.
        if parsed.netloc and parsed.netloc != request.get_host():
            continue
        path = parsed.path or "/"
        # Normalize slashes: reverse() includes trailing slash; Referer paths often omit it.
        profile_prefix = profile_path.rstrip("/") or "/"
        path_norm = path.rstrip("/") or "/"
        if path_norm == profile_prefix or path.startswith(profile_prefix + "/"):
            continue
        # Reconstruct relative URL with query string preserved.
        return path + (f"?{parsed.query}" if parsed.query else "")
    return fallback


def login_view(request):

    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")

        try:
            user = User.objects.get(email=email)
            user = authenticate(request, username=user.username, password=password)
        except User.DoesNotExist:
            user = None

        if user is not None:
            login(request, user)
            return redirect("workspace_list")
        else:
            messages.error(request, "Invalid email or password.")

    return render(request, "accounts/login.html")


def signup_view(request):
    if request.method == "POST":
        full_name = request.POST.get("full_name", "").strip()
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")

        if User.objects.filter(email=email).exists():
            messages.error(request, "An account with this email already exists.")
        else:
            first_name, _, last_name = full_name.partition(" ")
            user = User.objects.create_user(
                username=email,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
            )
            login(request, user)
            return redirect("workspace_list")

    return render(request, "accounts/signup.html")


def logout_view(request):
    logout(request)
    return redirect("accounts:login")


@login_required
def profile_view(request):
    fallback = reverse("workspace_list")
    back_url = _safe_back_url(request, fallback)
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    if request.method == "POST":
        first_name = request.POST.get("first_name", "").strip()
        last_name  = request.POST.get("last_name", "").strip()
        email      = request.POST.get("email", "").strip().lower()
        image_file = request.FILES.get("profile_image")
        remove_image = request.POST.get("remove_image") == "1"

        valid = True
        if not email:
            messages.error(request, "Email is required.")
            valid = False
        elif not EMAIL_RE.match(email):
            messages.error(request, "Enter a valid email address.")
            valid = False
        elif User.objects.exclude(pk=request.user.pk).filter(email__iexact=email).exists():
            messages.error(request, "That email is already in use.")
            valid = False

        if valid and image_file is not None:
            if not (image_file.content_type or '').startswith('image/'):
                messages.error(request, "Profile picture must be an image.")
                valid = False
            elif image_file.size > 5 * 1024 * 1024:
                messages.error(request, "Image must be 5 MB or smaller.")
                valid = False

        if valid:
            old_username = request.user.username
            request.user.first_name = first_name[:150]
            request.user.last_name  = last_name[:150]
            request.user.email      = email
            if "@" in old_username:
                request.user.username = email
            request.user.save()

            if remove_image and profile.image:
                profile.image.delete(save=False)
                profile.image = None
                profile.save()
            elif image_file is not None:
                if profile.image:
                    profile.image.delete(save=False)
                profile.image = image_file
                profile.save()

            messages.success(request, "Profile updated.")
            profile_url = reverse("accounts:profile")
            if back_url and back_url != fallback:
                profile_url += "?" + urlencode({"next": back_url})
            return HttpResponseRedirect(profile_url)

    return render(request, "accounts/profile.html", {
        "back_url": back_url,
        "profile": profile,
    })