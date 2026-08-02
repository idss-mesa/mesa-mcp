"""EMBL-EBI Ontology Lookup Service (OLS) API client.

Provides access to 266+ ontologies and 8.6M+ terms via the OLS4 REST API.
Used to generate dynamic metadata schemas from ontology term hierarchies so
researchers (or agents) can annotate iRODS data with controlled-vocabulary
terms stored as AVUs.

Ported from ``cyverse/esiil-portal/portal/services/ols_client.py``. Public
method signatures and return shapes are preserved verbatim so parity work
stays mechanical. The Django ``cache`` dependency has been replaced with an
in-process :class:`cachetools.TTLCache`; the original TTLs (24 h for ontology
catalogs + term details, 12 h for child listings, 1 h for searches) are
preserved.

No authentication required — the OLS API is public.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

import requests
from cachetools import TTLCache
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

OLS_BASE_URL = "https://www.ebi.ac.uk/ols4/api/v2"
OLS_SEARCH_URL = "https://www.ebi.ac.uk/ols4/api/search"

# Cache TTLs (seconds) — preserved from the esiil-portal source.
_TTL_24H = 86400
_TTL_12H = 43200
_TTL_1H = 3600

# Cache size cap. The portal uses Django cache which has no hard cap; here we
# pick a generous upper bound so a busy MCP process won't grow unbounded.
_CACHE_MAXSIZE = 4096

# HTTP timeout when the caller supplies none. Also ported from the portal.
_DEFAULT_TIMEOUT = 15


class OLSAPIError(Exception):
    """Custom exception for OLS API errors."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class OLSClient:
    """Client for the EMBL-EBI Ontology Lookup Service (OLS4) API.

    Provides methods to browse ontologies, search terms, and generate
    SCHEMAS-compatible templates for dynamic form rendering. Follows the same
    session/retry pattern as the portal's ``DataCiteClient``.
    """

    def __init__(
        self,
        base_url: str | None = None,
        *,
        ontology_cache_ttl: int | None = None,
        term_cache_ttl: int | None = None,
        search_cache_ttl: int | None = None,
        request_timeout: float | None = None,
    ) -> None:
        """Construct a client.

        The TTL and timeout keywords exist so ``OLSConfig`` is actually
        honoured. They previously did not: the class hardcoded the values
        ported from esiil-portal while ``OLSConfig`` advertised different
        ones, so an operator who set ``search_cache_ttl: 60`` silently got
        3600. Omitted arguments keep the ported defaults.
        """
        self.base_url = (base_url or OLS_BASE_URL).rstrip("/")
        self.timeout = _DEFAULT_TIMEOUT if request_timeout is None else request_timeout

        ontology_ttl = _TTL_24H if ontology_cache_ttl is None else ontology_cache_ttl
        term_ttl = _TTL_24H if term_cache_ttl is None else term_cache_ttl
        search_ttl = _TTL_1H if search_cache_ttl is None else search_cache_ttl

        # Per-instance TTL caches. The portal's single Django cache becomes
        # one cache per logical purpose so we can preserve the original TTLs.
        self._cache_catalog: TTLCache = TTLCache(maxsize=_CACHE_MAXSIZE, ttl=ontology_ttl)
        self._cache_ontology: TTLCache = TTLCache(
            maxsize=_CACHE_MAXSIZE, ttl=ontology_ttl
        )
        self._cache_search: TTLCache = TTLCache(maxsize=_CACHE_MAXSIZE, ttl=search_ttl)
        self._cache_term: TTLCache = TTLCache(maxsize=_CACHE_MAXSIZE, ttl=term_ttl)
        self._cache_children: TTLCache = TTLCache(maxsize=_CACHE_MAXSIZE, ttl=_TTL_12H)
        self._cache_desc_search: TTLCache = TTLCache(
            maxsize=_CACHE_MAXSIZE, ttl=search_ttl
        )
        self._cache_template: TTLCache = TTLCache(maxsize=_CACHE_MAXSIZE, ttl=_TTL_24H)

        self.session = requests.Session()
        retry_strategy = Retry(
            total=2,
            backoff_factor=0.5,
            status_forcelist=[429, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        self.session.headers.update({"Accept": "application/json"})

    def _make_request(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make a GET request to the OLS API with structured error handling."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        logger.debug("OLS API Request: GET %s params=%s", url, params)

        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            logger.debug("OLS API Response: %s", response.status_code)

            try:
                data = response.json()
            except ValueError:
                data = {}

            if not response.ok:
                error_msg = data.get("message", response.text[:500])
                raise OLSAPIError(
                    f"OLS API error ({response.status_code}): {error_msg}",
                    status_code=response.status_code,
                )

            return data

        except requests.exceptions.ConnectionError as e:
            raise OLSAPIError(f"Connection error to OLS API: {e}") from e
        except requests.exceptions.Timeout as e:
            raise OLSAPIError("OLS API request timed out") from e
        except OLSAPIError:
            raise
        except requests.exceptions.RequestException as e:
            raise OLSAPIError(f"OLS API request failed: {e}") from e

    # ------------------------------------------------------------------
    # Ontology catalog
    # ------------------------------------------------------------------

    def list_ontologies(self, page: int = 0, size: int = 25) -> dict[str, Any]:
        """List available ontologies with pagination.

        Returns a dict with ``ontologies`` list and pagination info.
        """
        cache_key = f"ols:catalog:{page}:{size}"
        cached = self._cache_catalog.get(cache_key)
        if cached is not None:
            return cached

        data = self._make_request(
            "/ontologies",
            params={"page": page, "size": size},
        )
        result = {
            "ontologies": _extract_ontologies(data),
            "totalElements": data.get("totalElements", 0),
            "page": data.get("page", page),
            "size": data.get("size", size),
        }

        self._cache_catalog[cache_key] = result
        return result

    def get_ontology(self, ontology_id: str) -> dict[str, Any]:
        """Get details for a specific ontology.

        Parameters
        ----------
        ontology_id:
            Ontology ID (e.g. ``"envo"``, ``"go"``, ``"chebi"``).

        Returns
        -------
        dict
            Ontology metadata.
        """
        cache_key = f"ols:ontology:{ontology_id.lower()}"
        cached = self._cache_ontology.get(cache_key)
        if cached is not None:
            return cached

        data = self._make_request(f"/ontologies/{ontology_id.lower()}")
        result = _extract_ontology_detail(data)

        self._cache_ontology[cache_key] = result
        return result

    # ------------------------------------------------------------------
    # Term search
    # ------------------------------------------------------------------

    def search_terms(
        self,
        query: str,
        ontology_id: str | None = None,
        size: int = 15,
    ) -> list[dict[str, Any]]:
        """Search for terms across ontologies or within a specific one.

        Uses the v2 ``/entities`` endpoint with the ``search`` parameter. When
        searching within a specific ontology, includes both classes and
        individuals so that registries like ROR (organizations stored as OWL
        individuals) are searchable.

        Parameters
        ----------
        query:
            Search string.
        ontology_id:
            Optional ontology ID to restrict search.
        size:
            Max results to return.

        Returns
        -------
        list of dicts
            Term dicts with ``label``, ``iri``, ``curie``, ``description``,
            ``ontologyId``.
        """
        cache_key = f'ols:search:{ontology_id or "all"}:{query.lower().strip()}:{size}'
        cached = self._cache_search.get(cache_key)
        if cached is not None:
            return cached

        params: dict[str, Any] = {
            "search": query,
            "size": size,
        }
        if ontology_id:
            params["ontologyId"] = ontology_id.lower()
            # Don't restrict type — include individuals (ROR orgs, etc.)
        else:
            # Broad cross-ontology search: restrict to classes to avoid noise.
            params["type"] = "class"

        data = self._make_request("/entities", params=params)
        results = _extract_search_results(data)

        self._cache_search[cache_key] = results
        return results

    def get_term(self, ontology_id: str, iri: str) -> dict[str, Any] | None:
        """Get details for a specific term by its IRI.

        Parameters
        ----------
        ontology_id:
            Ontology ID.
        iri:
            Full IRI of the term.

        Returns
        -------
        dict or None
            Term metadata, or ``None`` if not found.
        """
        iri_hash = hashlib.md5(iri.encode()).hexdigest()
        cache_key = f"ols:term:{ontology_id.lower()}:{iri_hash}"
        cached = self._cache_term.get(cache_key)
        if cached is not None:
            return cached

        try:
            # OLS4 v2 uses double-encoded IRIs in the URL path.
            encoded_iri = requests.utils.quote(
                requests.utils.quote(iri, safe=""), safe=""
            )
            data = self._make_request(
                f"/ontologies/{ontology_id.lower()}/classes/{encoded_iri}"
            )
            result = _extract_term(data)
            self._cache_term[cache_key] = result
            return result
        except OLSAPIError as e:
            if e.status_code == 404:
                return None
            raise

    def get_term_children(
        self, ontology_id: str, iri: str, size: int = 50
    ) -> list[dict[str, Any]]:
        """Get child terms for hierarchy browsing.

        Parameters
        ----------
        ontology_id:
            Ontology ID.
        iri:
            Full IRI of the parent term.
        size:
            Max children to return.

        Returns
        -------
        list of dicts
            Child term dicts.
        """
        iri_hash = hashlib.md5(iri.encode()).hexdigest()
        cache_key = f"ols:children:{ontology_id.lower()}:{iri_hash}"
        cached = self._cache_children.get(cache_key)
        if cached is not None:
            return cached

        encoded_iri = requests.utils.quote(requests.utils.quote(iri, safe=""), safe="")
        try:
            data = self._make_request(
                f"/ontologies/{ontology_id.lower()}/classes/{encoded_iri}/children",
                params={"size": size},
            )
            results = _extract_elements_as_terms(data)
            self._cache_children[cache_key] = results
            return results
        except OLSAPIError as e:
            if e.status_code == 404:
                return []
            raise

    def search_term_descendants(
        self,
        query: str,
        ontology_id: str,
        parent_iri: str,
        size: int = 20,
    ) -> list[dict[str, Any]]:
        """Search for terms that are descendants of a given parent term.

        Uses the OLS v1-compat ``/search`` endpoint which supports the
        ``allChildrenOf`` parameter for server-side descendant filtering.
        """
        parent_hash = hashlib.md5(parent_iri.encode()).hexdigest()
        cache_key = (
            f"ols:desc_search:{ontology_id.lower()}:{parent_hash}:"
            f"{query.lower().strip()}:{size}"
        )
        cached = self._cache_desc_search.get(cache_key)
        if cached is not None:
            return cached

        params = {
            "q": query,
            "ontology": ontology_id.lower(),
            "allChildrenOf": parent_iri,
            "rows": size,
            "fieldList": "iri,label,obo_id,description,ontology_name,hasChildren",
        }
        resp = self.session.get(OLS_SEARCH_URL, params=params, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()

        docs = data.get("response", {}).get("docs", [])
        results = [_extract_term(doc) for doc in docs]

        self._cache_desc_search[cache_key] = results
        return results

    # ------------------------------------------------------------------
    # Border term discovery (for template generation)
    # ------------------------------------------------------------------

    def _find_border_terms(
        self,
        ontology_id: str,
        curie_prefix: str,
        max_terms: int = 20,
        max_pages: int = 20,
    ) -> list[dict[str, Any]]:
        """Find native classes whose direct parents are all non-native.

        Many OBO ontologies (ENVO, UBERON, etc.) import an upper ontology like
        BFO and attach their own classes underneath. This means native classes
        have ``hasDirectParents=true`` and won't appear as roots. Their true
        top-level concepts are the first native classes below the imported
        hierarchy — i.e. classes whose ``directParent`` list contains only
        non-native IRIs.

        We scan class pages (cached 24 h each), check the ``directParent``
        field, and collect native classes with children. Results are sorted by
        ancestor depth (shallowest first) so the broadest categories appear
        first.

        Returns a list of term dicts (same shape as :func:`_extract_term`),
        capped at *max_terms*.
        """
        iri_fragment = f"/{ontology_id.upper()}_"
        border: list[tuple[int, dict[str, Any]]] = []
        empty_pages = 0  # consecutive pages with no native classes

        for page in range(max_pages):
            try:
                data = self._make_request(
                    f"/ontologies/{ontology_id.lower()}/classes",
                    params={"size": 200, "page": page},
                )
            except OLSAPIError:
                break

            elements = data.get("elements", [])
            if not elements:
                break

            native_on_page = 0
            for elem in elements:
                curie = elem.get("curie", "")
                if not curie.upper().startswith(curie_prefix):
                    continue
                native_on_page += 1
                if not elem.get("hasDirectChildren", False):
                    continue

                # Check directParent: all must be non-native
                parents = elem.get("directParent", [])
                if not parents:
                    continue

                all_imported = True
                for p in parents:
                    val = p.get("value", "") if isinstance(p, dict) else str(p)
                    if iri_fragment in val:
                        all_imported = False
                        break

                if all_imported:
                    depth = len(elem.get("hierarchicalAncestor", []))
                    border.append((depth, _extract_term(elem)))

            # Stop when we hit pages with no native classes (imported-only zone)
            if native_on_page == 0:
                empty_pages += 1
                if empty_pages >= 2:
                    break
            else:
                empty_pages = 0

        # Sort by depth (shallowest = broadest categories first)
        border.sort(key=lambda x: x[0])
        return [t for _, t in border[:max_terms]]

    # ------------------------------------------------------------------
    # Template generation
    # ------------------------------------------------------------------

    def generate_template(self, ontology_id: str) -> dict[str, Any]:
        """Generate a SCHEMAS-compatible dict from an ontology's top-level terms.

        The template contains:

        * ``label``: human-readable ontology name
        * ``prefix``: ``<ontology_id>.`` for AVU attribute prefix
        * ``fields``: list of ``{key, label, desc, curie, iri, hasChildren,
          synonyms}`` dicts from top-level terms

        Returns a dict compatible with the metadata page's SCHEMAS structure.
        """
        cache_key = f"ols:template:{ontology_id.lower()}"
        cached = self._cache_template.get(cache_key)
        if cached is not None:
            return cached

        ontology = self.get_ontology(ontology_id)
        prefix = ontology_id.lower() + "."

        # Get top-level terms (roots of the ontology)
        curie_prefix = ontology_id.upper() + ":"
        try:
            data = self._make_request(
                f"/ontologies/{ontology_id.lower()}/classes",
                params={"hasDirectParents": "false", "size": 50},
            )
            all_roots = _extract_elements_as_terms(data)
            # Filter out imported terms from other ontologies (e.g. BFO, PATO
            # roots that ENVO imports). OLS sets ontologyId='envo' for ALL
            # terms retrieved from ENVO's namespace, so we must filter by
            # CURIE prefix instead.
            root_terms = [
                t
                for t in all_roots
                if (t.get("curie") or "").upper().startswith(curie_prefix)
            ]
        except OLSAPIError:
            root_terms = []

        # Check if primary results are sufficient: need >= 5 native roots, or
        # at least some with children. Ontologies like ENVO have only 2 orphan
        # native roots (both leaves) while their real top-level concepts (biome,
        # environmental material, etc.) have imported BFO parents and so
        # aren't "roots" at all.
        has_useful_roots = len(root_terms) >= 5 or (
            root_terms and any(t.get("hasChildren") for t in root_terms)
        )

        # Fallback 1: find "border terms" — native classes whose direct parents
        # are ALL non-native (imported from BFO, PATO, etc.). These are the
        # true top-level concepts of the ontology.
        if not has_useful_roots:
            border_terms = self._find_border_terms(ontology_id, curie_prefix)
            if border_terms:
                root_terms = border_terms

        # Fallback 2: grab native classes with children from the class listing.
        if not root_terms:
            try:
                data = self._make_request(
                    f"/ontologies/{ontology_id.lower()}/classes",
                    params={"size": 200},
                )
                all_classes = _extract_elements_as_terms(data)
                root_terms = [
                    t
                    for t in all_classes
                    if (t.get("curie") or "").upper().startswith(curie_prefix)
                    and t.get("hasChildren")
                ][:20]
            except OLSAPIError:
                pass

        # Fallback 3: registries like ROR use simple CURIEs without a colon
        # (e.g. 'company', 'education') for their category classes. Include
        # these non-imported classes when no standard-prefix matches found.
        if not root_terms:
            try:
                data = self._make_request(
                    f"/ontologies/{ontology_id.lower()}/classes",
                    params={"size": 50},
                )
                all_classes = _extract_elements_as_terms(data)
                root_terms = [
                    t for t in all_classes if ":" not in (t.get("curie") or ":")
                ]
            except OLSAPIError:
                pass

        fields: list[dict[str, Any]] = []
        for term in root_terms:
            snake_key = _label_to_snake(term.get("label", ""))
            if not snake_key:
                continue
            fields.append(
                {
                    "key": f"{prefix}{snake_key}",
                    "label": term.get("label", ""),
                    "desc": term.get("description", ""),
                    "curie": term.get("curie", ""),
                    "iri": term.get("iri", ""),
                    "hasChildren": term.get("hasChildren", False),
                    "synonyms": term.get("synonyms", []),
                }
            )

        individual_count = ontology.get("numberOfIndividuals", 0)

        template = {
            "label": ontology.get("title", ontology_id.upper()),
            "prefix": prefix,
            "ontologyId": ontology_id.lower(),
            "description": ontology.get("description", ""),
            "termCount": ontology.get("numberOfTerms", 0),
            "individualCount": individual_count,
            "fields": fields,
        }

        self._cache_template[cache_key] = template
        return template


# ------------------------------------------------------------------
# Response extraction helpers
# ------------------------------------------------------------------


def _extract_ontologies(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract ontology summaries from an OLS API response.

    OLS4 v2 uses a flat structure (no 'config' wrapper):

    * ``title`` / ``label`` at the top level
    * ``numberOfClasses`` instead of ``numberOfTerms``
    * some ontologies use ``config`` (v1 compat), others don't
    """
    elements = data.get("elements", [])
    results: list[dict[str, Any]] = []
    for ont in elements:
        config = ont.get("config", {})
        results.append(
            {
                "ontologyId": ont.get("ontologyId", ""),
                "title": (
                    ont.get("title")
                    or ont.get("label")
                    or config.get("title")
                    or ont.get("ontologyId", "")
                ),
                "description": (
                    ont.get("description") or config.get("description") or ""
                ),
                "numberOfTerms": (
                    ont.get("numberOfClasses")
                    or ont.get("numberOfEntities")
                    or ont.get("numberOfTerms")
                    or config.get("numberOfTerms")
                    or 0
                ),
                "status": ont.get("activity_status", ont.get("status", "")),
            }
        )
    return results


def _extract_ontology_detail(data: dict[str, Any]) -> dict[str, Any]:
    """Extract ontology detail from OLS API response.

    Handles both OLS4 v2 flat format and v1-style ``config`` wrapper.
    """
    config = data.get("config", {})
    # Try int conversion for numberOfClasses (sometimes returned as string)
    num_terms = (
        data.get("numberOfClasses")
        or data.get("numberOfEntities")
        or data.get("numberOfTerms")
        or config.get("numberOfTerms")
        or 0
    )
    try:
        num_terms = int(num_terms)
    except (ValueError, TypeError):
        num_terms = 0
    num_props = data.get("numberOfProperties") or config.get("numberOfProperties") or 0
    try:
        num_props = int(num_props)
    except (ValueError, TypeError):
        num_props = 0
    num_indiv = data.get("numberOfIndividuals") or config.get("numberOfIndividuals") or 0
    try:
        num_indiv = int(num_indiv)
    except (ValueError, TypeError):
        num_indiv = 0

    return {
        "ontologyId": data.get("ontologyId", ""),
        "title": (
            data.get("title")
            or data.get("label")
            or config.get("title")
            or data.get("ontologyId", "")
        ),
        "description": data.get("description") or config.get("description") or "",
        "numberOfTerms": num_terms,
        "numberOfProperties": num_props,
        "numberOfIndividuals": num_indiv,
        "status": data.get("activity_status", data.get("status", "")),
        "homepage": data.get("homepage") or config.get("homepage") or "",
        "version": (
            data.get("http://www.w3.org/2002/07/owl#versionInfo")
            or config.get("version")
            or ""
        ),
        "preferredPrefix": data.get("preferredPrefix") or config.get("preferredPrefix") or "",
    }


def _extract_search_results(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract term results from OLS search response."""
    # v2 uses 'elements', v1 uses 'response.docs'
    elements = data.get("elements", [])
    if not elements:
        response = data.get("response", {})
        elements = response.get("docs", [])
    return [_extract_term(elem) for elem in elements]


def _extract_term(data: dict[str, Any]) -> dict[str, Any]:
    """Extract a single term's key fields.

    Handles both OLS4 v2 format (``label`` as list, ``definition`` instead of
    ``description``) and v1 format (``label`` as string, ``description`` as
    list).
    """
    # Label: v2 returns list, v1 returns string.
    label = data.get("label", "")
    if isinstance(label, list):
        label = label[0] if label else ""

    # Description: try 'description' first, then 'definition'.
    description = ""
    desc_raw = data.get("description") or data.get("definition") or []
    if isinstance(desc_raw, list) and desc_raw:
        first = desc_raw[0]
        if isinstance(first, dict):
            description = first.get("value", "")
        elif isinstance(first, str):
            description = first
    elif isinstance(desc_raw, str):
        description = desc_raw

    # Filter uninformative auto-generated definitions.
    if description and "injected by pyobo" in description.lower():
        description = ""

    # hasChildren: v2 uses 'hasDirectChildren', v1 uses 'hasChildren'.
    has_children = data.get("hasDirectChildren", data.get("hasChildren", False))

    # Synonyms: OLS returns these in an annotation object.
    annotation = data.get("annotation", {})
    synonyms: list[str] = []
    for syn_key in (
        "has_exact_synonym",
        "hasExactSynonym",
        "has_related_synonym",
        "hasRelatedSynonym",
    ):
        syn_val = annotation.get(syn_key, [])
        if isinstance(syn_val, list):
            synonyms.extend(syn_val)
        elif isinstance(syn_val, str):
            synonyms.append(syn_val)

    return {
        "label": label,
        "iri": data.get("iri", ""),
        "curie": data.get("curie", data.get("obo_id", "")),
        "description": description,
        "ontologyId": data.get("ontologyId", data.get("ontology_name", "")),
        "isRoot": data.get("isRoot", not data.get("hasDirectParents", True)),
        "hasChildren": has_children,
        "synonyms": synonyms[:5],
    }


def _extract_elements_as_terms(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract an ``elements`` array as a list of term dicts."""
    elements = data.get("elements", [])
    return [_extract_term(e) for e in elements]


def _label_to_snake(label: str) -> str:
    """Convert a term label to a snake_case AVU key fragment.

    Examples
    --------
    >>> _label_to_snake('Biome')
    'biome'
    >>> _label_to_snake('Environmental Feature')
    'environmental_feature'
    >>> _label_to_snake('pH value')
    'ph_value'
    """
    if not label:
        return ""
    s = re.sub(r"[^a-zA-Z0-9\s]", "", label)
    s = re.sub(r"\s+", "_", s.strip())
    return s.lower()


def _truncate(text: str, length: int) -> str:
    """Truncate text to length, adding ellipsis if needed."""
    if not text or len(text) <= length:
        return text or ""
    return text[: length - 1] + "…"


# ------------------------------------------------------------------
# Factory
# ------------------------------------------------------------------


def get_ols_client() -> OLSClient:
    """Return a new :class:`OLSClient` built from the active configuration.

    Falls back to the ported defaults when no config is bound, so this
    stays usable outside a request context (tests, scripts).
    """
    try:
        from mesa_mcp.config import get_active_config

        ols = get_active_config().ols
    except Exception:
        return OLSClient()

    return OLSClient(
        base_url=ols.base_url or None,
        ontology_cache_ttl=ols.ontology_cache_ttl,
        term_cache_ttl=ols.term_cache_ttl,
        search_cache_ttl=ols.search_cache_ttl,
        request_timeout=ols.request_timeout,
    )
