from .allocation import StickyIPError


class HostCheckError(StickyIPError):
    pass


class ProbeUnavailableError(HostCheckError):
    """The operating system cannot provide network probe verification."""
