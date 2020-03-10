from django.contrib.auth.decorators import user_passes_test, login_required
from django.contrib.auth.mixins import AccessMixin

from posapp.models import User

LOGIN_URL = '/accounts/login'
test_waiter_login_required = user_passes_test(lambda u: True if u.is_waiter else False, login_url=LOGIN_URL)
test_manager_login_required = user_passes_test(lambda u: True if u.is_manager else False, login_url=LOGIN_URL)
test_admin_login_required = user_passes_test(lambda u: True if u.is_admin else False, login_url=LOGIN_URL)


def waiter_login_required(view_func):
    decorated_view_func = login_required(test_waiter_login_required(view_func), login_url=LOGIN_URL)
    return decorated_view_func


def manager_login_required(view_func):
    decorated_view_func = login_required(test_manager_login_required(view_func), login_url=LOGIN_URL)
    return decorated_view_func


def admin_login_required(view_func):
    decorated_view_func = login_required(test_admin_login_required(view_func), login_url=LOGIN_URL)
    return decorated_view_func


class WaiterLoginRequiredMixin(AccessMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_waiter and not request.user.can_grant(request.user, User.WAITER):
            return self.handle_no_permission()
        return super().dispatch(request, *args, **kwargs)


class ManagerLoginRequiredMixin(AccessMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_manager and not request.user.can_grant(request.user, User.MANAGER):
            return self.handle_no_permission()
        return super().dispatch(request, *args, **kwargs)


class AdminLoginRequiredMixin(AccessMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_admin and not request.user.can_grant(request.user, User.ADMIN):
            return self.handle_no_permission()
        return super().dispatch(request, *args, **kwargs)
