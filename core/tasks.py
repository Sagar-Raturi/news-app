from celery import shared_task


@shared_task
def ping():
    """Health-check task proving the Celery worker is wired up."""
    return "pong"
