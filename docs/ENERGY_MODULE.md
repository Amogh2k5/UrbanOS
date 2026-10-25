
# UrbanOS — Energy Intelligence

## Implemented scope

The module adds `Infrastructure → Energy`, the API `GET /api/infrastructure/energy/report` (and `/sources`), source metadata, deterministic analytics and a dashboard. The dashboard labels all datasets as historical/latest-available and explicitly does not imply live grid telemetry.

## Official sources verified

1. **EMA / data.gov.sg — Peak System Demand, 2005 to Jul 2021**  
   Dataset ID `d_926d3e304c0b41e56d4cbd3304acf105`; datastore API `https://data.gov.sg/api/action/datastore_search?resource_id=d_926d3e304c0b41e56d4cbd3304acf105`; monthly; MW; January 2005–July 2021. Fields: `year`, `mth`, `peak_system_demand_mw`. Source page: https://data.gov.sg/datasets/d_926d3e304c0b41e56d4cbd3304acf105/view

2. **EMA / data.gov.sg — Total Final Energy Consumption, 2009 to 2019**  
   Dataset ID `d_500440fba49cfc69f395e6dd1df967de`; datastore API at the same endpoint with this resource ID; annual; ktoe; 2009–2019. Fields: `year`, `sector`, `energy_products`, `consumption_ktoe`. This is total final energy consumption, not electricity-only consumption. Source: https://data.gov.sg/datasets/d_500440fba49cfc69f395e6dd1df967de/view

3. **EMA / data.gov.sg — Installed Capacity of Grid-Connected Solar PV Systems by User Type**  
   Dataset ID `d_51adcf3cc50e30e25ad68c951743db69`; annual/historical; Jan 2008–Mar 2021; MWp and MWac. Fields: `year`, `residential_status`, `user_type`, `inst_cap_mwp`, `inst_cap_mwac`. Source: https://data.gov.sg/datasets/d_51adcf3cc50e30e25ad68c951743db69/view

4. **EMA / data.gov.sg — Solar PV Installations by URA Planning Region**  
   Dataset ID `d_cd4f91f7a1ebb2b7ceb1a70c0dbb706d`; annual/historical; Jan 2008–Mar 2021; installation count, kWac and percentage. Fields include `year`, `ura_planning_region`, `residential_status`, `num_solar_pv_inst`, `inst_cap_kwac`, `total_inst_cap_percent`. Source: https://data.gov.sg/datasets/d_cd4f91f7a1ebb2b7ceb1a70c0dbb706d/view

The source pages document the dataset metadata and provide the data.gov.sg datastore query pattern. Runtime code actually requests the datasets and reports source availability, record counts, and failures in the report. Runtime API access still depends on the deployment environment's network access and data.gov.sg availability. An optional `DATA_GOV_SG_API_KEY` environment variable is supported for higher rate limits; no key is hardcoded.

## Dashboard and report

- KPI cards: latest available peak demand, historical maximum peak demand, latest historical solar capacity, consumption record count.
- Monthly peak-demand history chart.
- Historical solar capacity by year.
- Consumption table by year/sector/energy product.
- Regional solar installations table.
- Source inventory with frequency, coverage, units, status and source link.
- Error, empty, partial and unavailable states.
- API report preserves source metadata and limitations.

## Forecast / ML decision

The task specification requests short-horizon ML forecasting from half-hourly system demand. The publicly accessible EMA dataset verified during this implementation is **monthly peak system demand ending July 2021**, not half-hourly telemetry. No verified, accessible half-hourly dataset was established. It would be misleading to train a short-horizon model on this data or expose a synthetic forecast, so the forecast is explicitly unavailable. Re-enable forecasting only after a valid half-hourly source is identified and tested, then use chronological splits and report metrics against a baseline.

## Not implemented due to data verification

No live/latest electricity demand, current generation mix, current generation/consumption comparison, current solar capacity, USEP, current tariffs, generation capacity/availability, transmission availability, or four-zone demand series is represented as current. These were not added because a current, directly accessible dataset and schema were not verified in this implementation. No unsupported geographic map is created.

## Tests

`tests/test_energy_processing.py` tests null/missing data handling, numeric parsing, historical periods, regional solar records, and forecast gating. Run with `pytest tests/test_energy_processing.py`. Full frontend production build and live deployment verification must be run in the target environment.
