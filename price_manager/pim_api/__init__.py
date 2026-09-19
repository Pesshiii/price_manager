import json
import time
from typing import List, Dict, Protocol, Optional, Any, Union
from enum import Enum

import httpx
from pydantic import BaseModel


class Method(Protocol):
    def get(self, prefix: str, headers: Dict[str, str], timeout: float = 0.5, *args, **kwargs) -> httpx.Response:
      ...


class Where(BaseModel):
    """Одно условие отбора в списочном запросе.

    `value` бывает и списком: типы вроде `linkedWith` и `in` отбирают по набору
    id, а не по одному. PIM ждёт их в PHP-нотации массива — `where[0][value][]`
    повторяется на каждый элемент, — поэтому у ключа появляется `[]`, а httpx
    раскладывает список в повторяющийся параметр. Со скалярным `value` ключ
    остаётся прежним: иначе поломались бы все существующие вызовы с `equals`.
    """

    attribute: str
    type: str
    value: Optional[Union[str, List[str]]] = None
    isAttribute: Optional[bool] = None

    def get(self, num) -> Dict[str, Any]:
        def prefix(attr: str) -> str:
            return f'where[{num}][{attr}]'
        result: Dict[str, Any] = {prefix('attribute'): self.attribute, prefix('type'): self.type}
        if self.value is not None:
            if isinstance(self.value, (list, tuple)):
                result[f"{prefix('value')}[]"] = list(self.value)
            else:
                result[prefix('value')] = self.value
        if self.isAttribute is not None:
            result[prefix('isAttribute')] = self.isAttribute
        return result

class Asc(Enum):
    ASC=True
    DESC=False

class Ordering(BaseModel):
    sortBy: str
    asc: Asc


class EntityList(BaseModel):
    """Списочный запрос к PIM.

    Ответ приходит как {'total': N, 'list': [...]}, и без offset/maxSize PIM
    отдаёт ПЕРВУЮ СТРАНИЦУ размера по умолчанию — молча. Запрос, у которого
    совпадений больше страницы, выглядит успешным и при этом неполон; именно
    так выглядит «категория на 500 товаров вернула 20». Существующие вызовы
    ищут по `number equals`, где ожидается 0-1 совпадение, поэтому их это не
    задевало, — но любой широкий отбор задевает.

    Для полного набора берите fetch_list(): он проходит страницы и честно
    сообщает, если набор пришлось урезать.
    """

    name: str
    select: Optional[List[str]] = None
    where: Optional[List[Where]] = None
    ordering: Optional[Ordering] = None
    offset: Optional[int] = None
    maxSize: Optional[int] = None

    def get(self, prefix: str, headers: Dict[str, str], timeout: float = 5.0) -> httpx.Response:
        params: Dict[str, Any] = dict()
        if self.select:
            params.update({'select':','.join(self.select)})
        if self.where:
            for i, where in enumerate(self.where):
                params.update(where.get(i))
        if self.offset is not None:
            params['offset'] = self.offset
        if self.maxSize is not None:
            params['maxSize'] = self.maxSize
        if self.ordering is not None:
            params['sortBy'] = self.ordering.sortBy
            params['asc'] = self.ordering.asc.value
        return httpx.get(url=prefix + self.name, params=params, headers=headers, timeout=timeout)

class Entity(BaseModel):
    name: str
    id: str
    def get(self, prefix: str, headers: Dict[str, str], timeout: float = 5.0) -> httpx.Response:
        return httpx.get(url=f'{prefix}{self.name}/{self.id}', headers=headers, timeout=timeout)

class UpsertAsync(BaseModel):
    payload: Any
    def get(self, prefix: str, headers: Dict[str, str], timeout: float = 5.0) -> httpx.Response:
        return httpx.post(url=prefix + 'upsertAsync', headers=headers, json=self.payload, timeout=timeout)

class Job(BaseModel):
    id: str
    def get(self, prefix: str, headers: Dict[str, str], timeout: float = 5.0) -> httpx.Response:
        return httpx.get(url=prefix + 'Job/' + self.id, headers=headers, timeout=timeout)

class ContributorProduct(BaseModel):
    """Unreachable against the current PIM — kept pending confirmation.

    Probed 2026-09-11: both /api/ContributorProduct and
    /api/ContributorProduct/{id} return 404, identical to a deliberately
    nonexistent entity, while Product/PriceManagerProduct/Category/File/Job all
    return 401. The whole family went at once — Contributor, ContributorCategory,
    ContributorBrand, Supplier and ProductFamily also 404 — which is what a
    disabled *module* looks like from outside, and is indistinguishable from the
    entities having been removed without a working API token to check metadata.

    Nothing in this repo calls this class. Confirm in the PIM admin UI which of
    the two it is before deleting it.
    """
    id: str
    def get(self, prefix: str, headers: Dict[str, str], timeout: float = 5.0) -> httpx.Response:
        return httpx.get(url=prefix + 'ContributorProduct/' + self.id, headers=headers, timeout=timeout)

class FileRecord(BaseModel):
    id: str
    def get(self, prefix: str, headers: Dict[str, str], timeout: float = 5.0) -> httpx.Response:
        return httpx.get(url=prefix + 'File/' + self.id, headers=headers, timeout=timeout)

class Download(BaseModel):
    file_name: str
    def get(self, prefix: str, headers: Dict[str, str], timeout: float = 60.0) -> httpx.Response:
        base = prefix.split('/api/')[0]
        return httpx.get(url=f'{base}/downloads/{self.file_name}', headers=headers, timeout=timeout, follow_redirects=True)

class SiteAPI(BaseModel):
    token: str
    host: str
    timeout: float = 5.0
    debug: bool = False

    def get(self, method: Method, timeout: Optional[float] = None):
        """`timeout` перекрывает SiteAPI.timeout на один вызов.

        Нужно интерактивным путям: 5 секунд по умолчанию разумны для фоновой
        задачи и неприемлемы для клика по фильтру, где столько же секунд
        страница просто стоит. Вызов без аргумента ведёт себя как раньше.
        """
        headers = {
            'Accept': 'application/json',
            'Authorization-Token': self.token
        }
        response = method.get(
            prefix=f'https://{self.host}/api/',
            headers=headers,
            timeout=self.timeout if timeout is None else timeout,
        )
        if self.debug:
            print(f'[PIM] {response.request.method} {response.request.url}')
        response.raise_for_status()
        return response.json()

    def download(self, method: Method) -> bytes:
        headers = {'Authorization-Token': self.token}
        response = method.get(prefix=f'https://{self.host}/api/', headers=headers)
        if self.debug:
            print(f'[PIM] {response.request.method} {response.request.url}')
        response.raise_for_status()
        return response.content


class ListResult(BaseModel):
    """Результат полного списочного запроса.

    `truncated` — главное поле. Обрезанный набор от полного по одному только
    списку не отличить, а молча вернуть префикс — ровно та ошибка, ради
    которой заведён offset/maxSize. Вызывающий обязан на это смотреть и
    сказать пользователю, а не делать вид, что нашлось именно столько.
    """

    total: int
    items: List[Dict[str, Any]]
    truncated: bool


def fetch_list(
    site: 'SiteAPI',
    query: EntityList,
    page_size: int = 200,
    max_items: Optional[int] = None,
    timeout: Optional[float] = None,
) -> ListResult:
    """Проходит страницы списочного запроса и собирает набор целиком.

    Голый site.get(EntityList(...)) отдаёт первую страницу и молчит об этом.
    Здесь мы идём по offset, пока не выберем total или не упрёмся в max_items,
    и в обоих случаях говорим правду через ListResult.truncated.

    `offset`/`maxSize` у переданного query игнорируются — страницами управляет
    эта функция. Всё остальное (name, select, where, ordering) идёт как есть.

    Пустая страница при недобранном total обрывает цикл: PIM либо
    рассогласовался, либо набор поменялся между страницами, и крутиться на
    месте здесь хуже, чем вернуть неполный набор с truncated=True.
    """
    items: List[Dict[str, Any]] = []
    total = 0
    offset = 0

    while True:
        page = query.model_copy(update={'offset': offset, 'maxSize': page_size})
        response = site.get(page, timeout=timeout)
        total = int(response.get('total') or 0)
        batch = response.get('list') or []
        if not batch:
            break

        items.extend(batch)
        if max_items is not None and len(items) >= max_items:
            del items[max_items:]
            break

        offset += len(batch)
        if offset >= total:
            break

    # len < total покрывает оба случая: и упёрлись в max_items, и PIM отдал
    # меньше, чем обещал в total.
    return ListResult(total=total, items=items, truncated=len(items) < total)


PIM_JOB_TERMINAL_STATUSES = {'Success', 'Failed', 'Canceled'}


def upsert_async(site: SiteAPI, items: List[Dict[str, Any]], poll_interval: float = 1.0, timeout: float = 60.0) -> List[Dict[str, Any]]:
    """POST a batch of {'entity': <EntityName>, 'payload': {...}} items to
    upsertAsync and poll the resulting Job until it reaches a terminal status.

    Job.payload just echoes back the request; the actual per-item outcome is
    a JSON-encoded string in Job.message, one entry per input item in the
    same order, e.g. {'status': 'Created', 'stored': True,
    'entity': 'PriceManagerProduct', 'id': '...'} or, for an item PIM rejects,
    {'status': 'Failed', 'stored': False, 'code': 400, 'message': 'Validation
    failed. ...'} with no 'id' — while the job itself still ends as Success.
    Returns that parsed list.

    Raises TimeoutError if the job doesn't reach a terminal status within
    `timeout` seconds, RuntimeError if the job itself ends as Failed/Canceled
    or its message isn't parseable JSON (as opposed to individual items
    failing, which is reported per-item in the returned list).
    """
    if not items:
        return []
    response = site.get(UpsertAsync(payload=items))
    job_id = response['jobId']

    deadline = time.monotonic() + timeout
    job: Dict[str, Any] = {}
    status = None
    while True:
        job = site.get(Job(id=job_id))
        status = job.get('status')
        if status in PIM_JOB_TERMINAL_STATUSES:
            break
        if time.monotonic() > deadline:
            raise TimeoutError(
                f'PIM upsertAsync job {job_id} did not finish within {timeout}s (last status={status})'
            )
        time.sleep(poll_interval)

    if site.debug:
        print(f'[PIM] job {job_id} full response={job!r}')

    if status != 'Success':
        raise RuntimeError(f'PIM upsertAsync job {job_id} ended with status={status}: {job.get("message")}')

    message = job.get('message')
    if not message:
        return []
    try:
        results = json.loads(message)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f'PIM upsertAsync job {job_id}: unparseable message: {message!r:.500}') from exc
    if not isinstance(results, list):
        raise RuntimeError(f'PIM upsertAsync job {job_id}: message is not a list: {results!r:.500}')
    return results
