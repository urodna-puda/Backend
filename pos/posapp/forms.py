from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.validators import UnicodeUsernameValidator

from posapp.models import User, PaymentMethod, Product, ItemInProduct, Item


class CreateUserForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'password1', 'password2', 'email', 'mobile_phone', 'is_waiter',
                  'is_manager', 'is_admin', 'is_active']

    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Password confirmation", widget=forms.PasswordInput,
                                help_text="Enter the same password as above, for verification.")

    def __init__(self, *args, **kwargs):
        super(CreateUserForm, self).__init__(*args, **kwargs)
        for visible in self.visible_fields():
            if isinstance(visible.field.widget, forms.widgets.TextInput):
                visible.field.widget.attrs['class'] = 'form-control'
            elif isinstance(visible.field.widget, forms.widgets.EmailInput):
                visible.field.widget.attrs['class'] = 'form-control'
            elif isinstance(visible.field.widget, forms.widgets.PasswordInput):
                visible.field.widget.attrs['class'] = 'form-control'
            elif isinstance(visible.field.widget, forms.widgets.CheckboxInput):
                visible.field.widget.attrs['class'] = 'form-check-input'

    def clean_password2(self):
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("The two passwords don't match. Please enter the same password twice.")
        return password2

    def save(self, commit=True):
        user = super(CreateUserForm, self).save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


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


class CreateEditProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['name', 'price', 'enabled']

    def __init__(self, *args, **kwargs):
        super(CreateEditProductForm, self).__init__(*args, **kwargs)
        for visible in self.visible_fields():
            if isinstance(visible.field.widget, forms.widgets.TextInput):
                visible.field.widget.attrs['class'] = 'form-control'
            elif isinstance(visible.field.widget, forms.widgets.NumberInput):
                visible.field.widget.attrs['class'] = 'form-control'
            elif isinstance(visible.field.widget, forms.widgets.CheckboxInput):
                visible.field.widget.attrs['class'] = 'form-check-input'


ItemsInProductFormSet = forms.modelformset_factory(ItemInProduct, fields=['item', 'amount'], extra=2, can_delete=True)


class CreateItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = ['name', 'unitGroup']

    def __init__(self, *args, **kwargs):
        super(CreateItemForm, self).__init__(*args, **kwargs)
        for visible in self.visible_fields():
            if isinstance(visible.field.widget, forms.widgets.TextInput):
                visible.field.widget.attrs['class'] = 'form-control'
            elif isinstance(visible.field.widget, forms.widgets.Select):
                visible.field.widget.attrs['class'] = 'form-control'


class AuthenticationForm(forms.Form):
    username_validator = UnicodeUsernameValidator()
    username = forms.CharField(
        max_length=150,
        help_text='Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.',
        validators=[username_validator],
    )
    password = forms.CharField(widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super(AuthenticationForm, self).__init__(*args, **kwargs)
        for visible in self.visible_fields():
            visible.field.widget.attrs['class'] = 'form-control'

    def authenticate(self):
        return authenticate(username=self.cleaned_data.get('username'), password=self.cleaned_data.get('password'))
