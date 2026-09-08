"""
Network degradation simulation package.
"""
from .link_quality import NetworkQuality, DegradationEvent, NetworkQualitySimulator

__all__ = ["NetworkQuality", "DegradationEvent", "NetworkQualitySimulator"]
