import uuid
from django import forms
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.contrib import messages
from django.shortcuts import render,redirect
from django.utils import timezone
from django.views import View
from tenants.mixins import TenantAccessMixin
from tenants.models import AccessPlan,Sale,Payment,AuditEvent,TenantSettings


class CashPlanChoice(forms.ModelChoiceField):
    def label_from_instance(self,obj):
        return f'{obj.name} — {obj.duration_minutes} minutos — R$ {obj.price:.2f}'


class CashSaleForm(forms.Form):
    plan=CashPlanChoice(label='Plano vendido',queryset=AccessPlan.objects.none())
    received=forms.BooleanField(label='Confirmo que o estabelecimento recebeu o valor deste plano em dinheiro.')
    request_token=forms.CharField(widget=forms.HiddenInput)

    def __init__(self,*args,tenant,user,**kwargs):
        self.tenant=tenant
        self.user=user
        super().__init__(*args,**kwargs)
        query=AccessPlan.objects.for_tenant(tenant).filter(enabled=True,price__gt=0).order_by('name')
        self.fields['plan'].queryset=query
        if not self.is_bound:
            self.initial['request_token']=signing.dumps({'tenant':tenant.pk,'user':user.pk,'nonce':str(uuid.uuid4()),'plans':{str(plan.pk):{'price':str(plan.price),'duration':plan.duration_minutes} for plan in query}},salt='cash-sale')

    def clean(self):
        values=super().clean()
        try:
            quote=signing.loads(values.get('request_token',''),salt='cash-sale',max_age=900)
            plan=values.get('plan')
            if quote['tenant']!=self.tenant.pk or quote['user']!=self.user.pk or not plan or quote['plans'].get(str(plan.pk))!={'price':str(plan.price),'duration':plan.duration_minutes}:
                raise ValueError()
            values['request_id']=uuid.UUID(quote['nonce'])
        except (signing.BadSignature,KeyError,ValueError,TypeError):
            raise forms.ValidationError('Plano, preço ou período alterado, ou formulário expirado. Atualize a página e confira os valores antes de registrar.')
        return values


class CashSaleView(TenantAccessMixin,View):
    def handle(self,request):
        member=request.tenant_membership
        if member.role not in ['owner','admin','staff']:
            raise PermissionDenied
        form=CashSaleForm(request.POST if request.method=='POST' else None,tenant=request.tenant,user=request.user)
        if request.method=='POST' and form.is_valid():
            with transaction.atomic():
                lock,_=TenantSettings.objects.get_or_create(tenant=request.tenant)
                TenantSettings.objects.select_for_update().get(pk=lock.pk)
                previous=Sale.objects.for_tenant(request.tenant).filter(cash_request_id=form.cleaned_data['request_id']).first()
                if previous:
                    messages.success(request,'Este recebimento já foi registrado. Nenhuma venda duplicada foi criada.')
                    return redirect('tenants:records',section='vendas')
                chosen=form.cleaned_data['plan']
                plan=AccessPlan.objects.for_tenant(request.tenant).select_for_update().get(pk=chosen.pk)
                if not plan.enabled or plan.price<=0 or plan.price!=chosen.price or plan.duration_minutes!=chosen.duration_minutes:
                    form.add_error(None,'O plano foi alterado. Atualize a página e confira o valor e o período.')
                else:
                    receipt='DIN-'+str(form.cleaned_data['request_id'])
                    sale=Sale.objects.create(tenant=request.tenant,plan=plan,reference=receipt,cash_request_id=form.cleaned_data['request_id'],duration_minutes=plan.duration_minutes,amount=plan.price,status='paid')
                    Payment.objects.create(tenant=request.tenant,sale=sale,provider_reference=receipt,amount=plan.price,status='paid',method='cash',received_by=request.user,received_at=timezone.now())
                    AuditEvent.objects.create(tenant=request.tenant,actor=request.user,action='registrar recebimento em dinheiro',object_type='sale',object_id=sale.pk,fields_changed=['plan','amount','duration_minutes','status','payment.method','payment.received_by','payment.received_at'])
                    messages.success(request,'Recebimento em dinheiro registrado para o estabelecimento. Este registro não libera internet automaticamente.')
                    return redirect('tenants:records',section='vendas')
        return render(request,'tenants/cash_sale.html',dict(tenant=request.tenant,membership=member,page_title='Registrar venda em dinheiro',form=form))

    get=handle
    post=handle
