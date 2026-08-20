from pydantic import BaseModel


class IdOcrResult(BaseModel):
    national_id: str | None
    national_id_valid: bool
    last_name: str | None
    first_name: str | None
    address: str | None
    date_of_birth: str | None
    gender: str | None
    series_number: str | None
