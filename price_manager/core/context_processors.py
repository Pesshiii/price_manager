from core.models import PersistentNotification


def persistent_notifications(request):
    if not request.user.is_authenticated:
        return {"persistent_notifications": []}

    notifications = (
        PersistentNotification.objects
        .filter(user=request.user)
        .order_by('-created_at')[:30]
    )
    return {"persistent_notifications": notifications}
