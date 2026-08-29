import re
from typing import Dict, Any

class QueryParser:
    def __init__(self):
        self.class_keywords = {
            "person": ["person", "man", "woman", "boy", "girl", "guy", "people", "pedestrian"],
            "car": ["car", "vehicle", "sedan", "suv"],
            "motorcycle": ["motorcycle", "bike", "motorbike"],
            "bus": ["bus"],
            "truck": ["truck", "lorry"],
            "bicycle": ["bicycle", "cycle"],
            "backpack": ["backpack", "bag", "pack"],
            "handbag": ["handbag", "purse"],
            "suitcase": ["suitcase", "luggage"],
            "cell phone": ["phone", "cellphone", "mobile"],
            "laptop": ["laptop", "computer"]
        }
        
    def parse(self, query: str) -> Dict[str, Any]:
        """
        Parses a natural language query to extract search parameters, constraints, and intent.
        """
        query_lower = query.lower()
        result = {
            "query": query,
            "object_class": None,
            "temporal_constraints": None,
            "intent": "appearance"
        }
        
        # 1. Resolve Target Object Class
        for obj_class, keywords in self.class_keywords.items():
            if any(kw in query_lower for kw in keywords):
                result["object_class"] = obj_class
                break
                
        # 2. Extract Temporal Constraints
        time_match = re.search(r'(after|before|around|at)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm|am\.|pm\.)?', query_lower)
        if time_match:
            relation = time_match.group(1)
            hour = int(time_match.group(2))
            minute = int(time_match.group(3)) if time_match.group(3) else 0
            meridiem = time_match.group(4)
            
            if meridiem:
                meridiem_clean = meridiem.replace('.', '').strip()
                if meridiem_clean == "pm" and hour < 12:
                    hour += 12
                elif meridiem_clean == "am" and hour == 12:
                    hour = 0
            elif hour < 12 and relation in ["after", "before"] and hour >= 1 and hour <= 8:
                hour += 12
                
            result["temporal_constraints"] = {
                "relation": relation,
                "hour": hour,
                "minute": minute,
                "seconds_of_day": hour * 3600 + minute * 60
            }
            result["intent"] = "temporal"
            
        # 3. Determine Search Intent
        person_terms = ["person", "man", "woman", "boy", "girl", "guy"]
        if any(term in query_lower for term in person_terms):
            result["intent"] = "identity" if result["intent"] != "temporal" else "temporal"
            
        colors = ["blue", "red", "white", "black", "green", "yellow", "orange", "grey", "gray", "dark", "light"]
        if any(color in query_lower for color in colors):
            result["intent"] = "appearance"
            
        zone_keywords = ["fence", "jump", "incident", "restricted", "intrusion", "zone", "boundary"]
        if any(zk in query_lower for zk in zone_keywords):
            result["intent"] = "zone"
            
        return result
