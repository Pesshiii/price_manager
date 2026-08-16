import httpx
from typing import List, Dict, Protocol, Optional, Any
from pydantic import BaseModel
from enum import Enum
from price_manager.settings import PIM_TOKEN, PIM_HOST

token = PIM_TOKEN
if token is None:
    raise ValueError('No token for PIM connection')
host = PIM_HOST
if host is None:
    raise ValueError('No host for PIM connection')


class Method(Protocol):
    def get(self, prefix: str, headers:Dict[str, str], *args, **kwargs)->httpx.Response|None:
        ...
    def post(self, prefix:str, headers:Dict[str, str])->httpx.Response|None:
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
    payload: Optional[Dict[str, Dict[str, str]|str]] = None
    def get(self, prefix: str, headers: Dict[str, str])->httpx.Response:
        params = dict()
        if self.select:
            params.update({'select':','.join(self.select)})
        if self.where:
            for i, where in enumerate(self.where):
                params.update(where.get(i))
        return httpx.get(url = prefix + self.name, params=params, headers=headers)
    def post(self, prefix: str, headers: Dict[str, str])->httpx.Response|None:
        return httpx.post(url=prefix + self.name, headers=headers, json=self.payload)

class Entity(BaseModel):
    name: str
    id: str
    def get(self, prefix: str, headers: Dict[str, str])->httpx.Response:
        return httpx.get(url=prefix+self.name+'/' + self.id, headers=headers)
    def post(self, prefix: str, headers: Dict[str, str])->httpx.Response|None:
        raise NotImplementedError('No post for Entity request')

class UpsertAsync(BaseModel):
    payload: Any
    def get(self, prefix: str, headers: Dict[str, str])->httpx.Response|None:
        raise NotImplementedError('No get for UpsertAsync request')
    def post(self, prefix:str, headers:Dict[str, str])->httpx.Response:
        return httpx.post(url=prefix + 'upsertAsync', headers=headers, json=self.payload)

class Job(BaseModel):
    id: str
    def get(self, prefix:str, headers:Dict[str, str])->httpx.Response:
            return httpx.get(url= prefix + 'Job/' + self.id, headers=headers)
    def post(self, prefix: str, headers: Dict[str, str])->httpx.Response|None:
        raise NotImplementedError('No post for Job request')

class SiteAPI(BaseModel):
    token:  str
    host: str
    def get(self, method: Method):
        headers = {
            'Accept': 'application/json',
            'Authorization-Token': self.token
        } 
        response = method.get(prefix=f'https://{self.host}/api/', headers=headers)
        if response is None:
            raise ValueError('Empty response')
        response.raise_for_status()
        return response.json()
    def post(self, method: Method):
            headers = {
                'Accept': 'application/json',
                'Authorization-Token': self.token
            } 
            response = method.post(prefix=f'https://{self.host}/api/', headers=headers)
            if response is None:
                raise ValueError('Empty response')
            response.raise_for_status()
            return response.json()
    
site = SiteAPI(token=token, host=host)
