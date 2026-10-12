from django import forms

from website.models import LeadRequest


class LeadRequestForm(forms.ModelForm):
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = LeadRequest
        fields = ("name", "business_name", "email", "phone", "message")
        widgets = {
            "name": forms.TextInput(attrs={"autocomplete": "name"}),
            "business_name": forms.TextInput(attrs={"autocomplete": "organization"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
            "phone": forms.TextInput(attrs={"autocomplete": "tel"}),
            "message": forms.Textarea(attrs={"rows": 3}),
        }

    def clean_website(self):
        value = self.cleaned_data["website"]
        if value:
            raise forms.ValidationError("Não foi possível enviar sua solicitação.")
        return value
