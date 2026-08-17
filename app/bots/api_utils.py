import time
from google.api_core.exceptions import ResourceExhausted, InternalServerError, ServiceUnavailable
import google.api_core.exceptions

def call_gemini_with_retry(model, prompt, max_retries=8, initial_delay=10, log_func=print):
    """
    Calls the Gemini API with exponential backoff for rate limits and server errors.

    Note on genai.configure():
    This is called multiple times by different bots (HTML, XML, Text, QAAudit) in their __init__ methods.
    The google.generativeai library uses global state for configuration. This is currently safe because all 
    bots use the same API key. If future features require different keys per bot, this global state pattern 
    will cause a race condition and will need to be refactored to pass the client instance or key per call.
    """
    # Base delay removed because Flash models have massive RPM limits.
    # time.sleep(2.5)
    
    delay = initial_delay
    for attempt in range(max_retries):
        try:
            return model.generate_content(prompt, request_options={"timeout": 600})
        except google.api_core.exceptions.InvalidArgument as e:
            # 400 Bad Request / Invalid API Key usually shouldn't be retried blindly unless it's a transient glitch,
            # but we can log and fail fast if it's clearly an auth issue.
            log_func(f"[API Utils] InvalidArgument/400 Error: {e}")
            raise e
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "500" in error_str or "503" in error_str or "504" in error_str or "quota" in error_str.lower() or "deadline" in error_str.lower() or isinstance(e, (ResourceExhausted, InternalServerError, ServiceUnavailable)):
                if attempt < max_retries - 1:
                    log_func(f"[API Utils] Caught error '{error_str[:60]}...' (Attempt {attempt + 1}/{max_retries}). Retrying in {delay} seconds...")
                    time.sleep(delay)
                    delay *= 2  # Exponential backoff
                else:
                    log_func(f"[API Utils] Max retries reached. Failing.")
                    raise e
            else:
                # For other unexpected exceptions, log and re-raise
                log_func(f"[API Utils] Unexpected error: {e}")
                raise e
