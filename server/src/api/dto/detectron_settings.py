from pydantic import BaseModel


class DetectronSettings(BaseModel):
    use_detectron: bool
    detectron_sensitivity: float


