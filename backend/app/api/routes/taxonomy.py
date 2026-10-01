from fastapi import APIRouter

from app.api.deps import CurrentUser, TaxonomyDep
from app.schemas.taxonomy import TaxonomyOut

router = APIRouter(tags=["meta"])


@router.get("/taxonomy", response_model=TaxonomyOut)
async def get_taxonomy(_: CurrentUser, taxonomy: TaxonomyDep) -> TaxonomyOut:
    return TaxonomyOut.from_taxonomy(taxonomy)
