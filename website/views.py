from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import TemplateView, View

from website.forms import LeadRequestForm


class HomeView(TemplateView):
    template_name = "site/home.html"


class LeadRequestView(View):
    def post(self, request, *args, **kwargs):
        form = LeadRequestForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                "Solicitação recebida. A equipe Nova Info entrará em contato.",
            )
            return redirect(f"{reverse('home')}#contato")

        messages.error(
            request,
            "Confira os campos e tente enviar sua solicitação novamente.",
        )
        return redirect(f"{reverse('home')}#contato")
