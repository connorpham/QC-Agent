from pydantic import BaseModel

from app.ingestion.taxonomy import Taxonomy


class DocTypeOut(BaseModel):
    key: str
    id: str
    title: str
    required: bool
    normalize: bool
    multi: bool


class FolderOut(BaseModel):
    id: str
    dir: str
    stage: str
    doc_types: list[DocTypeOut]


class TaxonomyOut(BaseModel):
    version: int
    folders: list[FolderOut]

    @classmethod
    def from_taxonomy(cls, taxonomy: Taxonomy) -> "TaxonomyOut":
        return cls(
            version=taxonomy.version,
            folders=[
                FolderOut(
                    id=folder.id,
                    dir=folder.dir,
                    stage=folder.stage,
                    doc_types=[
                        DocTypeOut(
                            key=t.key,
                            id=t.id,
                            title=t.title,
                            required=t.required,
                            normalize=t.normalize,
                            multi=t.multi,
                        )
                        for t in folder.doc_types
                    ],
                )
                for folder in taxonomy.folders
            ],
        )
