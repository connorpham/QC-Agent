from fastapi import APIRouter

from app.api.deps import AppSettings, CurrentUser, TaxonomyDep
from app.ingestion.intake import ALLOWED_EXTENSIONS, ZIP_MAX_ENTRIES
from app.schemas.taxonomy import TaxonomyOut
from app.schemas.uploads import UploadLimitsOut

router = APIRouter(tags=["meta"])


@router.get("/taxonomy", response_model=TaxonomyOut)
async def get_taxonomy(_: CurrentUser, taxonomy: TaxonomyDep) -> TaxonomyOut:
    return TaxonomyOut.from_taxonomy(taxonomy)


@router.get("/upload-limits", response_model=UploadLimitsOut)
async def get_upload_limits(_: CurrentUser, settings: AppSettings) -> UploadLimitsOut:
    """The intake limits the upload wizard enforces before sending anything."""
    return UploadLimitsOut(
        max_file_mb=settings.max_upload_file_mb,
        max_batch_mb=settings.max_upload_batch_mb,
        allowed_extensions=sorted(ALLOWED_EXTENSIONS),
        zip_max_entries=ZIP_MAX_ENTRIES,
    )
