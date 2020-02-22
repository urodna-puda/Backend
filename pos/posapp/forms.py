from django import forms

from posapp.models import User, PaymentMethod


class CreateUserForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'password', 'email', 'mobile_phone', 'is_waiter', 'is_manager',
                  'is_admin', 'is_active']

    def __init__(self, *args, **kwargs):
        super(CreateUserForm, self).__init__(*args, **kwargs)
        for visible in self.visible_fields():
            if isinstance(visible.field.widget, forms.widgets.TextInput):
                visible.field.widget.attrs['class'] = 'form-control'
            elif isinstance(visible.field.widget, forms.widgets.EmailInput):
                visible.field.widget.attrs['class'] = 'form-control'
            elif isinstance(visible.field.widget, forms.widgets.CheckboxInput):
                visible.field.widget.attrs['class'] = 'form-check-input'


class CreatePaymentMethodForm(forms.ModelForm):
    class Meta:
        model = PaymentMethod
        fields = ['name', 'currency', 'changeAllowed']

    def __init__(self, *args, **kwargs):
        super(CreatePaymentMethodForm, self).__init__(*args, **kwargs)
        for visible in self.visible_fields():
            if isinstance(visible.field.widget, forms.widgets.TextInput):
                visible.field.widget.attrs['class'] = 'form-control'
            elif isinstance(visible.field.widget, forms.widgets.Select):
                visible.field.widget.attrs['class'] = 'form-control'
            elif isinstance(visible.field.widget, forms.widgets.CheckboxInput):
                visible.field.widget.attrs['class'] = 'form-check-input'
