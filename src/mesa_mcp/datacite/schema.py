"""DataCite Metadata Schema 4.x as Pydantic models + controlled-vocabulary enums.

Static and offline — no network. Mandatory fields (Identifier, Creator, Title,
Publisher, PublicationYear, ResourceType) are required by the model; everything
else is optional. Mirrors the role OLS plays for ontology metadata.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ResourceTypeGeneral(str, Enum):
    Audiovisual = "Audiovisual"; Book = "Book"; BookChapter = "BookChapter"
    Collection = "Collection"; ComputationalNotebook = "ComputationalNotebook"
    ConferencePaper = "ConferencePaper"; ConferenceProceeding = "ConferenceProceeding"
    DataPaper = "DataPaper"; Dataset = "Dataset"; Dissertation = "Dissertation"
    Event = "Event"; Image = "Image"; InteractiveResource = "InteractiveResource"
    Journal = "Journal"; JournalArticle = "JournalArticle"; Model = "Model"
    OutputManagementPlan = "OutputManagementPlan"; PeerReview = "PeerReview"
    PhysicalObject = "PhysicalObject"; Preprint = "Preprint"; Report = "Report"
    Service = "Service"; Software = "Software"; Sound = "Sound"
    Standard = "Standard"; Text = "Text"; Workflow = "Workflow"; Other = "Other"


class ContributorType(str, Enum):
    ContactPerson = "ContactPerson"; DataCollector = "DataCollector"
    DataCurator = "DataCurator"; DataManager = "DataManager"; Distributor = "Distributor"
    Editor = "Editor"; HostingInstitution = "HostingInstitution"; Producer = "Producer"
    ProjectLeader = "ProjectLeader"; ProjectManager = "ProjectManager"
    ProjectMember = "ProjectMember"; RegistrationAgency = "RegistrationAgency"
    RegistrationAuthority = "RegistrationAuthority"; RelatedPerson = "RelatedPerson"
    Researcher = "Researcher"; ResearchGroup = "ResearchGroup"
    RightsHolder = "RightsHolder"; Sponsor = "Sponsor"; Supervisor = "Supervisor"
    WorkPackageLeader = "WorkPackageLeader"; Other = "Other"


class DateType(str, Enum):
    Accepted = "Accepted"; Available = "Available"; Copyrighted = "Copyrighted"
    Collected = "Collected"; Created = "Created"; Issued = "Issued"
    Submitted = "Submitted"; Updated = "Updated"; Valid = "Valid"; Withdrawn = "Withdrawn"


class DescriptionType(str, Enum):
    Abstract = "Abstract"; Methods = "Methods"; SeriesInformation = "SeriesInformation"
    TableOfContents = "TableOfContents"; TechnicalInfo = "TechnicalInfo"; Other = "Other"


class RelationType(str, Enum):
    IsCitedBy = "IsCitedBy"; Cites = "Cites"; IsSupplementTo = "IsSupplementTo"
    IsSupplementedBy = "IsSupplementedBy"; IsContinuedBy = "IsContinuedBy"
    Continues = "Continues"; IsDescribedBy = "IsDescribedBy"; Describes = "Describes"
    IsPartOf = "IsPartOf"; HasPart = "HasPart"; IsReferencedBy = "IsReferencedBy"
    References = "References"; IsDocumentedBy = "IsDocumentedBy"; Documents = "Documents"
    IsCompiledBy = "IsCompiledBy"; Compiles = "Compiles"; IsVariantFormOf = "IsVariantFormOf"
    IsDerivedFrom = "IsDerivedFrom"; IsSourceOf = "IsSourceOf"; IsVersionOf = "IsVersionOf"
    HasVersion = "HasVersion"; IsNewVersionOf = "IsNewVersionOf"; IsObsoletedBy = "IsObsoletedBy"


class RelatedIdentifierType(str, Enum):
    DOI = "DOI"; URL = "URL"; URN = "URN"; Handle = "Handle"; ARK = "ARK"
    ISBN = "ISBN"; ISSN = "ISSN"; PMID = "PMID"; arXiv = "arXiv"; bibcode = "bibcode"
    IGSN = "IGSN"; PURL = "PURL"; UPC = "UPC"; w3id = "w3id"; EAN13 = "EAN13"


class NameType(str, Enum):
    Personal = "Personal"; Organizational = "Organizational"


class Creator(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1)
    nameType: NameType | None = None
    affiliation: str | None = None
    nameIdentifier: str | None = None  # e.g. an ORCID
    nameIdentifierScheme: str | None = None


class Contributor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1)
    contributorType: ContributorType
    affiliation: str | None = None


class Subject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(..., min_length=1)
    subjectScheme: str | None = None


class DateInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: str = Field(..., min_length=1)
    dateType: DateType


class RelatedIdentifier(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(..., min_length=1)
    relatedIdentifierType: RelatedIdentifierType
    relationType: RelationType


class Description(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(..., min_length=1)
    descriptionType: DescriptionType = DescriptionType.Abstract


class Rights(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(..., min_length=1)
    rightsURI: str | None = None


class GeoLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    place: str | None = None
    point: str | None = None
    box: str | None = None


class DataCiteMetadata(BaseModel):
    """A DataCite 4.x record. Mandatory kernel fields are required."""

    model_config = ConfigDict(extra="forbid")

    # --- mandatory ---
    identifier: str = Field(..., min_length=1)
    identifierType: str = "DOI"
    titles: list[str] = Field(..., min_length=1)
    creators: list[Creator] = Field(..., min_length=1)
    publisher: str = Field(..., min_length=1)
    publicationYear: int
    resourceTypeGeneral: ResourceTypeGeneral
    # --- recommended/optional ---
    resourceType: str | None = None
    subjects: list[Subject] = Field(default_factory=list)
    contributors: list[Contributor] = Field(default_factory=list)
    dates: list[DateInfo] = Field(default_factory=list)
    relatedIdentifiers: list[RelatedIdentifier] = Field(default_factory=list)
    descriptions: list[Description] = Field(default_factory=list)
    rightsList: list[Rights] = Field(default_factory=list)
    geoLocations: list[GeoLocation] = Field(default_factory=list)
    language: str | None = None
    formats: list[str] = Field(default_factory=list)
    sizes: list[str] = Field(default_factory=list)
    version: str | None = None

    @field_validator("publicationYear")
    @classmethod
    def _year_range(cls, v: int) -> int:
        if not (1000 <= v <= 9999):
            raise ValueError("publicationYear must be a 4-digit year")
        return v


# CyVerse DOI-request template column name -> kernel field name.
LEGACY_CROSSWALK: dict[str, str] = {
    "datacite.title": "title",
    "datacite.creator": "creator",
    "creatorAffiliation": "affiliation",
    "creatorNameIdentifier": "nameIdentifier",
    "datacite.publisher": "publisher",
    "datacite.publicationyear": "publicationYear",
    "datacite.resourcetype": "resourceTypeGeneral",
    "ResourceType": "resourceType",
    "contributorName": "contributor",
    "contributorType": "contributorType",
    "Subject": "subject",
    "Identifier": "identifier",
    "identifierType": "identifierType",
    "AlternateIdentifier": "alternateIdentifier",
    "RelatedIdentifier": "relatedIdentifier",
    "relationType": "relationType",
    "Rights": "rights",
    "Description": "description",
    "descriptionType": "descriptionType",
    "compressed_data": "compressed",
    "geoLocationBox": "geoLocationBox",
    "geoLocationPlace": "geoLocationPlace",
    "geoLocationPoint": "geoLocationPoint",
}
