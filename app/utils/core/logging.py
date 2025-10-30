VERBOSE_LOGGING = True
DEBUG_CLIENT_LOGGING = False


def log(message: str):
    """Prints a message to the console if verbose logging is enabled."""
    if VERBOSE_LOGGING:
        print(message)


def debug(message: str):
    """Prints a message to the console if debug client logging is enabled."""
    if DEBUG_CLIENT_LOGGING:
        print(message)


def set_verbose_logging(enabled: bool):
    """Sets the verbose logging status."""
    global VERBOSE_LOGGING
    VERBOSE_LOGGING = enabled
    log(f"Verbose logging has been {'enabled' if enabled else 'disabled'}.")


def set_debug_client_logging(enabled: bool):
    """Sets the debug client logging status."""
    global DEBUG_CLIENT_LOGGING
    DEBUG_CLIENT_LOGGING = enabled
    log(f"Debug client logging has been {'enabled' if enabled else 'disabled'}.")
