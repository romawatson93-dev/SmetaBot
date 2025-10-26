"""Service-layer package for the bot.

Важно:
- Не импортируйте подмодули через пакет (`from bot.services import ...`) — это вызывает циклические импорты.
- Импортируйте нужные модули напрямую:

Примеры:
    from bot.services.db import init_pool, fetch, execute
    from bot.services.channels import create_channel, list_by_contractor
    from bot.services.contractors import get_or_create_by_tg
    from bot.services.publications import add_publication, list_recent
    from bot.services.invites import create_invite, list_active
    from bot.services.clients import register_client, block_client
    from bot.services.billing import get_active_subscription, apply_gifts_if_no_active
    from bot.services.referrals import get_progress_for_referrer, register_referral
    from bot.services.analytics import profile_overview
"""

# Ничего не реэкспортируем — это предотвращает циклические импорты
__all__: tuple[str, ...] = ()
