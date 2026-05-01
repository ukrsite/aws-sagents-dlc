import logging
import time
from typing import Optional, Dict, Any

# Setup local logging
logger = logging.getLogger(__name__)

class ExamplenameError(Exception):
    """Base exception for strands-evals errors."""
    pass

class ConnectionError(ExamplenameError):
    """Raised when the simulated service is unreachable."""
    pass

class Client:
    """
    The primary interface for the strands-evals service.
    
    Usage:
        >>> from strands-evals import Client
        >>> with Client(api_key="secret") as client:
        >>>     client.sync_data({"id": 123})
    """

    def __init__(self, api_key: str, timeout: int = 30):
        self.api_key = api_key
        self.timeout = timeout
        self.is_connected = False
        self._session_id: Optional[str] = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    def connect(self) -> bool:
        """Simulates establishing a connection to a remote backend."""
        logger.info("Initializing connection to backend...")
        time.sleep(0.5)  # Simulate network latency
        self._session_id = f"sess_{int(time.time())}"
        self.is_connected = True
        print(f"[+] strands-evals: Connected with session {self._session_id}")
        return True

    def sync_data(self, payload: Dict[str, Any]) -> Dict[str, str]:
        """Simulates sending data to a remote endpoint."""
        if not self.is_connected:
            raise ConnectionError("Client must be connected before syncing data.")
        
        logger.debug(f"Syncing payload: {payload}")
        # Realistic dummy response
        return {"status": "success", "timestamp": str(time.time())}

    def disconnect(self):
        """Cleanly closes the session."""
        self.is_connected = False
        self._session_id = None
        print("[-] strands-evals: Connection closed.")

def start_service(api_key: str):
    """Helper function for quick-start usage."""
    client = Client(api_key=api_key)
    client.connect()
    return client