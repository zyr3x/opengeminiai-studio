import pytest
import asyncio
from app.utils.observer import ObserverManager

@pytest.fixture
def observer():
    return ObserverManager()

def test_observer_sync_subscription(observer):
    events = []
    def my_handler(payload):
        events.append(payload)

    observer.subscribe('test.event', my_handler)
    observer.notify('test.event', payload='hello')
    
    assert len(events) == 1
    assert events[0] == 'hello'

    observer.unsubscribe('test.event', my_handler)
    observer.notify('test.event', payload='world')
    assert len(events) == 1  # Should not have increased

@pytest.mark.asyncio
async def test_observer_async_notify(observer):
    events = []
    
    async def my_async_handler(payload):
        await asyncio.sleep(0.01)
        events.append(payload)

    def my_sync_handler(payload):
        events.append(payload + "_sync")

    observer.subscribe('test.async', my_async_handler)
    observer.subscribe('test.async', my_sync_handler)
    
    # notify_async should wait for both
    await observer.notify_async('test.async', payload='hello')
    
    # We can't guarantee order between sync and async in notify_async necessarily,
    # but since sync runs immediately and async is awaited, both will be done.
    assert len(events) == 2
    assert 'hello' in events
    assert 'hello_sync' in events
