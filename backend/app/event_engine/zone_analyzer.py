import json

class ZoneAnalyzer:
    @staticmethod
    def parse_coordinates(coords_str: str) -> list:
        try:
            return json.loads(coords_str)
        except Exception:
            return []

    @classmethod
    def is_point_inside_zone(cls, x: float, y: float, zone_coords: list, geometry_type: str) -> bool:
        if not zone_coords:
            return False
        if geometry_type == 'polygon':
            return cls._point_in_polygon(x, y, zone_coords)
        return False

    @classmethod
    def does_segment_cross_zone(cls, p1: tuple, p2: tuple, zone_coords: list, geometry_type: str) -> bool:
        if not zone_coords or len(zone_coords) < 2:
            return False
        if geometry_type == 'line':
            return cls._line_intersection(p1, p2, tuple(zone_coords[0]), tuple(zone_coords[1]))
        elif geometry_type == 'polygon':
            num = len(zone_coords)
            for i in range(num):
                a = tuple(zone_coords[i])
                b = tuple(zone_coords[(i + 1) % num])
                if cls._line_intersection(p1, p2, a, b):
                    return True
        return False

    @staticmethod
    def _point_in_polygon(x: float, y: float, polygon: list) -> bool:
        num = len(polygon)
        inside = False
        p1x, p1y = polygon[0]
        for i in range(num + 1):
            p2x, p2y = polygon[i % num]
            if y > min(p1y, p2y):
                if y <= max(p1y, p2y):
                    if x <= max(p1x, p2x):
                        if p1y != p2y:
                            xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                        if p1x == p2x or x <= xinters:
                            inside = not inside
            p1x, p1y = p2x, p2y
        return inside

    @staticmethod
    def _line_intersection(p1: tuple, p2: tuple, p3: tuple, p4: tuple) -> bool:
        def ccw(A, B, C):
            return (C[1]-A[1]) * (B[0]-A[0]) > (B[1]-A[1]) * (C[0]-A[0])
        return ccw(p1,p3,p4) != ccw(p2,p3,p4) and ccw(p1,p2,p3) != ccw(p1,p2,p4)
