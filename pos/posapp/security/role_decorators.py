from django.contrib.auth.decorators import user_passes_test, login_required

LOGIN_URL = '/accounts/login'
test_waiter_login_required = user_passes_test(lambda u: True if u.is_waiter else False, login_url=LOGIN_URL)
test_manager_login_required = user_passes_test(lambda u: True if u.is_manager else False, login_url=LOGIN_URL)
test_staff_login_required = user_passes_test(lambda u: True if u.is_staff else False, login_url=LOGIN_URL)


def waiter_login_required(view_func):
    decorated_view_func = login_required(test_waiter_login_required(view_func), login_url=LOGIN_URL)
    return decorated_view_func


def manager_login_required(view_func):
    decorated_view_func = login_required(test_manager_login_required(view_func), login_url=LOGIN_URL)
    return decorated_view_func


def staff_login_required(view_func):
    decorated_view_func = login_required(test_staff_login_required(view_func), login_url=LOGIN_URL)
    return decorated_view_func
