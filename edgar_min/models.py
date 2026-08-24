"""Typed models for EDGAR data structures.
Vendored unchanged (minus CompanyRef/FactPoint) from
ma-target-screener/src/mascreener/edgar/models.py."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


def pad_cik(cik: int | str) -> str:
    """SEC CIKs are canonically 10-digit zero-padded strings."""
    return str(int(str(cik).lstrip("CIK"))).zfill(10)


class Filing(BaseModel):
    """One filing from a company's submissions feed."""

    cik: str
    accession_no: str          # 0001193125-16-624286
    form_type: str             # 10-K, 8-K, SC 13D, DEF 14A, ...
    filed_date: date
    period_of_report: date | None = None
    primary_doc: str | None = None
    primary_doc_description: str | None = None
    size_bytes: int | None = None

    @property
    def accession_nodash(self) -> str:
        return self.accession_no.replace("-", "")

    @property
    def primary_doc_url(self) -> str | None:
        """Direct URL to the primary document in the EDGAR archives."""
        if not self.primary_doc:
            return None
        return (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{int(self.cik)}/{self.accession_nodash}/{self.primary_doc}"
        )
