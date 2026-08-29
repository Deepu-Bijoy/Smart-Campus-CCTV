import logging

logger = logging.getLogger(__name__)

def classify_query(query: str) -> str:
    """
    Lightweight rule-based natural language search query classifier.
    Categorizes search queries into: 'identity', 'appearance', or 'incident'.
    """
    query_lower = query.lower().strip()

    # 1. Incident classifier: check for incident indicators
    incident_keywords = [
        "fight", "jump", "wall", "boundary", "restricted", "unauthorized",
        "violence", "cross", "intrud", "anomaly", "altercation", "clash"
    ]
    if any(k in query_lower for k in incident_keywords):
        logger.info(f"Query '{query}' classified as INCIDENT (due to incident keywords)")
        return "incident"

    # 2. Appearance classifier: check for clothing/context descriptors
    appearance_keywords = [
        "wearing", "shirt", "colour", "clothes", "uniform", "appearance",
        "person with", "jacket", "jeans", "pant", "hoodie", "cap", "bag",
        "car", "gate", "near", "crop", "visual"
    ]
    if any(k in query_lower for k in appearance_keywords):
        logger.info(f"Query '{query}' classified as APPEARANCE (due to appearance keywords)")
        return "appearance"

    # 3. Identity classifier: check for identity indicators or roll numbers
    identity_keywords = [
        "find", "show", "where was", "seen near", "appearances of", "student", "roll", "cs22b"
    ]
    if any(query_lower.startswith(k) for k in identity_keywords) or any(k in query_lower for k in ["student", "roll", "cs22b"]):
        logger.info(f"Query '{query}' classified as IDENTITY (due to identity indicators)")
        return "identity"

    # Default fallback
    logger.info(f"Query '{query}' falling back to default classification: APPEARANCE")
    return "appearance"
