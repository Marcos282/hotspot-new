from django import forms
from django.core import signing
from django.core.exceptions import ImproperlyConfigured,ValidationError
from django.db import transaction
from django.contrib import messages
from django.shortcuts import render,redirect
from django.views import View
from tenants.mixins import TenantAccessMixin
from tenants.views import require_editor,membership
from tenants.models import TenantSettings,AuditEvent
from website.models import SubscriptionPlan
from operations.models import SaaSSubscription
from operations.billing import subscription_credentials,valid_checkout_url


class PlanChoiceField(forms.ModelChoiceField):
    def label_from_instance(self,obj):
        return f'{obj.name} — R$ {obj.monthly_price:.2f} por mês'


class SubscribeForm(forms.Form):
    plan=PlanChoiceField(label='Plano mensal',queryset=SubscriptionPlan.objects.none())
    payer_email=forms.EmailField(label='E-mail da conta Mercado Pago',max_length=254)
    quote=forms.CharField(widget=forms.HiddenInput)
    authorize=forms.BooleanField(label='Solicito a contratação mensal pelo valor indicado. A autorização da recorrência será concluída no Mercado Pago.')

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['plan'].queryset=SubscriptionPlan.objects.filter(is_active=True,monthly_price__gt=0)

    def clean(self):
        values=super().clean()
        try:
            quote=signing.loads(values.get('quote',''),salt='saas-quote',max_age=900)
            plan=values.get('plan')
            if not plan or quote.get(str(plan.pk))!=str(plan.monthly_price):
                raise ValueError()
        except (signing.BadSignature,ValueError,AttributeError):
            raise ValidationError('O valor foi atualizado ou a proposta expirou. Atualize a página e revise o preço antes de confirmar.')
        return values


class SubscriptionView(TenantAccessMixin,View):
    def handle(self,request):
        require_editor(request)
        ready=True
        try:
            subscription_credentials()
        except ImproperlyConfigured:
            ready=False
        form=SubscribeForm(request.POST if request.method=='POST' else None,initial={'payer_email':request.tenant.email,'quote':signing.dumps({str(plan.pk):str(plan.monthly_price) for plan in SubscriptionPlan.objects.filter(is_active=True,monthly_price__gt=0)},salt='saas-quote')})
        if request.method=='POST' and ready and form.is_valid():
            with transaction.atomic():
                lock,_=TenantSettings.objects.get_or_create(tenant=request.tenant)
                TenantSettings.objects.select_for_update().get(pk=lock.pk)
                if SaaSSubscription.objects.for_tenant(request.tenant).exists():
                    form.add_error(None,'Já existe uma solicitação ou assinatura. Consulte a equipe antes de contratar novamente.')
                else:
                    subscription=SaaSSubscription.objects.create(tenant=request.tenant,plan=form.cleaned_data['plan'],monthly_amount=form.cleaned_data['plan'].monthly_price,payer_email=form.cleaned_data['payer_email'],requested_by=request.user)
                    AuditEvent.objects.create(tenant=request.tenant,actor=request.user,action='solicitar assinatura mensal',object_type='saassubscription',object_id=subscription.pk,fields_changed=['plan','monthly_amount','payer_email'])
                    messages.success(request,'Solicitação registrada. Após o processamento, conclua a autorização no Mercado Pago pelo link exibido aqui.')
                    return redirect('tenants:subscription')
        if request.method=='POST' and not ready:
            form.add_error(None,'Cobrança mensal ainda não habilitada. Solicite uma proposta à Nova Info.')
        subscription=SaaSSubscription.objects.for_tenant(request.tenant).first()
        checkout=subscription.checkout_url if subscription and subscription.checkout_url and valid_checkout_url(subscription.checkout_url) else None
        return render(request,'tenants/subscription.html',dict(tenant=request.tenant,membership=membership(request),page_title='Minha assinatura Nova Info',form=form,subscription=subscription,ready=ready,checkout=checkout))

    get=handle
    post=handle
