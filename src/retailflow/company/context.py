from contextvars import ContextVar


_current_tenant = ContextVar(
    "current_tenant",
    default=None,
)

_current_branch = ContextVar(
    "current_branch",
    default=None,
)


def set_current_tenant(company):
    return _current_tenant.set(company)


def get_current_tenant():
    return _current_tenant.get()


def reset_current_tenant(token):
    _current_tenant.reset(token)


def set_current_branch(branch):
    return _current_branch.set(branch)


def get_current_branch():
    return _current_branch.get()


def reset_current_branch(token):
    _current_branch.reset(token)