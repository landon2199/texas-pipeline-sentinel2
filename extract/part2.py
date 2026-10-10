"""Part 2: measure every zone in Earth Engine with the methods of analysis plan v1.4, Section 5.

Sentinel-2 surface reflectance (harmonized, so 2018-2026 stays consistent), with:
  - clouds and cloud shadows masked by Cloud Score+ (cs_cdf of 0.6 or more is kept; Pasquarella et al. 2023), and
    saturated, dark and snow pixels by the scene classification;
  - water kept out at four levels: water in that image (scene class 6, or MNDWI above 0), water more than 5% of the time
    since 1984 (JRC Global Surface Water) or NLCD open water, a 20 m shoreline buffer around both, and pixel counts so
    zones with too little land can be reported as not measurable;
  - seven indices computed in every image: NDVI, NDMI (B8A/B11), SAVI, MNDWI, NDRE, S2REP and BSI;
  - values split by NLCD land cover class.
Two products per spring: the image-by-image values (the main measure, paired ring by ring in Part 3; per_pass joins
the overlapping tiles of one satellite pass) and the spring composite (per pixel median and 90th percentile). Fixed values per zone (terrain, drainage, soil, water) come once.
"""
import ee

S2 = "COPERNICUS/S2_SR_HARMONIZED"
CLOUD_SCORE = "GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED"
CS_MIN = 0.6
SCENE_CLOUD_MAX = 60      # plan 5.2: scenes over 60% cloud are skipped; pixel masks do the rest
SCALE = 20                # meters: the native size of B5-B7, B8A and B11; 10 m gave the same answers (r >= 0.999)
TILE_SCALE = 1            # the per-image measure fits in memory at 1, which cost a quarter of tileScale 4 (2026-10-06 test)
INDICES = ["NDVI", "NDMI", "SAVI", "MNDWI", "NDRE", "S2REP", "BSI"]
SPRING = ("03-01", "05-01")


def nlcd():
    return ee.ImageCollection("USGS/NLCD_RELEASES/2021_REL/NLCD").first().select("landcover")


def static_water():
    occurrence = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence").unmask(0)
    return occurrence.gt(5).Or(nlcd().eq(11))


def near_static_water():
    """Rivers and lakes plus a 20 m shoreline. Built from fixed maps, so it is the same for every image."""
    return static_water().focalMax(20, "circle", "meters")


def prepare(img):
    """Mask clouds, shadows, snow, saturation and water (with a 20 m shoreline), then compute the seven indices."""
    s = img.select(["B2", "B3", "B4", "B5", "B6", "B7", "B8", "B8A", "B11", "B12"]).divide(10000)
    scl = img.select("SCL")
    clear = img.select("cs_cdf").gte(CS_MIN).And(scl.neq(1)).And(scl.neq(2)).And(scl.neq(11))
    mndwi = s.normalizedDifference(["B3", "B11"]).rename("MNDWI")
    water_today = scl.eq(6).Or(mndwi.gt(0))          # water in this image, removed pixel by pixel
    keep = clear.And(water_today.Not()).And(near_static_water().Not())
    b = {k: s.select(k) for k in ("B2", "B4", "B5", "B6", "B7", "B8", "B8A", "B11")}
    out = ee.Image.cat([
        s.normalizedDifference(["B8", "B4"]).rename("NDVI"),
        s.normalizedDifference(["B8A", "B11"]).rename("NDMI"),
        s.expression("1.5 * (N - R) / (N + R + 0.5)", {"N": b["B8"], "R": b["B4"]}).rename("SAVI"),
        mndwi,
        s.normalizedDifference(["B8A", "B5"]).rename("NDRE"),
        s.expression("705 + 35 * (((R + E3) / 2 - E1) / (E2 - E1))",
                     {"R": b["B4"], "E1": b["B5"], "E2": b["B6"], "E3": b["B7"]}).rename("S2REP"),
        s.expression("((W + R) - (N + B)) / ((W + R) + (N + B))",
                     {"W": b["B11"], "R": b["B4"], "N": b["B8"], "B": b["B2"]}).rename("BSI"),
    ]).updateMask(keep)
    return out.copyProperties(img, ["system:time_start", "system:index", "SENSING_ORBIT_NUMBER", "MGRS_TILE",
                                    "MEAN_SOLAR_ZENITH_ANGLE", "MEAN_INCIDENCE_ZENITH_ANGLE_B8"])


def images_between(region, start: str, end: str):
    """Every Sentinel-2 image over the region from start up to (not including) end, masked and with the seven indices."""
    col = ee.ImageCollection(S2).filterBounds(region).filterDate(start, end).filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", SCENE_CLOUD_MAX))
    return col.linkCollection(ee.ImageCollection(CLOUD_SCORE), ["cs_cdf"]).map(prepare)


def spring_images(region, year: int):
    return images_between(region, f"{year}-{SPRING[0]}", f"{year}-{SPRING[1]}")


def _grouped(stats: ee.Reducer, n_bands: int) -> ee.Reducer:
    return stats.repeat(n_bands).group(groupField=n_bands, groupName="landcover")


def _flatten(zones_out, extra: dict, names: list[str], stat_names: list[str]):
    """One row per zone and land cover class, with a column per index and statistic."""
    def per_zone(f):
        def per_group(g):
            g = ee.Dictionary(g)
            props = {"zone_id": f.get("zone_id"), "landcover": g.get("landcover"), **extra}
            row = ee.Feature(None, props)
            for s in stat_names:
                values = ee.List(g.get(s))
                row = row.set(ee.Dictionary.fromLists([f"{n}_{s}" for n in names], values))
            return row
        return ee.FeatureCollection(ee.List(f.get("groups")).map(per_group))
    return zones_out.map(per_zone).flatten()


def _measure_each(images, zones, crs: str, footprint, extra, bands=None, scale=None):
    """Every zone's mean and pixel count in each image, by land cover class; zones fully under cloud give no row."""
    bands = bands or INDICES
    reducer = _grouped(ee.Reducer.mean().combine(ee.Reducer.count(), sharedInputs=True), len(bands))

    def one(img):
        z = zones.filterBounds(footprint(img))
        out = img.select(bands).addBands(nlcd().rename("lc")).reduceRegions(collection=z, reducer=reducer, scale=scale or SCALE,
                                                                            crs=crs, tileScale=TILE_SCALE)
        rows = _flatten(out.filter(ee.Filter.neq("groups", [])), extra(img), bands, ["mean", "count"])
        return rows.filter(ee.Filter.gt(f"{bands[0]}_count", 0))

    return images.map(one).flatten()


def _image_props(img):
    return {"date": img.date().format("YYYY-MM-dd"), "image": img.get("system:index"),
            "orbit": img.get("SENSING_ORBIT_NUMBER"), "tile": img.get("MGRS_TILE"),
            "sun_zenith": img.get("MEAN_SOLAR_ZENITH_ANGLE"), "view_zenith": img.get("MEAN_INCIDENCE_ZENITH_ANGLE_B8")}


def per_image_values(zones, region, year: int, crs: str):
    """Image by image, one row per Sentinel-2 tile. Where tiles overlap, a zone is measured twice in the same pass."""
    return _measure_each(spring_images(region, year), zones, crs, lambda img: img.geometry(), _image_props)


def lean_composite_values(zones, region, year: int, crs=None, bands=("NDVI", "NDMI")):
    """The wall-to-wall measure: one spring median composite per index, then each zone's mean and pixel count by NLCD
    land cover class. Cheaper than the image-by-image measure (one image per spring), so every segment can be measured;
    the image-by-image sample stays the main test (plan 5.4)."""
    bands = list(bands)
    if year == 0:            # 0: one composite over all nine springs (March-April 2018-2026), measured once
        col = ee.ImageCollection(spring_images(region, 2018))
        for y in range(2019, 2027):
            col = col.merge(spring_images(region, y))
        img = col.select(bands).median().addBands(nlcd().rename("lc"))
    else:
        img = spring_images(region, year).select(bands).median().addBands(nlcd().rename("lc"))
    out = img.reduceRegions(collection=zones, reducer=_grouped(ee.Reducer.mean().combine(ee.Reducer.count(), sharedInputs=True),
                                                               len(bands)), scale=SCALE, crs=crs, tileScale=4)
    rows = _flatten(out.filter(ee.Filter.neq("groups", [])), {"spring": year}, bands, ["mean", "count"])
    return rows.filter(ee.Filter.gt(f"{bands[0]}_count", 0))


def per_image_between(zones, region, start: str, end: str, crs):
    """The same image-by-image values for any date window (the spill series, plan 7.4)."""
    return _measure_each(images_between(region, start, end), zones, crs, lambda img: img.geometry(), _image_props)


def pass_mosaics(region, year: int):
    """One image per satellite pass (date and orbit): the overlapping tiles of a pass are joined, so each zone is
    measured once per pass. In the 2025 test, 29% of the tile-by-tile rows repeated a pass from a neighboring tile."""
    col = spring_images(region, year)
    col = col.map(lambda i: i.set("pass", i.date().format("YYYY-MM-dd").cat("_")
                                  .cat(ee.Number(i.get("SENSING_ORBIT_NUMBER")).format("%.0f"))))

    def one(key):
        same = col.filter(ee.Filter.eq("pass", key))
        first = ee.Image(same.first())
        return same.mosaic().set({
            "system:time_start": first.get("system:time_start"), "pass": key,
            "SENSING_ORBIT_NUMBER": first.get("SENSING_ORBIT_NUMBER"),
            "tiles": same.aggregate_array("MGRS_TILE").distinct().join(","),
            "MEAN_SOLAR_ZENITH_ANGLE": same.aggregate_mean("MEAN_SOLAR_ZENITH_ANGLE"),
            "MEAN_INCIDENCE_ZENITH_ANGLE_B8": same.aggregate_mean("MEAN_INCIDENCE_ZENITH_ANGLE_B8"),
            "footprint": same.geometry()})

    return ee.ImageCollection(col.aggregate_array("pass").distinct().map(one))


def per_pass_values(zones, region, year: int, crs: str):
    """Image by image, one row per satellite pass: the main measure without the repeats from overlapping tiles."""
    def extra(img):
        return {"date": img.date().format("YYYY-MM-dd"), "orbit": img.get("SENSING_ORBIT_NUMBER"), "tiles": img.get("tiles"),
                "sun_zenith": img.get("MEAN_SOLAR_ZENITH_ANGLE"), "view_zenith": img.get("MEAN_INCIDENCE_ZENITH_ANGLE_B8")}
    return _measure_each(pass_mosaics(region, year), zones, crs, lambda img: ee.Geometry(img.get("footprint")), extra)


def composite_values(zones, region, year: int, crs: str):
    """The second measure: per pixel spring median and 90th percentile, summarized per zone and land cover."""
    col = spring_images(region, year)
    comp = col.reduce(ee.Reducer.percentile([50, 90], ["median", "p90"]))
    bands = [f"{i}_median" for i in INDICES] + [f"{i}_p90" for i in INDICES]
    clear = col.select("NDVI").count().rename("clear_images")
    img = comp.select(bands).addBands(clear).addBands(nlcd().rename("lc"))
    stats = (ee.Reducer.mean().combine(ee.Reducer.stdDev(), sharedInputs=True)
             .combine(ee.Reducer.percentile([10, 50, 90], ["p10", "median", "p90"]), sharedInputs=True)
             .combine(ee.Reducer.count(), sharedInputs=True))
    names = bands + ["clear_images"]
    out = img.reduceRegions(collection=zones, reducer=_grouped(stats, len(names)), scale=SCALE, crs=crs, tileScale=8)
    return _flatten(out.filter(ee.Filter.neq("groups", [])), {"year": year}, names, ["mean", "median", "stdDev", "p10", "p90", "count"])


# ---- Landsat 8 and 9 land surface temperature (plan 5.1, 5.2, D6) --------------------------------------------------
LANDSAT = ["LANDSAT/LC08/C02/T1_L2", "LANDSAT/LC09/C02/T1_L2"]
LST_SCALE = 30
ST_QA_MAX_K = 3.5     # D6: pixels whose surface-temperature uncertainty (ST_QA) exceeds this are dropped: the 95th
                      # percentile of clear pixels in the Central Great Plains, spring 2025 (2,779 pixels, 62 images;
                      # median 2.13 K). A 2 K cutoff would have dropped 71% of clear pixels.
QA_BAD = 0b10111111   # QA_PIXEL bits 0-5 and 7: fill, dilated cloud, cirrus, cloud, cloud shadow, snow, water


def prepare_lst(img):
    """Landsat Collection 2 Level-2 surface temperature in degrees C, with clouds, shadows, snow, water, saturated pixels
    and uncertain retrievals masked (USGS scale: ST_B10 x 0.00341802 + 149.0 K; ST_QA x 0.01 K)."""
    keep = (img.select("QA_PIXEL").bitwiseAnd(QA_BAD).eq(0)
            .And(img.select("QA_RADSAT").eq(0))
            .And(img.select("ST_QA").multiply(0.01).lte(ST_QA_MAX_K))
            .And(near_static_water().Not()))
    lst = img.select("ST_B10").multiply(0.00341802).add(149.0).subtract(273.15).rename("LST").updateMask(keep)
    return lst.copyProperties(img, ["system:time_start", "system:index", "WRS_PATH", "WRS_ROW", "SPACECRAFT_ID"])


def landsat_spring(region, year: int):
    start, end = f"{year}-{SPRING[0]}", f"{year}-{SPRING[1]}"
    col = ee.ImageCollection(LANDSAT[0]).merge(ee.ImageCollection(LANDSAT[1]))
    return (col.filterBounds(region).filterDate(start, end).filter(ee.Filter.lt("CLOUD_COVER", SCENE_CLOUD_MAX))
            .map(prepare_lst))


def lst_values(zones, region, year: int, crs):
    """Every zone's mean surface temperature and pixel count in every clear Landsat 8/9 image, by land cover class."""
    def extra(img):
        return {"date": img.date().format("YYYY-MM-dd"), "image": img.get("system:index"), "path": img.get("WRS_PATH"),
                "row": img.get("WRS_ROW"), "spacecraft": img.get("SPACECRAFT_ID")}
    return _measure_each(landsat_spring(region, year), zones, crs, lambda img: img.geometry(), extra,
                         bands=["LST"], scale=LST_SCALE)


# ---- Fixed values, measured once per zone (plan 5.4) -----------------------------------------------------------------
def fixed_image():
    """Elevation and slope (USGS 3DEP 10 m), height above the nearest drainage and a wetness index (MERIT Hydro; Yamazaki
    et al. 2019; Beven and Kirkby 1979), surface water share (JRC occurrence over 5% or NLCD open water) and topsoil
    texture class (OpenLandMap, 0 cm; Hengl 2018)."""
    tiles = ee.ImageCollection("USGS/3DEP/10m_collection")
    dem = tiles.mosaic().setDefaultProjection(ee.Image(tiles.first()).projection()).select("elevation")
    hydro = ee.Image("MERIT/Hydro/v1_0_1")
    slope90 = ee.Terrain.slope(hydro.select("elv")).multiply(3.141592653589793 / 180).tan().max(0.001)
    twi = hydro.select("upa").multiply(1e6).divide(90).max(1).log().subtract(slope90.log())
    return ee.Image.cat([dem.rename("elevation_m"), ee.Terrain.slope(dem).rename("slope_deg"),
                         hydro.select("hnd").rename("hand_m"), twi.rename("twi"),
                         static_water().unmask(0).rename("water_share"),
                         ee.Image("OpenLandMap/SOL/SOL_TEXTURE-CLASS_USDA-TT_M/v02").select("b0").rename("soil_texture")])


FIXED = ["elevation_m", "slope_deg", "hand_m", "twi", "water_share", "soil_texture"]


def fixed_values(zones, region=None, year=None, crs=None):
    """Mean of each fixed value per zone (and the most common soil texture class), on a 30 m grid."""
    reducer = ee.Reducer.mean().combine(ee.Reducer.mode(), sharedInputs=True)
    return fixed_image().reduceRegions(collection=zones, reducer=reducer, scale=30, crs=crs, tileScale=2)


# ---- Spring drought index (plan 5.4; gridMET drought, Abatzoglou 2013) ----------------------------------------------
DROUGHT = ["pdsi", "spei90d", "spi90d"]


def drought_values(zones, region, year: int, crs=None):
    """Each zone's mean Palmer Drought Severity Index and 90-day SPEI and SPI over the spring window."""
    col = ee.ImageCollection("GRIDMET/DROUGHT").filterDate(f"{year}-{SPRING[0]}", f"{year}-{SPRING[1]}").select(DROUGHT)
    out = col.mean().reduceRegions(collection=zones, reducer=ee.Reducer.mean(), scale=4000)
    return out.map(lambda f: f.set("year", year))


def utm_crs(region) -> str:
    lon = ee.Number(region.centroid(100).coordinates().get(0)).getInfo()
    return f"EPSG:326{int((lon + 180) // 6) + 1:02d}"


def zones_from(folder: str):
    """All pieces of an uploaded zone file as one collection, and the list of pieces."""
    parts = [a["name"] for a in ee.data.listAssets({"parent": folder})["assets"]]
    return ee.FeatureCollection([ee.FeatureCollection(p) for p in parts]).flatten(), parts
