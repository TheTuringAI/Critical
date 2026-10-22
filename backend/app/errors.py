from __future__ import annotations


class PipelineError(Exception):
    status_code = 500
    code = "INTERNAL_ERROR"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NoCaptionsError(PipelineError):
    status_code = 422
    code = "NO_CAPTIONS_AVAILABLE"


class VideoUnavailableError(PipelineError):
    status_code = 404
    code = "VIDEO_UNAVAILABLE"


class UpstreamError(PipelineError):
    status_code = 502
    code = "UPSTREAM_ERROR"


class ConfigurationError(PipelineError):
    status_code = 503
    code = "NOT_CONFIGURED"
