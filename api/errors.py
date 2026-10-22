from fastapi import HTTPException


def api_error(status_code: int, code: str, message: str, field: str | None = None) -> None:
    error = {"code": code, "message": message}
    if field is not None:
        error["field"] = field
    raise HTTPException(status_code=status_code, detail={"error": error})
