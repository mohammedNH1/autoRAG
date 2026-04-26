from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib import messages


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