from celery import shared_task

from core.task_runner import dispatch_after_commit, execute_locked_task
from product.services.prices import recalculate_base_prices

from .services import calculate_product_prices, iter_pim_push_batches, pim_push_enabled, push_prices_to_pim


@shared_task(name='product_pricing.update_product_prices', time_limit=None, soft_time_limit=None)
def update_product_prices_task(push: bool = True) -> dict:
    """Основные цены товаров -> наценки -> (после коммита) отправка в PIM.

    Локальная часть — в одной транзакции execute_locked_task: расчётные цены
    не должны увидеть наполовину пересчитанные основные. Отправка ходит в
    сеть, поэтому уходит отдельными партиями через dispatch_after_commit —
    иначе партия могла бы стартовать против цен, которые ещё откатятся.
    """
    def _runner():
        changed = recalculate_base_prices()
        changed += calculate_product_prices()
        if push and pim_push_enabled():
            for pks in iter_pim_push_batches():
                dispatch_after_commit(push_product_prices_batch_task, pks=pks)
        return changed

    return execute_locked_task(
        task_name='product_pricing.update_product_prices',
        lock_ttl=60 * 30,
        runner=_runner,
    )


@shared_task(name='product_pricing.push_product_prices_batch', time_limit=None, soft_time_limit=None)
def push_product_prices_batch_task(pks: list[int], delay: float = 0.5) -> dict:
    return execute_locked_task(
        task_name=f'product_pricing.push_product_prices_batch:{pks[0]}-{pks[-1]}',
        lock_ttl=60 * 30,
        runner=lambda: push_prices_to_pim(pks, delay=delay),
        # Висит на PIM-задании upsertAsync; снимок пишется по принятым записям,
        # так что прерванная партия просто отправится ещё раз.
        atomic=False,
    )
