import io
import sys
from .errors import *
from urllib.parse import quote_plus
from typing import Any
import asyncio


class Route:

    __MIME_TYPE = 'application/json'
    __CONTENT_TYPE = 'application/octet-stream'
    __BASE = 'https://database.deta.sh/v1/'
    __DRIVE = 'https://drive.deta.sh/v1/'
    __SINGLE_REQ_UPLOAD_SIZE = 10485760  # 10MB

    def __init__(self, deta):
        self.__session = deta.session
        self.__project_id = deta.token.split('_')[0]
        self.__base_root = self.__BASE + self.__project_id + '/'
        self.__drive_root = self.__DRIVE + self.__project_id + '/'
        self.__base_headers = {'X-API-Key': deta.token, 'Content-Type': self.__MIME_TYPE}
        self.__drive_headers = {'X-API-Key': deta.token, 'Content-Type': self.__CONTENT_TYPE}

    async def _fetch(self, base_name: str, key: str):
        ep = self.__base_root + base_name + '/items/' + key
        resp = await self.__session.get(ep, headers=self.__base_headers)
        if resp.status == 200:
            return await resp.json()
        if resp.status == 404:
            return None

    async def _fetch_all(self, base_name: str):
        ep = self.__base_root + base_name + '/query'
        resp = await self.__session.post(ep, headers=self.__base_headers)
        if resp.status == 200:
            data = await resp.json()
            return data['items']
        return None

    async def _put(self, base_name: str, json_data: dict):
        ep = self.__base_root + base_name + '/items'
        resp = await self.__session.put(ep, headers=self.__base_headers, json=json_data)
        if resp.status == 207:
            data = await resp.json()
            if 'failed' in data:
                print('Warning: some items failed because of internal processing error', file=sys.stderr)
        if resp.status == 400:
            e = await resp.json()
            raise BadRequest(e['errors'][0])
        return await resp.json()

    async def _delete(self, base_name: str, key: str):
        ep = self.__base_root + base_name + '/items/' + key
        await self.__session.delete(ep, headers=self.__base_headers)
        return key

    async def _delete_many(self, base_name: str, keys: list):
        for key in keys:
            await self._delete(base_name, key)
        return keys

    async def _insert(self, base_name: str, json_data: dict):
        ep = self.__base_root + base_name + '/items'
        resp = await self.__session.post(ep, headers=self.__base_headers, json=json_data)
        if resp.status == 201:
            return await resp.json()
        if resp.status == 409:
            raise KeyConflict('key already exists in Deta base')
        if resp.status == 400:
            raise BadRequest('invalid insert payload')

    async def _update(self, base_name: str, key: str, json_data: dict):
        ep = self.__base_root + base_name + '/items/' + key
        resp = await self.__session.patch(ep, headers=self.__base_headers, json=json_data)
        if resp.status == 200:
            return await resp.json()
        if resp.status == 404:
            raise NotFound('key does not exist in Deta Base')
        if resp.status == 400:
            raise BadRequest('invalid update payload')

    # TODO: query is not implemented yet

    # Drive API methods

    async def _fetch_file_list(
            self,
            drive_name: str,
            limit: int,
            prefix: str = None,
            last: str = None,
    ):
        if limit > 1000:
            raise ValueError('limit must be less or equal to 1000')
        if limit <= 0:
            raise ValueError('limit must be greater than 0')

        limit_ = limit or 1000

        tail = f'/files?limit={limit_}'
        if prefix:
            tail += f'&prefix={prefix}'
        if last:
            tail += f'&last={last}'
        ep = self.__drive_root + drive_name + tail

        resp = await self.__session.get(ep, headers=self.__base_headers)

        if resp.status == 200:
            return await resp.json()
        if resp.status == 400:
            error_map = await resp.json()
            raise BadRequest('\n'.join(error_map['errors']))

    async def _bulk_delete_files(self, drive_name: str, keys: list):
        ep = self.__drive_root + drive_name + '/files'
        json_data = {'names': keys}
        resp = await self.__session.delete(ep, headers=self.__base_headers, json=json_data)
        return await resp.json()

    async def _push_file(self, drive_name: str, remote_path: str, local_path: str = None, content: Any = None):
        ep = self.__drive_root + drive_name + '/files?name=' + quote_plus(remote_path)

        if local_path is not None:
            data = open(local_path, 'rb')
        elif isinstance(content, str):
            data = io.StringIO(content)
        elif isinstance(content, bytes):
            data = io.BytesIO(content)
        else:
            raise ValueError('local_path or content must be specified')

        CHUNK = data.read()

        if not len(CHUNK) > self.__SINGLE_REQ_UPLOAD_SIZE:
            resp = await self.__session.post(ep, headers=self.__drive_headers, data=CHUNK)
            if resp.status == 201:
                return await resp.json()
            elif resp.status == 400:
                error_map = await resp.json()
                raise BadRequest('\n'.join(error_map['errors']))
            else:
                error_map = await resp.json()
                raise Exception('\n'.join(error_map['errors']))
        else:
            # use multipart upload
            pass
