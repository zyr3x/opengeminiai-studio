from app.config import config
def log(message: str):
    if config.VERBOSE_LOGGING:
        print(message)
def debug(message: str):
    if config.DEBUG_CLIENT_LOGGING:
        print(message)
def set_verbose_logging(enabled: bool):
    config.set_param('VERBOSE_LOGGING', enabled)
    log(f"Verbose logging has been {'enabled' if enabled else 'disabled'}.")
def set_debug_client_logging(enabled: bool):
    config.set_param('DEBUG_CLIENT_LOGGING', enabled)
    log(f"Debug client logging has been {'enabled' if enabled else 'disabled'}.")