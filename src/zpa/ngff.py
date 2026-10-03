"""
ngff.py -- optional OME-NGFF conformance preflight, delegated to yaozarrs.

ZPA checks structural integrity (is the pyramid what its metadata says it
is?); it does not attempt the full OME-NGFF spec. yaozarrs does, with only
pydantic + fsspec, so a report can carry both answers side by side. The
two are kept apart on purpose:

  * ``ngff_conformance`` never changes ``integrity``, a severity or the gate
    verdict. A spec-valid pyramid can be chunkless (the PHerc0814 ``-L1``
    defect passes yaozarrs), and a spec-invalid one can still decode fine.
  * The validator is optional (``pip install 'zarr-pyramid-audit[ngff]'``).
    When it is not installed or not requested, the state is
    ``not_checked``; when it could not reach a verdict (transport error,
    an OME version it does not model) the state is ``unknown``. Neither is
    ever reported as ``conforms``.

States:

  conforms       yaozarrs.validate_zarr_store() accepted metadata + structure
  nonconformant  it rejected them (pydantic / storage validation error,
                 malformed JSON, no OME-Zarr group metadata at the root)
  unknown        it ran but could not decide
  not_checked    not requested, or yaozarrs is not installed
"""

from __future__ import annotations

from urllib.parse import quote

__all__ = ["VALIDATOR", "NGFF_STATES", "not_checked", "check_ngff", "ngff_uri"]

VALIDATOR = "yaozarrs"
NGFF_STATES = ("conforms", "nonconformant", "unknown", "not_checked")

INSTALL_HINT = "pip install 'zarr-pyramid-audit[ngff]'"


def _result(state: str, detail: str, version: str | None = None) -> dict:
    return {"validator": VALIDATOR, "validator_version": version,
            "state": state, "detail": detail}


def not_checked(detail: str = "not requested") -> dict:
    return _result("not_checked", detail)


def ngff_uri(store, root: str) -> str:
    """The URI yaozarrs should open for ``root`` in a ZPA store.

    ``s3://`` bases are rewritten to anonymous path-style HTTPS on the
    store's endpoint, so the validator needs no AWS credentials and reads
    exactly the bytes ZPA read.
    """
    base = getattr(store, "base_url", "") or ""
    uri = base + root.strip("/")
    if uri.startswith("s3://"):
        endpoint = (getattr(store, "endpoint_url", None)
                    or "https://s3.amazonaws.com").rstrip("/")
        uri = f"{endpoint}/{quote(uri[5:])}"
    return uri


def check_ngff(uri: str) -> dict:
    """Run yaozarrs on one root; never raises."""
    try:
        import yaozarrs
    except ImportError:
        return not_checked(f"yaozarrs not installed ({INSTALL_HINT})")
    version = getattr(yaozarrs, "__version__", None)
    try:
        yaozarrs.validate_zarr_store(uri)
    except NotImplementedError as exc:
        # e.g. "Structural validation for OME-Zarr version 0.6 is not
        # implemented": the validator has no opinion, so neither do we.
        return _result("unknown", f"{type(exc).__name__}: {exc}", version)
    except FileNotFoundError as exc:
        return _result("nonconformant",
                       f"{type(exc).__name__}: no OME-Zarr group metadata "
                       f"found ({exc})", version)
    except ValueError as exc:
        # pydantic.ValidationError, yaozarrs StorageValidationError and
        # json.JSONDecodeError are all ValueError subclasses.
        first = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
        return _result("nonconformant", f"{type(exc).__name__}: {first}",
                       version)
    except Exception as exc:  # noqa: BLE001 -- transport etc.: undecided
        return _result("unknown", f"{type(exc).__name__}: {exc}", version)
    return _result("conforms", "validate_zarr_store accepted metadata "
                   "and structure", version)
