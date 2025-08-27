from celery import shared_task

@shared_task
def refresh_views_for_room(room_id: int) -> dict:
    # Заглушка: здесь должен быть вызов userbot для получения message.views
    return {"room_id": room_id, "status": "ok"}
