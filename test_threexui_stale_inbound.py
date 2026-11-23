"""رفع باگ «Something went wrong (inbound N: record not found)» در ساخت کانفیگ 3X-UI."""
import asyncio, json
import pytest
from panel_providers.threexui_provider import ThreeXUIProvider
from panel_providers.base import PanelError


class _Resp:
    def __init__(self, data, status=200):
        self._d, self.status = data, status
    async def json(self): return self._d
    async def text(self): return json.dumps(self._d)
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False


class _Session:
    def __init__(self, live_ids, posted):
        self.live_ids, self.posted = live_ids, posted
    def get(self, url, **kw):
        return _Resp({"success": True, "obj": [{"id": i, "remark": f"r{i}", "protocol": "vless", "port": 1000 + i} for i in self.live_ids]})
    def post(self, url, json=None, **kw):
        self.posted.append(json)
        return _Resp({"success": True})
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False


def _provider(inbound_ids, live_ids, posted):
    server = {"id": 1, "api_url": "http://x", "api_password": "t", "xui_inbound_ids": json.dumps(inbound_ids),
              "xui_inbound_id": None, "xui_sub_base_url": "http://x/sub", "start_on_first_use": 0}
    p = ThreeXUIProvider(server)
    p._session = lambda: _Session(live_ids, posted)
    return p


def test_stale_inbound_is_dropped_and_creation_continues():
    posted = []
    p = _provider([50, 3], [3, 4], posted)
    res = asyncio.run(p.create_user("u1", 10, 30))
    assert posted[0]["inboundIds"] == [3]
    assert res.username == "u1"


def test_all_stale_gives_clear_error_with_available_inbounds():
    posted = []
    p = _provider([50], [3, 4], posted)
    with pytest.raises(PanelError) as ei:
        asyncio.run(p.create_user("u1", 10, 30))
    msg = str(ei.value)
    assert "#50" in msg and "#3" in msg and "#4" in msg
    assert posted == []


def test_valid_inbounds_unchanged():
    posted = []
    p = _provider([3, 4], [3, 4, 5], posted)
    asyncio.run(p.create_user("u1", 10, 30))
    assert posted[0]["inboundIds"] == [3, 4]
