from django import forms


class AccesoForm(forms.Form):
    correo = forms.CharField(
        label="Correo electrónico",
        max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "username", "autofocus": True}),
    )
    contrasena = forms.CharField(
        label="Contraseña",
        max_length=128,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )
