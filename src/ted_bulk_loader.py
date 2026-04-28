"""
TED Open Data CSV Bulk Loader

Downloads yearly CSV dumps from data.europa.eu and filters them
locally for defence trailer tenders. This catches notices that
our API queries might miss (API limited to 15,000 per query).

Each yearly file is a ZIP archive (~50-500MB) containing a CSV.
We download, extract, filter locally, and only keep matching rows.

Data source: https://data.europa.eu/data/datasets/ted-csv
Types:
  - ted-contract-notices-{year}.zip     (CN: new tenders)
  - ted-contract-award-notices-{year}.zip (CAN: results/awards)
"""

import csv
import io
import logging
import json
import os
import zipfile
import requests
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SSL_VERIFY = os.environ.get("SSL_VERIFY_DISABLE", "") != "1"


class TEDBulkLoader:
    """Loads and filters TED Open Data CSV dumps."""

    DATASET_API_URL = "https://data.europa.eu/api/hub/search/datasets/ted-csv"

    TRAILER_CPV_PREFIXES = [
        "34223",  # Trailers and semi-trailers
        "34224",  # Parts for trailers
        "35600",  # Military vehicles
        "35610",  # Military vehicles
        "34140",  # Heavy goods vehicles
        "34144",  # Special-purpose vehicles
        "34950",  # Loading systems
        "34221",  # Special-purpose mobile containers
    ]

    DEFENCE_LEGAL_BASIS = ["32009L0081"]

    TRAILER_KEYWORDS = [
        "trailer", "anhänger", "remorque", "rimorchio", "remolque",
        "przyczepa", "naczepa", "perävaunu", "släpvagn", "tilhenger",
        "semi-trailer", "semitrailer", "low-bed", "tieflader",
        "tank trailer", "tankanhänger", "citerne", "field kitchen",
        "feldküche", "shelter", "hook-lift", "hakenladegerät",
        "dolly", "ammunition trailer", "loading system",
    ]

    def __init__(self, config: dict, cache_dir: str = "data/raw/ted_bulk"):
        self.config = config
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def discover_csv_urls(self, notice_type: str = "contract-notices") -> dict:
        """
        Discover available CSV download URLs from data.europa.eu.

        Args:
            notice_type: "contract-notices" (CN, new tenders) or
                         "contract-award-notices" (CAN, results)

        Returns:
            dict of year -> download URL (ZIP archives)
        """
        try:
            resp = requests.get(
                self.DATASET_API_URL,
                headers={"Accept": "application/json"},
                timeout=30,
                verify=SSL_VERIFY,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"TED CSV API request failed: {e}")
            return {}

        distributions = data.get("result", {}).get("distributions", [])
        logger.info(f"TED CSV API: {len(distributions)} total distributions found")

        urls = {}
        for dist in distributions:
            # title can be str or {"en": "...", ...}
            title_raw = dist.get("title", {})
            title = title_raw if isinstance(title_raw, str) else title_raw.get("en", "")

            # download_url can be a list or string
            dl_urls = dist.get("download_url") or dist.get("access_url", [])
            if isinstance(dl_urls, str):
                dl_urls = [dl_urls]
            if not dl_urls:
                continue
            url = dl_urls[0]

            # Skip deprecated multi-year bundles and VEAT
            if "*deprecated" in title or "VEAT" in title or "2009-2015" in title:
                continue

            # Match on notice type: "contract notices" vs "contract award notices"
            title_lower = title.lower()
            if notice_type == "contract-notices":
                if "contract award" in title_lower or "award notice" in title_lower:
                    continue
                if "contract notice" not in title_lower and "contract notices" not in title_lower:
                    continue
            elif notice_type == "contract-award-notices":
                if "contract award" not in title_lower and "award notice" not in title_lower:
                    continue

            # Extract year from title
            for year in range(2006, 2027):
                if str(year) in title:
                    urls[year] = url
                    break

        logger.info(f"Discovered {notice_type} URLs: {sorted(urls.keys())}")
        return urls

    def peek_csv_columns(self, url: str) -> list:
        """Download a ZIP and return the CSV column headers (for debugging)."""
        try:
            resp = requests.get(url, timeout=120, verify=SSL_VERIFY)
            resp.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                if not csv_names:
                    return []
                with zf.open(csv_names[0]) as f:
                    sample = f.read(4096).decode("utf-8", errors="replace")
                    reader = csv.DictReader(io.StringIO(sample))
                    return reader.fieldnames or []
        except Exception as e:
            logger.error(f"Column peek failed: {e}")
            return []

    def download_and_filter_year(self, year: int, url: str) -> list:
        """
        Download a yearly ZIP, extract CSV, and filter for trailer-related tenders.
        Memory-efficient: reads row-by-row and only keeps matching rows.
        """
        cache_path = self.cache_dir / f"filtered_{year}.json"
        if cache_path.exists():
            with open(cache_path, encoding="utf-8") as f:
                cached = json.load(f)
            logger.info(f"Year {year}: {len(cached)} cached results")
            return cached

        logger.info(f"Downloading TED CSV for {year} from: {url}")

        try:
            resp = requests.get(url, timeout=600, verify=SSL_VERIFY)
            resp.raise_for_status()
            raw_size_mb = len(resp.content) / (1024 * 1024)
            logger.info(f"Year {year}: downloaded {raw_size_mb:.1f} MB")

            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                csv_files = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                if not csv_files:
                    logger.error(f"Year {year}: no CSV files found in ZIP (contents: {zf.namelist()})")
                    return []

                logger.info(f"Year {year}: ZIP contains {csv_files}")

                matches = []
                total_rows = 0

                for csv_name in csv_files:
                    with zf.open(csv_name) as csvfile:
                        text = csvfile.read().decode("utf-8", errors="replace")
                    reader = csv.DictReader(io.StringIO(text))

                    for row in reader:
                        total_rows += 1
                        if total_rows % 100_000 == 0:
                            logger.info(
                                f"  Year {year}: {total_rows} rows scanned, "
                                f"{len(matches)} matches"
                            )
                        if self._matches_filters(row):
                            matches.append(self._normalize_csv_row(row))

            logger.info(
                f"Year {year}: {len(matches)} matches from {total_rows} total rows"
            )

            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(matches, f, ensure_ascii=False, indent=2)

            return matches

        except Exception as e:
            logger.error(f"CSV processing failed for {year}: {e}")
            return []

    def _matches_filters(self, row: dict) -> bool:
        """
        Check if a CSV row matches our trailer + defence criteria.

        The TED bulk CSV (structural level) does NOT include title, description,
        or legal basis — only CPV and structural fields. So we use CPV prefix
        matching as the primary criterion, plus keyword/legal basis when available.
        This is intentionally broader than our API filter: the bulk comparison is
        about finding notices our API queries might have missed, not final quality
        filtering (that happens later in the classify phase).
        """
        # CPV — different column names across TED CSV schema versions
        cpv_main = str(
            row.get("CPV")
            or row.get("cpv_code")
            or row.get("main_cpv_code")
            or row.get("CPV_CODE")
            or ""
        ).strip()
        additional_cpvs = str(row.get("ADDITIONAL_CPVS", "")).strip()
        cpv_all = cpv_main + " " + additional_cpvs

        cpv_match = any(cpv_all.find(prefix) >= 0 for prefix in self.TRAILER_CPV_PREFIXES)

        # If CPV matches, we take it — this is a tier-1 trailer CPV
        if cpv_match:
            return True

        # Legal basis (defence directive) — when available
        legal = str(
            row.get("LEGAL_BASIS")
            or row.get("legal_basis")
            or row.get("DIRECTIVE")
            or ""
        ).strip()
        defence_legal = any(lb in legal for lb in self.DEFENCE_LEGAL_BASIS)

        # Keyword search in title + description — when available
        title = str(
            row.get("TITLE") or row.get("title") or row.get("CN_TITLE") or ""
        ).lower()
        desc = str(
            row.get("SHORT_DESCRIPTION") or row.get("description") or row.get("DESCRIPTION") or ""
        ).lower()
        text = title + " " + desc
        keyword_match = bool(text.strip()) and any(kw in text for kw in self.TRAILER_KEYWORDS)

        return (keyword_match and defence_legal) or keyword_match

    @staticmethod
    def _csv_id_to_api_id(csv_id: str, ted_url: str = "") -> str:
        """
        Convert TED CSV ID format to standard API format.

        CSV format:   {year4}{notice_number}  e.g. "2023423"
        API format:   {notice_number}-{year4} e.g. "423-2023"

        Falls back to parsing TED_NOTICE_URL if available:
          ted.europa.eu/udl?uri=TED:NOTICE:423-2023:TEXT:EN:HTML
        """
        if ted_url:
            import re
            m = re.search(r"NOTICE:(\d+)-(\d{4})", ted_url)
            if m:
                return f"{m.group(1)}-{m.group(2)}"

        csv_id = str(csv_id).strip()
        if len(csv_id) > 4:
            year = csv_id[:4]
            notice_num = csv_id[4:]
            if year.isdigit() and notice_num.isdigit():
                return f"{notice_num}-{year}"

        return csv_id

    def _normalize_csv_row(self, row: dict) -> dict:
        """Normalize a CSV row to our standard notice format."""
        def first(*keys):
            for k in keys:
                v = row.get(k)
                if v:
                    return str(v)
            return ""

        raw_id = first("ID_NOTICE_CN", "notice_id", "ID", "id_notice", "ID_NOTICE")
        ted_url = first("TED_NOTICE_URL")
        api_id = self._csv_id_to_api_id(raw_id, ted_url)

        return {
            "tender_id": api_id,
            "source": "TED-CSV",
            "title": first("TITLE", "title", "CN_TITLE"),
            "authority": first("CAE_NAME", "buyer_name", "contracting_authority", "AUTHORITY"),
            "country": first("ISO_COUNTRY_CODE", "country", "country_code"),
            "cpv": first("CPV", "cpv_code", "main_cpv_code", "CPV_CODE"),
            "legal_basis": first("LEGAL_BASIS", "legal_basis", "DIRECTIVE"),
            "value": first("AWARD_VALUE_EURO", "VALUE_EURO", "value_eur", "estimated_value"),
            "date": first("DT_DISPATCH", "publication_date", "dispatch_date", "DATE_PUB"),
            "description": first("SHORT_DESCRIPTION", "description", "DESCRIPTION")[:500],
        }

    def load_all_years(
        self,
        from_year: int = 2015,
        to_year: int = 2026,
        notice_type: str = "contract-notices",
        test_mode: bool = False,
    ) -> list:
        """Load and filter all available yearly CSVs."""
        urls = self.discover_csv_urls(notice_type=notice_type)

        if not urls:
            logger.warning(f"No CSV URLs found for notice_type={notice_type}")
            return []

        valid_years = sorted(y for y in urls if from_year <= y <= to_year)

        if test_mode:
            valid_years = valid_years[-1:]  # Only the most recent year
            logger.info(f"Test mode: loading only year {valid_years}")

        all_matches = []
        for year in valid_years:
            matches = self.download_and_filter_year(year, urls[year])
            all_matches.extend(matches)

        logger.info(
            f"Bulk load complete: {len(all_matches)} matches "
            f"across {len(valid_years)} years ({valid_years})"
        )
        return all_matches

    def find_missing_notices(
        self,
        existing_ids: set,
        from_year: int = 2015,
        to_year: int = 2026,
        notice_type: str = "contract-notices",
        test_mode: bool = False,
    ) -> list:
        """
        Compare bulk CSV data with our existing dataset.
        Returns notices in the CSV but NOT in our current data.
        """
        all_bulk = self.load_all_years(
            from_year=from_year,
            to_year=to_year,
            notice_type=notice_type,
            test_mode=test_mode,
        )

        missing = [
            n for n in all_bulk
            if n.get("tender_id") and n["tender_id"] not in existing_ids
        ]

        logger.info(
            f"Bulk: {len(all_bulk)} matches total, "
            f"{len(missing)} not in existing dataset"
        )
        return missing
