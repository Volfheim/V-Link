import asyncio
import time

from network.client import TransferClient


def test_reachable_endpoint_probes_run_concurrently():
    client = TransferClient()
    calls = []

    async def fake_ping(host, port, timeout, retries):
        calls.append((host, port, timeout, retries))
        if host == "192.168.1.20":
            await asyncio.sleep(0.01)
            return True
        await asyncio.sleep(0.4)
        return False

    client.ping = fake_ping
    started = time.perf_counter()
    selected = asyncio.run(
        client.pick_reachable_endpoint(
            [("10.8.0.2", 8765), ("192.168.1.20", 8765)],
            timeout=0.5,
        )
    )
    elapsed = time.perf_counter() - started

    assert selected == ("192.168.1.20", 8765)
    assert elapsed < 0.15
    assert {call[:2] for call in calls} == {
        ("10.8.0.2", 8765),
        ("192.168.1.20", 8765),
    }
    assert all(call[3] == 1 for call in calls)


def test_single_endpoint_skips_redundant_probe():
    client = TransferClient()

    async def unexpected_ping(*_args, **_kwargs):
        raise AssertionError("A selected endpoint must not be probed again")

    client.ping = unexpected_ping
    selected = asyncio.run(
        client.pick_reachable_endpoint([("192.168.1.20", 8765)], timeout=0.5)
    )

    assert selected == ("192.168.1.20", 8765)
