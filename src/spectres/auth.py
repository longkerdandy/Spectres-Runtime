"""Authorization provider for the all-users-equal deployment phase."""

from agno.os.authz.provider import AuthorizationContext, AuthorizationProvider


class AnyAuthenticatedProvider(AuthorizationProvider):
    """Grant every authenticated caller full access to every route.

    Token scopes carry no weight in this phase. It is meant to be composed
    with agno's ``ScopeAuthorizationProvider`` (OR semantics), so
    scope-bearing credentials — admin-scope dev tokens, the scheduler's
    internal service token, service-account PATs — keep working unchanged.
    """

    def check(self, ctx: AuthorizationContext) -> bool:
        """Allow any authenticated principal on resource checks."""
        if not ctx.resource_type or not ctx.action:
            return True
        return ctx.principal_id is not None

    def authorize_route(self, ctx: AuthorizationContext, required_scopes: list[str]) -> bool:
        """Allow any authenticated principal regardless of the route's scopes."""
        return ctx.principal_id is not None

    def accessible_resource_ids(self, ctx: AuthorizationContext) -> set[str]:
        """Authenticated callers see every resource; anonymous sees nothing."""
        return {"*"} if ctx.principal_id is not None else set()
