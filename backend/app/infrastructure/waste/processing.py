"""Deterministic Waste analytics.

Every number here is computed from the parsed official table (``WasteTable``) with plain
arithmetic.  Rules:
  * Previous-period comparisons use *exactly* the preceding calendar year; if that year is
    missing the comparison is omitted (never the "nearest" year, never zero).
  * Quantities stay in tonnes, rates in percent; percentages are rounded to 1 decimal.
  * A metric that cannot be computed reliably is ``None`` / listed in ``unavailable_metrics``.
  * No ML: see ``build_forecast_section`` for why.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from backend.app.infrastructure.waste.models import (
    AnnualPoint, AnnualSeries, CategoryRow, CategorySection, CategorySeries, DataQualitySection,
    FacilityKindSummary, FoodSection, ForecastSection, GenerationSection, Indicator,
    InfrastructureSection, QualityCheck, ServiceClass, ServicesSection, UnavailableMetric, WasteAlert,
)
from backend.app.infrastructure.waste.sources import (
    CLASS_DESCRIPTIONS, FACILITY_LABELS, FACILITY_SPECS, WasteSnapshot, WasteTable,
)

STATS = "waste_statistics"
MIN_OBSERVATIONS_FOR_ML = 48          # e.g. 4 years of monthly data; same rule as the Water module
RATE_SLACK_PP = 0.1                  # see _rate_tolerance_pp
ROUNDING_T = 500.0                    # source rounds tonnes to the nearest thousand => +/-500 t each
LARGE_STREAM_T = 500_000              # "large" waste stream for the low-recycling alert
LOW_RATE_PCT = 35.0
YOY_JUMP_PCT = 40.0
YOY_JUMP_MIN_T = 100_000


def _r1(v: Optional[float]) -> Optional[float]:
    return None if v is None else round(v, 1)


def _pct(part: Optional[float], whole: Optional[float]) -> Optional[float]:
    if part is None or whole is None or whole <= 0:
        return None
    return round(part / whole * 100.0, 1)


def _change_pct(cur: Optional[float], prev: Optional[float]) -> Optional[float]:
    if cur is None or prev is None or prev <= 0:
        return None
    return round((cur - prev) / prev * 100.0, 1)


def make_series(key: str, label: str, unit: str, values: Dict[int, Optional[float]], years: List[int],
                kind: str = "historical") -> AnnualSeries:
    """Series over every year of the table; years the source did not report stay ``None``."""
    return AnnualSeries(
        key=key, label=label, unit=unit, data_kind=kind, source_key=STATS,  # type: ignore[arg-type]
        points=[AnnualPoint(year=y, value=values.get(y)) for y in years],
    )


def latest_complete_year(table: WasteTable) -> Optional[int]:
    """Latest year in which total generated, recycled and disposed are all reported."""
    cand = [
        y for y in table.years
        if all(table.total.get(b, {}).get(y) is not None for b in ("generated", "recycled", "disposed"))
    ]
    return max(cand) if cand else None


def _val(table: WasteTable, block: str, year: int, cat: Optional[str] = None) -> Optional[float]:
    src = table.total.get(block, {}) if cat is None else table.cats.get(block, {}).get(cat, {})
    return src.get(year)


def computed_rate(rec: Optional[float], gen: Optional[float]) -> Optional[float]:
    return _pct(rec, gen)


def rate_excluding_cd(table: WasteTable, year: int) -> Optional[float]:
    """Overall recycling rate excluding construction & demolition waste (an NEA-published view)."""
    gen, rec = _val(table, "generated", year), _val(table, "recycled", year)
    cd_gen = _val(table, "generated", year, "construction_demolition")
    cd_rec = _val(table, "recycled", year, "construction_demolition")
    if None in (gen, rec, cd_gen, cd_rec) or gen - cd_gen <= 0:  # type: ignore[operator]
        return None
    return round((rec - cd_rec) / (gen - cd_gen) * 100.0, 1)  # type: ignore[operator]


# ======================================================================
# Indicators
# ======================================================================
def _indicator(table: WasteTable, key: str, label: str, block: str, year: int, unit: str,
               cat: Optional[str] = None, note: Optional[str] = None, kind: str = "latest_available") -> Indicator:
    cur = _val(table, block, year, cat)
    prev = _val(table, block, year - 1, cat)
    is_rate = unit == "%"
    ind = Indicator(
        key=key, label=label, value=cur, unit=unit, period=str(year), note=note,
        data_kind=kind, source_key=STATS,  # type: ignore[arg-type]
    )
    if cur is not None and prev is not None:
        ind.previous_value, ind.previous_period = prev, str(year - 1)
        ind.change_abs = round(cur - prev, 1) if is_rate else round(cur - prev, 0)
        ind.change_pct = None if is_rate else _change_pct(cur, prev)
    return ind


def build_kpis(table: WasteTable, year: int) -> List[Indicator]:
    gen = _val(table, "generated", year)
    rec = _val(table, "recycled", year)
    kpis = [
        _indicator(table, "total_generated", "Total waste generated", "generated", year, "tonnes"),
        _indicator(table, "total_recycled", "Total waste recycled", "recycled", year, "tonnes"),
        _indicator(table, "total_disposed", "Total waste disposed", "disposed", year, "tonnes"),
    ]
    # Overall recycling rate: value is recomputed from tonnes (1 dp); the published whole-number
    # figure is carried alongside so the UI can show both.
    rate = _indicator(table, "overall_recycling_rate", "Overall recycling rate", "rate", year, "%")
    rate.published_value = rate.value
    rate.value = computed_rate(rec, gen) if computed_rate(rec, gen) is not None else rate.value
    prev_c = computed_rate(_val(table, "recycled", year - 1), _val(table, "generated", year - 1))
    if rate.value is not None and prev_c is not None:
        rate.previous_value, rate.previous_period = prev_c, str(year - 1)
        rate.change_abs = round(rate.value - prev_c, 1)
    rate.note = "Recycled / generated, computed from tonnes. NEA publishes this rounded to a whole percentage point."
    kpis.append(rate)
    ex = rate_excluding_cd(table, year)
    ex_prev = rate_excluding_cd(table, year - 1)
    kpis.append(Indicator(
        key="recycling_rate_excl_cd", label="Recycling rate excl. construction & demolition", value=ex, unit="%",
        period=str(year), previous_value=ex_prev, previous_period=str(year - 1) if ex_prev is not None else None,
        change_abs=round(ex - ex_prev, 1) if ex is not None and ex_prev is not None else None,
        note="Computed from tonnes; C&D waste is ~99% recycled and lifts the headline rate.",
        data_kind="latest_available", source_key=STATS,
    ))
    kpis.append(_indicator(table, "food_waste_generated", "Food waste generated", "generated", year, "tonnes", cat="food"))
    return kpis


# ======================================================================
# Sections
# ======================================================================
def build_generation_section(table: WasteTable, year: Optional[int]) -> GenerationSection:
    sec = GenerationSection(latest_year=year, first_year=table.years[0] if table.years else None)
    if year is None:
        sec.limitations.append("No year with total generated, recycled and disposed all reported.")
        return sec
    sec.data_kind = "historical"
    yrs = table.years
    sec.generated = make_series("generated", "Total waste generated", "tonnes", table.total.get("generated", {}), yrs)
    sec.recycled = make_series("recycled", "Total waste recycled", "tonnes", table.total.get("recycled", {}), yrs)
    sec.disposed = make_series("disposed", "Total waste disposed", "tonnes", table.total.get("disposed", {}), yrs)
    sec.recycling_rate_published = make_series("recycling_rate_published", "Recycling rate (published)", "%", table.total.get("rate", {}), yrs)
    comp = {y: computed_rate(_val(table, "recycled", y), _val(table, "generated", y)) for y in yrs}
    sec.recycling_rate_computed = make_series("recycling_rate_computed", "Recycling rate (computed from tonnes)", "%", comp, yrs)
    excl = {y: rate_excluding_cd(table, y) for y in yrs}
    sec.recycling_rate_excl_cd = make_series("recycling_rate_excl_cd", "Recycling rate excl. construction & demolition", "%", excl, yrs)

    gen_vals = {y: v for y, v in table.total.get("generated", {}).items() if v is not None}
    if gen_vals:
        sec.peak_generated_year = max(gen_vals, key=lambda y: (gen_vals[y], y))
        sec.peak_generated_tonnes = gen_vals[sec.peak_generated_year]
        cur = gen_vals.get(year)
        sec.generated_change_since_peak_pct = _change_pct(cur, sec.peak_generated_tonnes)
    rate_vals = {y: v for y, v in table.total.get("rate", {}).items() if v is not None}
    if rate_vals:
        sec.peak_recycling_rate_year = max(rate_vals, key=lambda y: (rate_vals[y], y))
        sec.peak_recycling_rate_pct = rate_vals[sec.peak_recycling_rate_year]
    disp = {y: v for y, v in table.total.get("disposed", {}).items() if v is not None}
    sec.disposed_is_series_high = bool(len(disp) > 1 and year in disp and disp[year] >= max(disp.values()))
    sec.limitations.append("Annual national totals only; there is no monthly, regional or live waste-generation feed.")
    sec.limitations.append("Tonnes are rounded to the nearest thousand and rates to the nearest percentage point by the source.")
    return sec


def build_category_section(table: WasteTable, year: Optional[int]) -> CategorySection:
    sec = CategorySection(latest_year=year)
    cats = sorted({c for b in ("generated", "recycled", "disposed", "rate") for c in table.cats.get(b, {})})
    if year is None or not cats:
        sec.limitations.append("Waste-type breakdown unavailable.")
        return sec
    sec.data_kind = "historical"
    total_gen, total_disp = _val(table, "generated", year), _val(table, "disposed", year)
    rows: List[CategoryRow] = []
    for c in cats:
        gen, rec, disp = (_val(table, b, year, c) for b in ("generated", "recycled", "disposed"))
        prev = _val(table, "generated", year - 1, c)
        rows.append(CategoryRow(
            key=c, label=table.labels.get(c, c), generated=gen, recycled=rec, disposed=disp,
            recycling_rate_published=_val(table, "rate", year, c),
            recycling_rate_computed=computed_rate(rec, gen),
            share_of_generated_pct=_pct(gen, total_gen), share_of_disposed_pct=_pct(disp, total_disp),
            previous_generated=prev, generated_change_pct=_change_pct(gen, prev),
        ))
    rows.sort(key=lambda r: (r.generated is None, -(r.generated or 0), r.key))
    sec.rows = rows
    sec.top_disposed = [r.key for r in sorted((r for r in rows if r.disposed is not None), key=lambda r: (-(r.disposed or 0), r.key))[:5]]
    for r in rows:
        sec.series.append(CategorySeries(
            key=r.key, label=r.label,
            generated=make_series(f"{r.key}_generated", f"{r.label} generated", "tonnes", table.cats.get("generated", {}).get(r.key, {}), table.years),
            recycled=make_series(f"{r.key}_recycled", f"{r.label} recycled", "tonnes", table.cats.get("recycled", {}).get(r.key, {}), table.years),
            disposed=make_series(f"{r.key}_disposed", f"{r.label} disposed", "tonnes", table.cats.get("disposed", {}).get(r.key, {}), table.years),
            recycling_rate=make_series(f"{r.key}_rate", f"{r.label} recycling rate", "%", table.cats.get("rate", {}).get(r.key, {}), table.years),
        ))
    sec.limitations.append(
        "SingStat footnote: from 2019, wood and horticultural wastes recycled include materials sent to facilities "
        "(e.g. biomass power plants and an energy-from-waste plant) for use as fuel.")
    no_rate = [r.label for r in rows if r.recycling_rate_published is None and r.recycling_rate_computed is not None]
    if no_rate:
        sec.limitations.append(
            f"No published recycling rate for {', '.join(no_rate)} in {year} (the source reports 'na'); "
            "the computed rate (recycled / generated) is shown instead.")
    return sec


def build_food_section(table: WasteTable, year: Optional[int]) -> FoodSection:
    sec = FoodSection(latest_year=year)
    if year is None or "food" not in table.cats.get("generated", {}):
        sec.limitations.append("Food-waste rows are not present in the statistics table.")
        return sec
    sec.data_kind = "historical"
    sec.generated = _indicator(table, "food_generated", "Food waste generated", "generated", year, "tonnes", cat="food")
    sec.recycled = _indicator(table, "food_recycled", "Food waste recycled", "recycled", year, "tonnes", cat="food")
    sec.disposed = _indicator(table, "food_disposed", "Food waste disposed", "disposed", year, "tonnes", cat="food")
    sec.recycling_rate = _indicator(table, "food_recycling_rate", "Food waste recycling rate", "rate", year, "%", cat="food")
    sec.share_of_total_generated_pct = _pct(sec.generated.value, _val(table, "generated", year))
    sec.share_of_total_disposed_pct = _pct(sec.disposed.value, _val(table, "disposed", year))
    yrs = table.years
    sec.series_generated = make_series("food_generated", "Food waste generated", "tonnes", table.cats["generated"]["food"], yrs)
    sec.series_recycled = make_series("food_recycled", "Food waste recycled", "tonnes", table.cats.get("recycled", {}).get("food", {}), yrs)
    sec.series_disposed = make_series("food_disposed", "Food waste disposed", "tonnes", table.cats.get("disposed", {}).get("food", {}), yrs)
    sec.series_recycling_rate = make_series("food_rate", "Food waste recycling rate", "%", table.cats.get("rate", {}).get("food", {}), yrs)
    sec.limitations.append(
        "Food waste here is the national 'Food' row of the waste-statistics table; it is not split into "
        "household, retail or food-service waste, and it does not measure avoidable vs unavoidable food waste.")
    gen_food = {y: v for y, v in table.cats["generated"]["food"].items() if v is not None}
    ys = sorted(gen_food)
    if len(ys) >= 2 and ys[1] - ys[0] == 1:
        ch = _change_pct(gen_food[ys[1]], gen_food[ys[0]])
        if ch is not None and abs(ch) >= YOY_JUMP_PCT and gen_food[ys[0]] >= YOY_JUMP_MIN_T:
            sec.limitations.append(
                f"Food waste generated changes {ch:+.0f}% between {ys[0]} and {ys[1]}, which looks like a series break; "
                f"trends are most reliable from {ys[1]}.")
    return sec


def build_services_section(snap: WasteSnapshot) -> ServicesSection:
    sec = ServicesSection()
    coll = snap.collectors
    if coll is None:
        sec.limitations.append("Licensed-collector listing unavailable.")
        return sec
    sec.data_kind = "reference"
    sec.licensee_count = len(coll.licensees)
    sec.duplicate_records_removed = coll.duplicate_rows_removed
    sec.dataset_period = "Jan 2026 listing (data.gov.sg last updated 19 Jan 2026)"
    for key, (label, desc) in CLASS_DESCRIPTIONS.items():
        sec.classes.append(ServiceClass(key=key, label=label, description=desc,
                                        licensees=sum(1 for ks in coll.licensees.values() if key in ks)))
    sec.unrecognised_class_values = sorted(coll.unrecognised)
    sec.class_combinations = dict(sorted(coll.combinations.items(), key=lambda kv: (-kv[1], kv[0])))
    sec.limitations.append("A licensee holding several classes is counted once per class, so class counts add up to more than the licensee count.")
    sec.limitations.append("This is a licence register, not service capacity, coverage or collection activity. Contact details in the source are not ingested.")
    return sec


def build_infrastructure_section(snap: WasteSnapshot) -> InfrastructureSection:
    sec = InfrastructureSection()
    for kind, spec in FACILITY_SPECS.items():
        status = snap.facility_status.get(kind, "unavailable")
        src = next((s for s in snap.sources if s.key == spec["source"]), None)
        layer = snap.facilities.get(kind)
        summ = FacilityKindSummary(
            key=kind, label=FACILITY_LABELS[kind], status=status,  # type: ignore[arg-type]
            dataset_last_updated=spec["last_updated"],
            note=(src.error if src and src.error else ("Downloading from data.gov.sg..." if status == "loading" else "")),
        )
        if layer is not None:
            summ.count = len(layer.facilities)
            summ.invalid_records = layer.invalid
            summ.duplicate_records_removed = layer.duplicates_removed
            summ.by_name = dict(layer.by_name.most_common())
            summ.record_date_min, summ.record_date_max = layer.date_min, layer.date_max
        sec.kinds.append(summ)
    sec.total_locations = sum(k.count for k in sec.kinds)
    sec.map_available = sec.total_locations > 0
    sec.data_kind = "reference" if sec.map_available else "unavailable"
    loading = [k.label for k in sec.kinds if k.status == "loading"]
    if loading:
        sec.limitations.append(
            f"Still downloading from data.gov.sg: {', '.join(loading)}. Anonymous access allows only about 5 file downloads "
            "per minute, so the layers arrive one by one; they appear automatically (set DATA_GOV_SG_API_KEY to speed this up).")
    sec.limitations += [
        "These are static location listings published by NEA (per-record update stamps are 2017-2022). They are reference "
        "data: a listed bin, collection point or plant may have moved, closed or been replaced, and no fill level or collection activity is available.",
        "No official open dataset of landfill capacity or garbage-truck tracking exists; the disposal-site layer only lists locations.",
    ]
    return sec


def build_forecast_section(table: Optional[WasteTable]) -> ForecastSection:
    n = len([v for v in (table.total.get("generated", {}).values() if table else []) if v is not None])
    return ForecastSection(
        available=False, data_kind="unavailable", observations=n, frequency="annual",
        minimum_observations_required=MIN_OBSERVATIONS_FOR_ML,
        reason=(
            f"The only official waste time series are annual ({n} yearly observations, 2000-latest). A chronological "
            f"train/validation/test split plus a baseline comparison cannot give trustworthy error estimates on that, and "
            f"waste totals move with economic activity and one-off events (e.g. 2020). At least "
            f"{MIN_OBSERVATIONS_FOR_ML} observations (e.g. 4 years of monthly data) are required; none exists as official open data. "
            "No forecast is produced."
        ),
    )


def build_unavailable_metrics() -> List[UnavailableMetric]:
    return [
        UnavailableMetric(key="domestic_vs_non_domestic", label="Domestic vs non-domestic waste",
                          reason="Not in any machine-readable official dataset verified for this module (NEA reports the split in text on its Waste Statistics page only)."),
        UnavailableMetric(key="domestic_waste_per_capita", label="Domestic waste per capita",
                          reason="Needs a domestic waste series and a matching population series; neither was verified, so the ratio is not computed."),
        UnavailableMetric(key="landfill_capacity", label="Landfill capacity / remaining lifespan",
                          reason="Not published as an open dataset; none is shown."),
        UnavailableMetric(key="collection_activity", label="Garbage-truck tracking / live collection activity",
                          reason="No official open feed exists."),
        UnavailableMetric(key="bin_fill_levels", label="Bin fill levels",
                          reason="No official open feed exists; bin locations are static."),
        UnavailableMetric(key="forecast", label="Waste forecasts",
                          reason="Annual data only - see the forecast section."),
    ]


# ======================================================================
# Data quality
# ======================================================================
def _rate_tolerance_pp(gen: float, rec: float) -> float:
    """Percentage-point tolerance for 'published rate vs rate recomputed from tonnes', derived from
    the source rounding both tonnes to +/-500 t and the rate to +/-0.5 pp.  A further 0.1 pp of slack covers values
    sitting on a rounding boundary (e.g. 2013: 61.49% recomputed from rounded tonnes, published as 62%); the check
    exists to catch gross mismatches, not boundary effects."""
    if gen <= 0:
        return 100.0
    return RATE_SLACK_PP + 0.5 + 100.0 * ROUNDING_T * (1.0 / gen + rec / (gen * gen))


def build_data_quality(table: WasteTable) -> DataQualitySection:
    dq = DataQualitySection(duplicate_series_rows=table.duplicate_rows,
                            unparseable_cells=table.unparseable_cells, missing_cells=table.missing_cells)
    years = table.years

    fails: List[str] = []
    checked = 0
    for y in years:
        g, r, d = (_val(table, b, y) for b in ("generated", "recycled", "disposed"))
        if None in (g, r, d):
            continue
        checked += 1
        if abs(g - (r + d)) > 3 * ROUNDING_T:  # type: ignore[operator]
            fails.append(f"{y}: generated {g:,.0f} t vs recycled + disposed {r + d:,.0f} t")  # type: ignore[operator]
    dq.checks.append(QualityCheck(key="generated_equals_recycled_plus_disposed",
                                  description="Total generated = total recycled + total disposed (within source rounding)",
                                  passed=not fails and checked > 0, checked=checked, failures=fails[:10]))

    for block, label in (("generated", "generated"), ("recycled", "recycled"), ("disposed", "disposed")):
        fails, checked = [], 0
        cats = table.cats.get(block, {})
        for y in years:
            tot = _val(table, block, y)
            parts = [c.get(y) for c in cats.values()]
            if tot is None or not parts or any(p is None for p in parts):
                continue
            checked += 1
            tol = ROUNDING_T * (len(parts) + 1)
            if abs(sum(parts) - tot) > tol:  # type: ignore[arg-type]
                fails.append(f"{y}: waste types sum to {sum(parts):,.0f} t vs total {tot:,.0f} t")  # type: ignore[arg-type]
        dq.checks.append(QualityCheck(key=f"categories_sum_to_total_{block}",
                                      description=f"Waste-type rows add up to the total {label} (within source rounding)",
                                      passed=not fails and checked > 0, checked=checked, failures=fails[:10]))

    fails, checked = [], 0
    for y in years:
        g, r, pub = _val(table, "generated", y), _val(table, "recycled", y), _val(table, "rate", y)
        if None in (g, r, pub) or not g:
            continue
        checked += 1
        comp = r / g * 100.0  # type: ignore[operator]
        if abs(comp - pub) > _rate_tolerance_pp(g, r):  # type: ignore[arg-type]
            fails.append(f"{y}: published {pub:g}% vs computed {comp:.1f}%")
    dq.checks.append(QualityCheck(key="published_rate_matches_computed",
                                  description="Published overall recycling rate matches recycled / generated (within source rounding)",
                                  passed=not fails and checked > 0, checked=checked, failures=fails[:10]))

    jumps: List[Tuple[int, str]] = []
    series = [("Total generated", table.total.get("generated", {}))] + [
        (table.labels.get(c, c), v) for c, v in table.cats.get("generated", {}).items()]
    for label, vals in series:
        for y in years:
            a, b = vals.get(y - 1), vals.get(y)
            if a is None or b is None or a < YOY_JUMP_MIN_T:
                continue
            ch = _change_pct(b, a)
            if ch is not None and abs(ch) >= YOY_JUMP_PCT:
                jumps.append((y, f"{label} generated {y - 1}->{y}: {ch:+.0f}%"))
    dq.large_year_on_year_changes = [m for _, m in sorted(jumps, key=lambda t: (-t[0], t[1]))[:15]]
    return dq


# ======================================================================
# Alerts
# ======================================================================
def build_alerts(snap: WasteSnapshot, gen: GenerationSection, cats: CategorySection, dq: DataQualitySection,
                 now: datetime) -> List[WasteAlert]:
    alerts: List[WasteAlert] = []
    y = gen.latest_year
    if y is not None and gen.disposed is not None and gen.disposed_is_series_high:
        cur = next((p.value for p in gen.disposed.points if p.year == y), None)
        alerts.append(WasteAlert(
            id="disposed_series_high", severity="LOW", category="disposal", data_kind="historical",
            message=f"Waste disposed of in {y} is the highest in the series ({gen.first_year}-{y}).",
            evidence=[f"{y} disposed: {cur:,.0f} tonnes" if cur is not None else f"{y} disposed: n/a"]))
    if y is not None and gen.peak_recycling_rate_pct is not None and gen.recycling_rate_published is not None:
        cur_rate = next((p.value for p in gen.recycling_rate_published.points if p.year == y), None)
        if cur_rate is not None and gen.peak_recycling_rate_pct - cur_rate >= 5:
            alerts.append(WasteAlert(
                id="recycling_rate_below_peak", severity="MODERATE", category="recycling", data_kind="historical",
                message=(f"The overall recycling rate ({cur_rate:g}% in {y}) is "
                         f"{gen.peak_recycling_rate_pct - cur_rate:g} percentage points below its peak "
                         f"({gen.peak_recycling_rate_pct:g}% in {gen.peak_recycling_rate_year})."),
                evidence=[f"Published rate {y}: {cur_rate:g}%", f"Published peak: {gen.peak_recycling_rate_pct:g}% ({gen.peak_recycling_rate_year})"]))
    big = [r for r in cats.rows if (r.generated or 0) >= LARGE_STREAM_T and r.recycling_rate_computed is not None
           and r.recycling_rate_computed < LOW_RATE_PCT]
    if big:
        alerts.append(WasteAlert(
            id="large_streams_low_recycling", severity="LOW", category="categories", data_kind="historical",
            message=("Large waste streams with low recycling rates: "
                     + ", ".join(f"{r.label} ({r.recycling_rate_computed:g}%)" for r in big) + "."),
            evidence=[f"{r.label}: {r.generated:,.0f} t generated, {r.recycled:,.0f} t recycled ({cats.latest_year})"
                      if r.recycled is not None else f"{r.label}: {r.generated:,.0f} t generated" for r in big]))
    failed = [c for c in dq.checks if not c.passed]
    if failed:
        alerts.append(WasteAlert(
            id="data_consistency", severity="LOW", category="data_quality", data_kind="latest_available",
            message="The statistics table failed internal consistency checks; treat affected figures with caution.",
            evidence=[f"{c.key}: {c.failures[0] if c.failures else 'no comparable years'}" for c in failed]))
    if y is not None and y < now.year - 2:
        alerts.append(WasteAlert(
            id="statistics_out_of_date", severity="LOW", category="freshness", data_kind="latest_available",
            message=f"The latest complete year in the official statistics is {y}; newer figures may exist.",
            evidence=[f"Report generated {now.date().isoformat()}"]))
    degraded = [s for s in snap.sources if s.status in ("unavailable", "stale_cache")]   # 'loading' is not a failure
    if degraded:
        alerts.append(WasteAlert(
            id="source_degraded", severity="LOW", category="source", data_kind="unavailable",
            message=f"{len(degraded)} official source(s) are unavailable or served from cache.",
            evidence=[f"{s.name}: {s.status}" for s in degraded]))
    return alerts
