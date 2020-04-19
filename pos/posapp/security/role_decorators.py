from django.contrib.auth.decorators import user_passes_test, login_required
from django.contrib.auth.mixins import AccessMixin

from posapp.models import User

LOGIN_URL = '/accounts/login'
test_waiter_login_required = user_passes_test(lambda u: True if u.is_waiter else False, login_url=LOGIN_URL)
test_manager_login_required = user_passes_test(lambda u: True if u.is_manager else False, login_url=LOGIN_URL)
test_director_login_required = user_passes_test(lambda u: True if u.is_director else False, login_url=LOGIN_URL)


def waiter_login_required(view_func):
    decorated_view_func = login_required(test_waiter_login_required(view_func), login_url=LOGIN_URL)
    return decorated_view_func


def manager_login_required(view_func):
    decorated_view_func = login_required(test_manager_login_required(view_func), login_url=LOGIN_URL)
    return decorated_view_func


def director_login_required(view_func):
    decorated_view_func = login_required(test_director_login_required(view_func), login_url=LOGIN_URL)
    return decorated_view_func


class WaiterLoginRequiredMixin(AccessMixin):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            if request.user.is_waiter or request.user.can_grant(request.user, User.WAITER):
                return super().dispatch(request, *args, **kwargs)
        return self.handle_no_permission()


class ManagerLoginRequiredMixin(AccessMixin):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            if request.user.is_manager or request.user.can_grant(request.user, User.MANAGER):
                return super().dispatch(request, *args, **kwargs)
        return self.handle_no_permission()


class DirectorLoginRequiredMixin(AccessMixin):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            if request.user.is_director or request.user.can_grant(request.user, User.DIRECTOR):
                return super().dispatch(request, *args, **kwargs)
        return self.handle_no_permission()
