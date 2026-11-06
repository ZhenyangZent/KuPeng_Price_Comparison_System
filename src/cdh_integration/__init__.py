"""I01 synthetic-only adapter between B01 observations and the frozen C01 core."""

from .adapter import QualificationFixture, SyntheticObservation
from .pipeline import IntegrationResult, SyntheticIntegrationPipeline

__all__ = [
    "IntegrationResult",
    "QualificationFixture",
    "SyntheticIntegrationPipeline",
    "SyntheticObservation",
]

