"""HTTP API. A thin layer over Services: validation, status codes and plain-language errors.

The API is reached only through the SSM tunnel (localhost), never from the internet.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import FastAPI, File, HTTPException, Path, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from voiceover_studio import __version__
from voiceover_studio.core.consent import ConsentError
from voiceover_studio.core.convert import ConversionError
from voiceover_studio.core.render import RenderError
from voiceover_studio.core.script import ScriptRefusedError, ScriptRequest
from voiceover_studio.services import OUTPUT_FILES, SampleRejectedError, Services

HexId = Annotated[str, Path(pattern=r"^[0-9a-f]{12}$")]
VoiceId = Annotated[str, Path(pattern=r"^[0-9a-f-]{36}$")]
MEDIA_TYPES = {"voiceover.wav": "audio/wav", "voiceover.srt": "application/x-subrip",
               "provenance.json": "application/json"}  # fmt: skip


class ScriptIn(BaseModel):
    description: str = Field(min_length=10, max_length=4000)
    target_seconds: float = Field(gt=0)
    audience: str = Field("general viewers", max_length=200)
    tone: str = Field("friendly and clear", max_length=200)
    language: str = "en"


class EstimateIn(BaseModel):
    script: str = Field(max_length=20000)


class PluginIn(BaseModel):
    script: str = Field(min_length=1, max_length=20000)
    language: str = "en"
    target_seconds: float | None = None
    settings: dict[str, Any] = {}


class RenderIn(BaseModel):
    voice_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    script: str = Field(min_length=1, max_length=20000)
    language: str = "en"


def create_app(services: Services) -> FastAPI:
    app = FastAPI(
        title="voiceover-studio", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json"
    )
    app.state.services = services

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/info")
    def info() -> dict[str, Any]:
        return services.info()

    # --- voices -----------------------------------------------------------------------
    @app.post("/api/voices", status_code=201)
    async def add_voice(file: Annotated[UploadFile, File()]) -> dict[str, Any]:
        data = await file.read()
        try:
            voice = services.add_voice(data)
        except SampleRejectedError as exc:
            raise HTTPException(422, {"message": "Please record again.", "problems": exc.problems}) from exc
        except (ConsentError, ConversionError) as exc:
            raise HTTPException(422, {"message": str(exc)}) from exc
        return voice.__dict__

    @app.get("/api/voices")
    def list_voices() -> list[dict[str, Any]]:
        return services.list_voices()

    @app.delete("/api/voices/{voice_id}", status_code=204)
    def delete_voice(voice_id: VoiceId) -> Response:
        services.delete_voice(voice_id)
        return Response(status_code=204)

    # --- scripts ----------------------------------------------------------------------
    @app.post("/api/scripts")
    def draft_script(body: ScriptIn) -> dict[str, Any]:
        try:
            draft = services.draft_script(ScriptRequest(**body.model_dump()))
        except ScriptRefusedError as exc:
            raise HTTPException(422, {"message": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(422, {"message": str(exc)}) from exc
        return {
            "script": draft.text,
            "words": draft.words,
            "estimated_seconds": round(draft.estimated_seconds, 1),
        }

    @app.post("/api/scripts/estimate")
    def estimate(body: EstimateIn) -> dict[str, Any]:
        draft = services.estimate(body.script)
        return {"words": draft.words, "estimated_seconds": round(draft.estimated_seconds, 1)}

    @app.post("/api/plugins/{name}")
    def run_plugin(name: str, body: PluginIn) -> dict[str, Any]:
        try:
            return services.run_plugin(name, body.script, body.language, body.target_seconds, body.settings)
        except LookupError as exc:
            raise HTTPException(404, {"message": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(422, {"message": str(exc)}) from exc

    # --- renders ----------------------------------------------------------------------
    @app.post("/api/renders", status_code=202)
    def submit_render(body: RenderIn) -> dict[str, Any]:
        if body.language not in services.tts.capabilities().languages:
            raise HTTPException(
                422, {"message": f"Language '{body.language}' isn't supported by the voice model."}
            )
        try:
            job = services.submit_render(body.voice_id, body.script, body.language)
        except (KeyError, FileNotFoundError) as exc:
            raise HTTPException(404, {"message": "Voice not found."}) from exc
        except RenderError as exc:
            raise HTTPException(422, {"message": str(exc)}) from exc
        return job.public()

    @app.get("/api/renders/{job_id}")
    def render_status(job_id: HexId) -> dict[str, Any]:
        job = services.jobs.get(job_id)
        if not job:
            raise HTTPException(404, {"message": "Job not found."})
        return job.public()

    @app.get("/api/outputs/{output_id}/{name}")
    def download(output_id: HexId, name: str) -> Response:
        if name not in OUTPUT_FILES:
            raise HTTPException(404, {"message": "Unknown file."})
        try:
            data = services.output_file(output_id, name)
        except (KeyError, FileNotFoundError) as exc:
            raise HTTPException(404, {"message": "Output not found."}) from exc
        headers = {"Content-Disposition": f'attachment; filename="{name}"'}
        return Response(data, media_type=MEDIA_TYPES[name], headers=headers)

    return app
