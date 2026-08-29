import math

class TrajectoryAnalyzer:
    @staticmethod
    def calculate_velocity(p1: tuple, p2: tuple, t1: float, t2: float) -> float:
        dt = t2 - t1
        if dt <= 0:
            return 0.0
        dist = math.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)
        return dist / dt

    @staticmethod
    def get_direction(p1: tuple, p2: tuple) -> str:
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        if abs(dx) > abs(dy):
            return "East" if dx > 0 else "West"
        else:
            return "South" if dy > 0 else "North"

    @classmethod
    def analyze_trajectory(cls, detections: list) -> dict:
        if not detections or len(detections) < 2:
            return {
                "history": [(d["x"], d["y"]) for d in detections] if detections else [],
                "velocity": 0.0,
                "direction": "Static"
            }

        history = [(d["x"], d["y"]) for d in detections]
        first, last = detections[0], detections[-1]
        p1 = (first["x"], first["y"])
        p2 = (last["x"], last["y"])
        
        velocity = cls.calculate_velocity(p1, p2, first["timestamp_seconds"], last["timestamp_seconds"])
        direction = cls.get_direction(p1, p2)

        return {
            "history": history,
            "velocity": velocity,
            "direction": direction
        }
