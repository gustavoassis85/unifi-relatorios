from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect, render
from django.urls import reverse


@login_required
def inicio(request):
    if getattr(request, "vinculo", None):
        return redirect("clientes:lista")
    # Sem organização: o dono da plataforma (ou alguém de organização inativa).
    return render(request, "inicio.html")


def login_do_admin(request, extra_context=None):
    """Substitui o login do admin do Django, que não passa pelo MFA.

    Nunca recebe senha: quem não está logado vai para o login do sistema;
    quem está logado mas não é o dono da plataforma volta para o início.
    """
    if request.user.is_authenticated:
        return redirect("inicio")
    destino = request.GET.get("next") or reverse("admin:index")
    return redirect_to_login(destino, login_url=reverse("account_login"))
