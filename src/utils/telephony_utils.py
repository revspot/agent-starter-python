import re

def extract_sip_status_from_error(error: Exception) -> dict:
    """
    Extract SIP status information from TwirpError or other SIP-related exceptions.
    
    Returns a dictionary with SIP status details:
    - sip_status_code: The numeric SIP status code (e.g., 486, 503)
    - sip_status_message: The human-readable status message (e.g., "User Busy")
    - error_type: The type of error (e.g., "TwirpError")
    - raw_error: The original error message
    """
    sip_info = {
        "sip_status_code": None,
        "sip_status_message": None,
        "error_type": type(error).__name__,
        "raw_error": str(error)
    }
    
    error_str = str(error)
    
    # Check if it's a TwirpError with SIP status information
    if "TwirpError" in error_str and "sip status" in error_str.lower():
        # Extract SIP status code using regex
        sip_code_match = re.search(r'sip status:\s*(\d+)', error_str)
        if sip_code_match:
            sip_info["sip_status_code"] = int(sip_code_match.group(1))
        
        # Extract SIP status message
        sip_message_match = re.search(r'sip status:\s*\d+:\s*([^,]+)', error_str)
        if sip_message_match:
            sip_info["sip_status_message"] = sip_message_match.group(1).strip()
    
    # Check for metadata with SIP information
    if hasattr(error, 'metadata') and error.metadata:
        metadata = error.metadata
        if 'sip_status' in metadata:
            sip_info["sip_status_message"] = metadata['sip_status']
        if 'sip_status_code' in metadata:
            sip_info["sip_status_code"] = int(metadata['sip_status_code'])
    
    return sip_info

def identify_call_status(error: Exception) -> str:
    """
    Simple function to identify if a SIP call failed due to no-answer or busy status.
    
    Args:
        error: The exception that occurred during SIP participant creation
        
    Returns:
        str: One of the following:
        - "busy" - User is busy (486, 600)
        - "no_answer" - No answer (408, 480, 504, 603, 604)
        - "other" - Other error types
        - "unknown" - Could not determine status
    """
    sip_info = extract_sip_status_from_error(error)
    status_code = sip_info.get('sip_status_code')
    
    if not status_code:
        return "unknown"
    
    # Busy status codes
    if status_code in [486, 600]:
        return "busy"
    
    # No answer status codes
    if status_code in [408, 480, 504, 603, 604]:
        return "no_answer"

    if status_code in [500, 501, 502, 503]:
        return "failed"
    
    # All other status codes
    return "other"
