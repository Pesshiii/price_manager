import httpx
import json
from urllib.parse import urlencode
from dataclasses import  dataclass
from typing import List, Dict, Protocol, Optional, Any
from pydantic import BaseModel
from enum import Enum
from django.conf import settings

token = settings.PIM_TOKEN
host = settings.PIM_HOST


class Method(Protocol):
    def get(self, prefix: str, headers: Dict[str, str], timeout: float = 0.5, *args, **kwargs) -> httpx.Response:
      ...


class Where(BaseModel):
    attribute: str
    type: str
    value: Optional[str] = None
    isAttribute: Optional[bool] = None
    def get(self, num) -> Dict[str, str]:
        def prefix(attr: str) -> str:
            return f'where[{num}][{attr}]'
        result: Dict[str, Any] = {prefix('attribute'): self.attribute, prefix('type'): self.type}
        if self.value is not None:
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
    name: str
    select: Optional[List[str]] = None
    where: Optional[List[Where]] = None
    ordering: Optional[Ordering] = None
    def get(self, prefix: str, headers: Dict[str, str], timeout: float = 5.0) -> httpx.Response:
        params = dict()
        if self.select:
            params.update({'select':','.join(self.select)})
        if self.where:
            for i, where in enumerate(self.where):
                params.update(where.get(i))
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

    def get(self, method: Method):
        headers = {
            'Accept': 'application/json',
            'Authorization-Token': self.token
        }
        response = method.get(prefix=f'https://{self.host}/api/', headers=headers, timeout=self.timeout)
        if settings.DEBUG:
            print(f'[PIM] {response.request.method} {response.request.url}')
        response.raise_for_status()
        return response.json()

    def download(self, method: Method) -> bytes:
        headers = {'Authorization-Token': self.token}
        response = method.get(prefix=f'https://{self.host}/api/', headers=headers)
        if settings.DEBUG:
            print(f'[PIM] {response.request.method} {response.request.url}')
        response.raise_for_status()
        return response.content

site = SiteAPI(token=f'{token}', host=f'{host}')


