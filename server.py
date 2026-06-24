"""
NIST Chemistry WebBook MCP Server
Provides thermochemical and thermophysical data for chemical compounds
by scraping webbook.nist.gov (no official API exists).
"""

import json
import re
import sys
from typing import Optional
from enum import Enum

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, ConfigDict
from mcp.server.fastmcp import FastMCP

# ─── Constants ────────────────────────────────────────────────────────────────

BASE_URL = "https://webbook.nist.gov"
CBOOK_URL = f"{BASE_URL}/cgi/cbook.cgi"
FLUID_URL = f"{BASE_URL}/cgi/fluid.cgi"
SEARCH_TIMEOUT = 20.0

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; NIST-MCP-Server/1.0; "
        "ChemE research tool; respectful scraper)"
    )
}

# Fluid IDs used by NIST thermophysical properties endpoint
FLUID_IDS = {
    "water": "Water", "h2o": "Water",
    "nitrogen": "Nitrogen", "n2": "Nitrogen",
    "hydrogen": "Hydrogen", "h2": "Hydrogen",
    "oxygen": "Oxygen", "o2": "Oxygen",
    "carbon dioxide": "CarbonDioxide", "co2": "CarbonDioxide",
    "carbon monoxide": "CarbonMonoxide", "co": "CarbonMonoxide",
    "methane": "Methane", "ch4": "Methane",
    "ethane": "Ethane", "c2h6": "Ethane",
    "propane": "Propane", "c3h8": "Propane",
    "butane": "Butane",
    "pentane": "Pentane",
    "hexane": "Hexane",
    "heptane": "Heptane",
    "octane": "Octane",
    "ammonia": "Ammonia", "nh3": "Ammonia",
    "methanol": "Methanol",
    "ethanol": "Ethanol",
    "benzene": "Benzene",
    "toluene": "Toluene",
    "argon": "Argon", "ar": "Argon",
    "helium": "Helium", "he": "Helium",
    "hydrogen sulfide": "HydrogenSulfide", "h2s": "HydrogenSulfide",
    "sulfur dioxide": "SulfurDioxide", "so2": "SulfurDioxide",
    "cyclohexane": "Cyclohexane",
    "acetone": "Acetone",
}

# ─── Server init ──────────────────────────────────────────────────────────────

mcp = FastMCP("nist_webbook_mcp")

# ─── Shared HTTP helpers ──────────────────────────────────────────────────────

async def _get(url: str, params: dict) -> httpx.Response:
    """Shared async GET with timeout and headers."""
    async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT, follow_redirects=True) as client:
        return await client.get(url, params=params, headers=HEADERS)


def _handle_http_error(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        if e.response.status_code == 404:
            return "Error: Compound not found on NIST WebBook."
        if e.response.status_code == 429:
            return "Error: Rate limited by NIST. Please wait a moment before retrying."
        return f"Error: NIST returned HTTP {e.response.status_code}."
    if isinstance(e, httpx.TimeoutException):
        return "Error: Request to NIST timed out. Try again in a moment."
    return f"Error: {type(e).__name__}: {e}"


def _parse_table_rows(table) -> list[dict]:
    """Parse an HTML table into a list of row dicts."""
    rows = []
    headers = [th.get_text(strip=True) for th in table.find_all("th")]
    for tr in table.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if cells and len(cells) == len(headers):
            rows.append(dict(zip(headers, cells)))
    return rows


def _extract_shomate(text: str) -> Optional[dict]:
    """Extract Shomate equation coefficients (A–H) from page text."""
    pattern = r"A\s*=\s*([\-\d.]+).*?B\s*=\s*([\-\d.]+).*?C\s*=\s*([\-\d.]+).*?D\s*=\s*([\-\d.]+).*?E\s*=\s*([\-\d.]+).*?F\s*=\s*([\-\d.]+).*?G\s*=\s*([\-\d.]+).*?H\s*=\s*([\-\d.]+)"
    m = re.search(pattern, text, re.DOTALL)
    if m:
        return {k: float(v) for k, v in zip("ABCDEFGH", m.groups())}
    return None


# ─── Input models ─────────────────────────────────────────────────────────────

class ResponseFormat(str, Enum):
    MARKDOWN = "markdown"
    JSON = "json"


class CompoundSearchInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    compound: str = Field(
        ...,
        description="Compound name, formula, or CAS number (e.g. 'water', 'H2O', '7732-18-5')",
        min_length=1, max_length=200,
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="'markdown' for readable output, 'json' for structured data",
    )


class ThermophysicalInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    compound: str = Field(
        ...,
        description=(
            "Fluid name or common formula for high-accuracy thermophysical data. "
            "Supported: water, methane, ethane, propane, CO2, nitrogen, oxygen, ammonia, "
            "hydrogen, helium, argon, benzene, toluene, hexane, heptane, octane, etc."
        ),
        min_length=1, max_length=100,
    )
    T_min: float = Field(
        default=298.15,
        description="Minimum temperature in Kelvin (e.g. 298.15)",
        ge=1.0, le=10000.0,
    )
    T_max: float = Field(
        default=500.0,
        description="Maximum temperature in Kelvin (e.g. 500.0)",
        ge=1.0, le=10000.0,
    )
    pressure_MPa: float = Field(
        default=0.101325,
        description="Pressure in MPa (default 0.101325 = 1 atm)",
        gt=0.0, le=1000.0,
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="'markdown' for readable output, 'json' for structured data",
    )


class SaturationInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    compound: str = Field(
        ...,
        description="Fluid name (e.g. 'water', 'methane', 'propane')",
        min_length=1, max_length=100,
    )
    T_min: float = Field(
        default=273.15,
        description="Minimum temperature in Kelvin",
        ge=1.0, le=5000.0,
    )
    T_max: float = Field(
        default=373.15,
        description="Maximum temperature in Kelvin",
        ge=1.0, le=5000.0,
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="'markdown' for readable output, 'json' for structured data",
    )


# ─── Tool: search_compound ────────────────────────────────────────────────────

@mcp.tool(
    name="nist_search_compound",
    annotations={
        "title": "Search NIST WebBook for a Chemical Compound",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def nist_search_compound(params: CompoundSearchInput) -> str:
    """Search the NIST Chemistry WebBook for a compound and return its key thermochemical data.

    Returns thermochemical properties including:
    - Molecular formula and weight
    - Standard enthalpy of formation (gas and liquid phases)
    - Standard entropy
    - Heat capacity (Cp) at 298 K
    - Normal boiling point and melting point
    - Critical constants (Tc, Pc, Vc)
    - Antoine equation parameters (if available)
    - Shomate equation coefficients (if available)

    Args:
        params (CompoundSearchInput):
            compound (str): Name, formula, or CAS number of the compound.
            response_format (str): 'markdown' or 'json'.

    Returns:
        str: Formatted thermochemical data or error message.
    """
    query = params.compound.strip()

    # Determine search parameter: CAS (digits + dashes) vs name/formula
    cas_pattern = re.compile(r"^\d{1,7}-\d{2}-\d$")
    if cas_pattern.match(query):
        search_params = {"ID": query, "Units": "SI", "cGC": "on", "cTher": "on",
                         "cIE": "on", "cTP": "on", "cPC": "on"}
    else:
        search_params = {"Name": query, "Units": "SI", "cGC": "on", "cTher": "on",
                         "cIE": "on", "cTP": "on", "cPC": "on"}

    try:
        resp = await _get(CBOOK_URL, search_params)
        resp.raise_for_status()
    except Exception as e:
        return _handle_http_error(e)

    soup = BeautifulSoup(resp.text, "html.parser")
    result: dict = {"query": query, "source": "NIST Chemistry WebBook"}

    # ── Check for disambiguation / search results list ──
    ol = soup.find("ol")
    if ol and not soup.find("h1", string=re.compile(r"^\d")):
        items = [li.get_text(strip=True) for li in ol.find_all("li")]
        if items:
            if params.response_format == ResponseFormat.JSON:
                return json.dumps({"matches": items[:10], "note": "Multiple results — refine query."}, indent=2)
            lines = ["## Multiple Matches Found\n",
                     f"Your search for **{query}** returned multiple results. Please refine:\n"]
            for i, it in enumerate(items[:10], 1):
                lines.append(f"{i}. {it}")
            return "\n".join(lines)

    # ── Extract compound name from h1 ──
    h1 = soup.find("h1")
    if h1:
        result["name"] = h1.get_text(strip=True)

    # ── Molecular formula ──
    formula_tag = soup.find("li", string=re.compile(r"Formula"))
    if formula_tag:
        result["formula"] = formula_tag.get_text(strip=True).replace("Formula:", "").strip()

    # ── Molecular weight ──
    mw_tag = soup.find("li", string=re.compile(r"Molecular weight"))
    if mw_tag:
        result["molecular_weight"] = mw_tag.get_text(strip=True).replace("Molecular weight:", "").strip()

    # ── CAS ──
    cas_tag = soup.find("li", string=re.compile(r"CAS Registry Number"))
    if cas_tag:
        result["cas"] = cas_tag.get_text(strip=True).replace("CAS Registry Number:", "").strip()

    # ── Thermochemical data tables ──
    thermo_data = {}
    for h2 in soup.find_all(["h2", "h3"]):
        section = h2.get_text(strip=True)
        table = h2.find_next_sibling("table")
        if table:
            rows = _parse_table_rows(table)
            if rows:
                thermo_data[section] = rows

    if thermo_data:
        result["thermochemical_data"] = thermo_data

    # ── Shomate coefficients from page text ──
    page_text = soup.get_text()
    shomate = _extract_shomate(page_text)
    if shomate:
        result["shomate_equation"] = {
            "coefficients": shomate,
            "note": "Cp°(T) = A + B*t + C*t² + D*t³ + E/t²  [t = T(K)/1000, Cp in J/mol·K]",
            "H°": "H°(T)−H°(298.15) = A*t + B*t²/2 + C*t³/3 + D*t⁴/4 − E/t + F − H  [kJ/mol]",
            "S°": "S°(T) = A*ln(t) + B*t + C*t²/2 + D*t³/3 − E/(2t²) + G  [J/mol·K]",
        }

    # ── Critical constants ──
    crit = {}
    for match in re.finditer(r"Critical temperature[:\s]+([\d.]+)\s*K", page_text):
        crit["Tc_K"] = float(match.group(1))
    for match in re.finditer(r"Critical pressure[:\s]+([\d.]+)\s*MPa", page_text):
        crit["Pc_MPa"] = float(match.group(1))
    for match in re.finditer(r"Critical volume[:\s]+([\d.]+)\s*", page_text):
        crit["Vc"] = match.group(1)
    if crit:
        result["critical_constants"] = crit

    # ── Format output ──
    if params.response_format == ResponseFormat.JSON:
        return json.dumps(result, indent=2)

    # Markdown output
    lines = []
    name = result.get("name", query)
    lines.append(f"# {name}")
    lines.append(f"**Source:** NIST Chemistry WebBook\n")

    if "formula" in result:
        lines.append(f"- **Formula:** {result['formula']}")
    if "molecular_weight" in result:
        lines.append(f"- **Molecular Weight:** {result['molecular_weight']}")
    if "cas" in result:
        lines.append(f"- **CAS Number:** {result['cas']}")

    if "critical_constants" in result:
        lines.append("\n## Critical Constants")
        for k, v in result["critical_constants"].items():
            lines.append(f"- **{k}:** {v}")

    if "shomate_equation" in result:
        sh = result["shomate_equation"]
        lines.append("\n## Shomate Equation Coefficients")
        for k, v in sh["coefficients"].items():
            lines.append(f"- {k} = {v}")
        lines.append(f"\n*{sh['note']}*")
        lines.append(f"*{sh['H°']}*")
        lines.append(f"*{sh['S°']}*")

    if "thermochemical_data" in result:
        for section, rows in result["thermochemical_data"].items():
            lines.append(f"\n## {section}")
            if rows:
                headers = list(rows[0].keys())
                lines.append("| " + " | ".join(headers) + " |")
                lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
                for row in rows[:20]:
                    lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")

    if len(lines) <= 5:
        return (
            f"Found the page for **{name}** but could not extract structured data. "
            f"Visit: {BASE_URL}/cgi/cbook.cgi?Name={query.replace(' ', '+')}&Units=SI"
        )

    return "\n".join(lines)


# ─── Tool: get_thermophysical_properties ─────────────────────────────────────

@mcp.tool(
    name="nist_get_thermophysical",
    annotations={
        "title": "Get High-Accuracy Thermophysical Properties of a Fluid",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def nist_get_thermophysical(params: ThermophysicalInput) -> str:
    """Get isobaric thermophysical properties of a fluid over a temperature range from NIST.

    Returns high-accuracy properties including:
    - Density (kg/m³)
    - Cp and Cv (J/mol·K)
    - Enthalpy (kJ/mol)
    - Entropy (J/mol·K)
    - Internal energy (kJ/mol)
    - Speed of sound (m/s)
    - Viscosity (µPa·s)
    - Thermal conductivity (W/m·K)
    - Phase (liquid/vapor/supercritical)

    Args:
        params (ThermophysicalInput):
            compound (str): Fluid name (e.g. 'water', 'methane', 'CO2').
            T_min (float): Minimum temperature in Kelvin.
            T_max (float): Maximum temperature in Kelvin.
            pressure_MPa (float): Pressure in MPa (default 0.101325 = 1 atm).
            response_format (str): 'markdown' or 'json'.

    Returns:
        str: Table of thermophysical properties or error message.
    """
    compound_key = params.compound.strip().lower()

    # Resolve fluid name
    fluid_id = FLUID_IDS.get(compound_key)
    if not fluid_id:
        # Try partial match
        for k, v in FLUID_IDS.items():
            if compound_key in k or k in compound_key:
                fluid_id = v
                break

    if not fluid_id:
        supported = sorted(set(FLUID_IDS.values()))
        return (
            f"Error: '{params.compound}' is not in the supported fluid list for thermophysical data.\n"
            f"Supported fluids: {', '.join(supported[:30])}...\n"
            f"For other compounds, use nist_search_compound instead."
        )

    fluid_params = {
        "Action": "Load",
        "ID": fluid_id,
        "Type": "IsoBar",
        "Digits": "5",
        "THigh": str(params.T_max),
        "TLow": str(params.T_min),
        "TInc": str(max(1.0, (params.T_max - params.T_min) / 20)),
        "RefState": "DEF",
        "TUnit": "K",
        "PUnit": "MPa",
        "DUnit": "kg/m3",
        "HUnit": "kJ/mol",
        "WUnit": "m/s",
        "VisUnit": "uPa*s",
        "STUnit": "N/m",
        "P": str(params.pressure_MPa),
    }

    try:
        resp = await _get(FLUID_URL, fluid_params)
        resp.raise_for_status()
    except Exception as e:
        return _handle_http_error(e)

    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table")

    if not table:
        return (
            f"Error: No data table returned for {params.compound}. "
            f"The requested T range ({params.T_min}–{params.T_max} K) may be outside "
            f"the valid range for this fluid, or the pressure ({params.pressure_MPa} MPa) "
            f"may be above the fluid's critical pressure for that range."
        )

    rows = _parse_table_rows(table)
    if not rows:
        return "Error: Could not parse thermophysical data table from NIST."

    result = {
        "compound": params.compound,
        "fluid_id": fluid_id,
        "T_range_K": [params.T_min, params.T_max],
        "pressure_MPa": params.pressure_MPa,
        "source": "NIST WebBook Thermophysical Fluids",
        "data": rows,
    }

    if params.response_format == ResponseFormat.JSON:
        return json.dumps(result, indent=2)

    # Markdown table
    lines = [
        f"# Thermophysical Properties: {params.compound.title()}",
        f"**Pressure:** {params.pressure_MPa} MPa  |  "
        f"**T range:** {params.T_min}–{params.T_max} K  |  "
        f"**Source:** NIST WebBook\n",
    ]
    if rows:
        headers = list(rows[0].keys())
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
        for row in rows:
            lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")

    return "\n".join(lines)


# ─── Tool: get_saturation_properties ─────────────────────────────────────────

@mcp.tool(
    name="nist_get_saturation",
    annotations={
        "title": "Get Saturation Curve Properties (Vapor Pressure, Liquid/Vapor Density)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def nist_get_saturation(params: SaturationInput) -> str:
    """Get saturation properties (vapor pressure curve) for a fluid from NIST.

    Returns properties along the saturation curve including:
    - Saturation temperature (K)
    - Saturation pressure (MPa)
    - Liquid density (kg/m³)
    - Vapor density (kg/m³)
    - Liquid enthalpy (kJ/mol)
    - Vapor enthalpy (kJ/mol)
    - Latent heat of vaporization (kJ/mol)
    - Surface tension (N/m)

    Useful for: distillation design, heat exchanger design (condensers/evaporators),
    vapor-liquid equilibrium calculations, Antoine equation validation.

    Args:
        params (SaturationInput):
            compound (str): Fluid name (e.g. 'water', 'propane').
            T_min (float): Lower bound temperature in Kelvin.
            T_max (float): Upper bound temperature in Kelvin.
            response_format (str): 'markdown' or 'json'.

    Returns:
        str: Saturation properties table or error message.
    """
    compound_key = params.compound.strip().lower()
    fluid_id = FLUID_IDS.get(compound_key)
    if not fluid_id:
        for k, v in FLUID_IDS.items():
            if compound_key in k or k in compound_key:
                fluid_id = v
                break

    if not fluid_id:
        supported = sorted(set(FLUID_IDS.values()))
        return (
            f"Error: '{params.compound}' not found in supported fluid list.\n"
            f"Supported: {', '.join(supported[:30])}..."
        )

    sat_params = {
        "Action": "Load",
        "ID": fluid_id,
        "Type": "SatT",
        "Digits": "5",
        "THigh": str(params.T_max),
        "TLow": str(params.T_min),
        "TInc": str(max(1.0, (params.T_max - params.T_min) / 20)),
        "RefState": "DEF",
        "TUnit": "K",
        "PUnit": "MPa",
        "DUnit": "kg/m3",
        "HUnit": "kJ/mol",
        "WUnit": "m/s",
        "VisUnit": "uPa*s",
        "STUnit": "N/m",
    }

    try:
        resp = await _get(FLUID_URL, sat_params)
        resp.raise_for_status()
    except Exception as e:
        return _handle_http_error(e)

    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table")

    if not table:
        return (
            f"Error: No saturation data returned for {params.compound} in range "
            f"{params.T_min}–{params.T_max} K. The range may be outside the fluid's "
            f"saturation curve (check triple point and critical temperature)."
        )

    rows = _parse_table_rows(table)
    if not rows:
        return "Error: Could not parse saturation table from NIST."

    # Compute latent heat if liquid/vapor enthalpy columns are present
    for row in rows:
        h_liq = row.get("Enthalpy (l) (kJ/mol)")
        h_vap = row.get("Enthalpy (v) (kJ/mol)")
        if h_liq and h_vap:
            try:
                row["ΔHvap (kJ/mol)"] = f"{float(h_vap) - float(h_liq):.4f}"
            except ValueError:
                pass

    result = {
        "compound": params.compound,
        "fluid_id": fluid_id,
        "T_range_K": [params.T_min, params.T_max],
        "source": "NIST WebBook Saturation Properties",
        "data": rows,
    }

    if params.response_format == ResponseFormat.JSON:
        return json.dumps(result, indent=2)

    lines = [
        f"# Saturation Properties: {params.compound.title()}",
        f"**T range:** {params.T_min}–{params.T_max} K  |  **Source:** NIST WebBook\n",
    ]
    if rows:
        headers = list(rows[0].keys())
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
        for row in rows:
            lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")

    return "\n".join(lines)


# ─── Tool: list_supported_fluids ─────────────────────────────────────────────

@mcp.tool(
    name="nist_list_supported_fluids",
    annotations={
        "title": "List Fluids Supported for High-Accuracy Thermophysical Data",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def nist_list_supported_fluids() -> str:
    """List all fluids available for high-accuracy thermophysical and saturation data.

    These fluids are supported by nist_get_thermophysical and nist_get_saturation.
    For other compounds (thermochemical data only), use nist_search_compound.

    Returns:
        str: Alphabetical list of supported fluid names and their aliases.
    """
    unique = {}
    for alias, fluid_id in sorted(FLUID_IDS.items()):
        if fluid_id not in unique:
            unique[fluid_id] = []
        if alias != fluid_id.lower():
            unique[fluid_id].append(alias)

    lines = ["# Supported Fluids for Thermophysical Data\n",
             "Use any of these names (or listed aliases) with `nist_get_thermophysical` "
             "or `nist_get_saturation`.\n",
             "| Fluid | Aliases |",
             "| --- | --- |"]
    for fluid_id, aliases in sorted(unique.items()):
        lines.append(f"| {fluid_id} | {', '.join(aliases) if aliases else '—'} |")

    lines.append(
        "\n*For compounds not in this list, use `nist_search_compound` to retrieve "
        "thermochemical data (enthalpy of formation, Shomate coefficients, etc.).*"
    )
    return "\n".join(lines)


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os
    if "--http" in sys.argv:
        port = int(os.environ.get("PORT", 8000))
        # Set host/port via settings — works across all FastMCP versions
        # because mcp.run() only reliably accepts 'transport'
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = port
        print(f"Starting NIST WebBook MCP server on HTTP port {port}...", file=sys.stderr)
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
