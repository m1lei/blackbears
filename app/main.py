import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session, init_db
from app.models import Base, Recording, RecordingStatus

CHUNK_SIZE = 1024 * 1024
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
router = APIRouter()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    storage_dir = Path(settings.audio_storage_dir)
    storage_dir.mkdir(parents=True, exist_ok=True)
    if settings.database_url.startswith("sqlite:///"):
        db_path = Path(settings.database_url.removeprefix("sqlite:///"))
        db_path.parent.mkdir(parents=True, exist_ok=True)

    init_db(settings)
    from app import db

    Base.metadata.create_all(db.engine)

    app = FastAPI(title="Blackbears", version="0.1.0")
    app.state.settings = settings
    app.state.storage_dir = storage_dir
    app.include_router(router)
    return app


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/")
def index(request: Request, session: Session = Depends(get_session)):
    recordings = session.scalars(
        select(Recording).order_by(Recording.created_at.desc(), Recording.id.desc())
    ).all()
    return templates.TemplateResponse(
        request, "index.html", {"recordings": [r.to_dict() for r in recordings]}
    )


@router.get("/recordings")
def list_recordings(session: Session = Depends(get_session)) -> list[dict]:
    recordings = session.scalars(
        select(Recording).order_by(Recording.created_at.desc(), Recording.id.desc())
    ).all()
    return [r.to_dict() for r in recordings]


@router.post("/recordings", status_code=201)
async def upload_recording(
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    settings: Settings = request.app.state.settings
    storage_dir = Path(settings.audio_storage_dir)

    original_name = file.filename or ""
    ext = Path(original_name).suffix.lower()
    if not ext:
        raise HTTPException(status_code=400, detail="Не указано расширение файла")
    allowed = [e.lower() for e in settings.allowed_extensions]
    if ext not in allowed:
        raise HTTPException(
            status_code=415,
            detail=f"Неподдерживаемый формат {ext!r}. Разрешены: {', '.join(allowed)}",
        )

    stored_filename = f"{uuid.uuid4().hex}{ext}"
    final_path = storage_dir / stored_filename
    tmp_path = storage_dir / f".tmp-{stored_filename}"

    size = 0
    try:
        with open(tmp_path, "wb") as out:
            while chunk := await file.read(CHUNK_SIZE):
                size += len(chunk)
                if size > settings.max_file_size_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Файл превышает лимит {settings.max_file_size_bytes} байт",
                    )
                out.write(chunk)
        os.replace(tmp_path, final_path)
    except HTTPException:
        tmp_path.unlink(missing_ok=True)
        raise
    except OSError as exc:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Не удалось сохранить файл") from exc

    recording = Recording(
        original_filename=original_name,
        stored_filename=stored_filename,
        file_size=size,
        status=RecordingStatus.UPLOADED.value,
    )
    session.add(recording)
    try:
        session.commit()
    except Exception:
        session.rollback()
        final_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Не удалось сохранить запись в БД")
    session.refresh(recording)
    return JSONResponse(status_code=201, content=recording.to_dict())


app = create_app()
