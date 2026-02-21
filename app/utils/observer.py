import asyncio
import inspect
from typing import Callable, Dict, List, Any

class ObserverManager:
    """
    Central hub for the publish-subscribe event system.
    Allows components to subscribe to named events and be notified when they occur.
    """
    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}

    def subscribe(self, event_name: str, callback: Callable) -> None:
        """
        Subscribe a callback function to a specific event.
        The callback can be synchronous or asynchronous.
        """
        if event_name not in self._subscribers:
            self._subscribers[event_name] = []
        if callback not in self._subscribers[event_name]:
            self._subscribers[event_name].append(callback)

    def unsubscribe(self, event_name: str, callback: Callable) -> None:
        """Unsubscribe a callback from an event."""
        if event_name in self._subscribers and callback in self._subscribers[event_name]:
            self._subscribers[event_name].remove(callback)

    def notify(self, event_name: str, **kwargs: Any) -> None:
        """
        Notify all subscribers of an event.
        Synchronous callbacks are executed immediately.
        Asynchronous callbacks are scheduled as background tasks on the event loop.
        """
        if event_name not in self._subscribers:
            return

        for callback in self._subscribers[event_name]:
            if inspect.iscoroutinefunction(callback):
                # We do not wait for it here, it will run in the background
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(callback(**kwargs))
                except RuntimeError:
                    # If no loop is running, we can't schedule it safely without blocking
                    asyncio.run(callback(**kwargs))
            else:
                callback(**kwargs)

    async def notify_async(self, event_name: str, **kwargs: Any) -> None:
        """
        Notify all subscribers of an event and await completion of all callbacks.
        Useful when you need to ensure all async handlers have finished processing.
        """
        if event_name not in self._subscribers:
            return

        tasks = []
        for callback in self._subscribers[event_name]:
            if inspect.iscoroutinefunction(callback):
                tasks.append(callback(**kwargs))
            else:
                # Run sync functions immediately, but we could also run them in an executor if they are blocking
                callback(**kwargs)
        
        if tasks:
            await asyncio.gather(*tasks)

# Global singleton instance
observer = ObserverManager()
