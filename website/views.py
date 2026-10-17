from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import TemplateView, View

from website.forms import LeadRequestForm


class HomeView(TemplateView):
    template_name = "site/home.html"

    def get(self, request, *args, **kwargs):
        if request.tenant:
            if request.user.is_authenticated:
                return redirect("tenants:dashboard")
            return redirect("login")
        return super().get(request, *args, **kwargs)


class NovaRedeView(TemplateView):
    template_name = "site/novarede.html"


class TaCombinadoView(TemplateView):
    template_name = "site/tacombinado.html"


class ViaZapView(TemplateView):
    template_name = "site/viazap.html"


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


class PlansView(TemplateView):
    template_name = "site/plans.html"

    def get_context_data(self, **kwargs):
        from website.models import SubscriptionPlan
        context = super().get_context_data(**kwargs)
        context["plans"] = SubscriptionPlan.objects.filter(is_active=True)
        return context


class PolicyView(TemplateView):
    template_name = "site/policy.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        policies = {
            "privacy": ("Política de privacidade", [
                "O formulário coleta nome, estabelecimento, e-mail e, opcionalmente, telefone e mensagem para responder à solicitação de contato. Não envie credenciais de roteadores ou dados sensíveis.",
                "As solicitações são armazenadas no sistema e acessíveis à equipe administrativa autorizada. O envio não inscreve você em campanhas de marketing.",
                "Para solicitar esclarecimentos, acesso, correção ou exclusão dos dados enviados, use o formulário de contato e identifique sua solicitação. A equipe avaliará o pedido e as obrigações aplicáveis.",
                "O site usa cookies de sessão e proteção CSRF para funcionamento e segurança. Esta versão não inclui rastreamento publicitário ou ferramentas de análise de terceiros.",
                "Antes de ativar operações comerciais, o responsável deverá formalizar identificação do controlador, canal de privacidade, bases legais e procedimentos de atendimento. Esta versão descreve o formulário atual e não certifica conformidade legal."
            ]),
            "terms": ("Termos de uso", [
                "O site apresenta a Nova Info e recebe solicitações de demonstração. A central possui cadastros e adaptadores de monitoramento WireGuard, API RouterOS e assinaturas Mercado Pago. A ativação depende da configuração e homologação de cada integração.",
                "Imagens do painel, métricas e preços de acessos são demonstrativos. A simulação calcula receita bruta, sem custos, taxas ou garantia de resultados.",
                "Planos publicados são informações comerciais; contratação depende de proposta e disponibilidade. A vitrine pública não efetua cobranças. A assinatura mensal dos estabelecimentos pelo Mercado Pago depende de credenciais e homologação. Os visitantes pagam a internet em dinheiro diretamente ao estabelecimento. O registro no painel não movimenta dinheiro nem libera acesso automaticamente.",
                "O acesso à área do cliente exige autorização para o estabelecimento. Não compartilhe credenciais nem tente acessar dados de outras organizações.",
                "Condições contratuais, suporte e responsabilidades operacionais deverão ser formalizados antes da ativação do serviço."
            ]),
            "retention": ("Política de retenção de registros", [
                "Solicitações de contato são removidas manualmente pela administração. Sessões encerradas, auditoria e amostras de monitoramento possuem retenção configurável na central; a remoção depende da execução agendada do comando de expurgo.",
                "O responsável deve revisar a necessidade de manter cada solicitação e remover dados sem finalidade vigente, considerando eventuais obrigações aplicáveis.",
                "A coleta de sessões Hotspot é opcional, controlada por equipamento, e exige finalidade/base legal documentada e prazo de retenção. O prazo deve ser definido pelo responsável antes da coleta. Não há coleta de páginas visitadas nesta integração.",
                "Pedidos sobre dados enviados podem ser encaminhados pelo formulário de contato. A política deverá ser atualizada quando novas integrações forem ativadas."
            ])
        }
        context["policy_title"], context["paragraphs"] = policies[self.extra_context["kind"]]
        return context


def robots(request):
    from django.http import HttpResponse
    return HttpResponse("User-agent: *\nAllow: /\nDisallow: /admin/\nDisallow: /accounts/\nDisallow: /painel/\nDisallow: /central/\nDisallow: /integracoes/\nSitemap: https://novainfo.com.br/sitemap.xml\n", content_type="text/plain")


def sitemap(request):
    from django.http import HttpResponse
    from xml.sax.saxutils import escape
    names = ["home", "platform-plans", "privacy", "terms", "retention"]
    entries = "".join(f"<url><loc>{escape('https://novainfo.com.br' + reverse(name))}</loc></url>" for name in names)
    return HttpResponse('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + entries + '</urlset>', content_type="application/xml")
