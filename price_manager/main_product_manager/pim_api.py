import httpx
import json
from urllib.parse import urlencode
from dataclasses import  dataclass
from typing import List, Dict, Protocol, Optional
from pydantic import BaseModel
from enum import Enum

token = "dGlyYWRvOjkyNjFlZDE2YzYxMTFhNTgyMjdiZjdhMjE1ZTljODFj"
host = "pim.tirado.kz"


class Method(Protocol):
    def get(self, prefix: str, headers:Dict[str, str], *args, **kwargs)->httpx.Response:
      ...


class Where(BaseModel):
    attribute: str
    type: str
    value: Optional[str] = None
    isAttribute: Optional[bool] = None
    def get(self, num)->Dict[str, str|bool]:
        def prefix(attr: str)->str:
            return f'where[{num}][{attr}]'
        result: Dict[str, str|bool] = {prefix('attribute'):self.attribute, prefix('type'):self.type}
        if not self.value is None:
            result.update({prefix('value'):self.value})
        if not self.isAttribute is None:
            result.update({prefix('isAttribute'):self.isAttribute})
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
    def get(self, prefix: str, headers: Dict[str, str])->httpx.Response:
        params = dict()
        if self.select:
            params.update({'select':','.join(self.select)})
        if self.where:
            for i, where in enumerate(self.where):
                params.update(where.get(i))
        return httpx.get(url = prefix + self.name, params=params, headers=headers)

class UpsertAsync(BaseModel):
    payload: List[Dict[str, str|Dict[str,str]]]
    def get(self, prefix:str, headers:Dict[str, str])->httpx.Response:
        return httpx.post(url=prefix + 'upsertAsync', headers=headers, json=self.payload)

class Job(BaseModel):
    id: str
    def get(self, prefix:str, headers:Dict[str, str])->httpx.Response:
            return httpx.get(url= prefix + 'Job/' + self.id, headers=headers)

class SiteAPI(BaseModel):
    token:  str
    host: str
    def get(self, method: Method):
        headers = {
            'Accept': 'application/json',
            'Authorization-Token': self.token
        } 
        response = method.get(prefix=f'https://{self.host}/api/', headers=headers)
        response.raise_for_status()
        return response.json()
    
site = SiteAPI(token=token, host=host)
