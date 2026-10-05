# Audit of the 2025 result tables: the numbers

Written by `audit/01_audit_tables.py`. Do not edit by hand; rerun the script.

## Every table

| distance | file | kind | rows | blank_rows | blank_pct | duplicate_ids | ids_with_space | ids_with_underscore | longest_number |
|---|---|---|---|---|---|---|---|---|---|
| 100m | combined_all_regions_masterset.csv | combined | 1,514,532 | 158,940 | 10.49 | 0 | 0 | 1,514,532 | 22 |
| 100m | combined_desert_plains.csv | combined | 1,177,408 | 127,865 | 10.86 | 0 | 1,177,408 | 0 | 22 |
| 100m | combined_semiaridprairie_plains.csv | combined | 337,124 | 31,075 | 9.22 | 0 | 337,124 | 0 | 19 |
| 100m | hydrocarbons_Deserts_100m.csv | region | 196,823 | 29,797 | 15.14 | 0 | 196,823 | 0 | 18 |
| 100m | hydrocarbons_Plains_100m.csv | region | 980,585 | 98,068 | 10 | 0 | 980,585 | 0 | 23 |
| 100m | hydrocarbons_SemiAridPlains_100m.csv | region | 46,257 | 8,002 | 17.3 | 0 | 46,257 | 0 | 19 |
| 100m | hydrocarbons_SemiAridPrairies_100m.csv | region | 290,867 | 23,073 | 7.93 | 0 | 290,867 | 0 | 19 |
| 250m | combined_hydrocarbons.csv | combined | 417,354 | 0 | 0 | 0 | 0 | 417,354 | 22 |
| 250m | hydrocarbon_liquids_250m_masterdataset.csv | combined | 559,411 | 0 | 0 | 0 | 0 | 559,411 | 22 |
| 250m | hydrocarbons_Deserts_250m.csv | region | 63,486 | 0 | 0 | 0 | 0 | 63,486 | 19 |
| 250m | hydrocarbons_Plains_250m.csv | region | 341,736 | 0 | 0 | 0 | 0 | 341,736 | 23 |
| 250m | hydrocarbons_SemiAridPlains_250m.csv | region | 12,132 | 0 | 0 | 0 | 0 | 12,132 | 18 |
| 250m | hydrocarbons_SemiAridPrairiesEco_250m.csv | region | 142,057 | 0 | 0 | 0 | 0 | 142,057 | 22 |
| 500m | combined_hydrocarbons_500m_masterdatset.csv | combined | 950,050 | 0 | 0 | 0 | 0 | 950,050 | 19 |
| 500m | combined_hydrocarbons_exclduing_semiaridprairies.csv | combined | 743,113 | 0 | 0 | 0 | 0 | 743,113 | 19 |
| 500m | hydrocarbons_Deserts_500m_diameter_eco.csv | region | 111,905 | 0 | 0 | 0 | 0 | 111,905 | 19 |
| 500m | hydrocarbons_Plains_500m.csv | region | 615,685 | 0 | 0 | 0 | 0 | 615,685 | 23 |
| 500m | hydrocarbons_SemiAridPlains_500m.csv | region | 15,523 | 0 | 0 | 0 | 0 | 15,523 | 19 |
| 500m | hydrocarbons_SemiAridPrairies_500m.csv | region | 206,937 | 0 | 0 | 0 | 0 | 206,937 | 23 |

`longest_number` is the most characters used to write one NDVI value. Shorter numbers in a
combined table mean the values were rounded when it was saved, which makes the file smaller
without losing any rows.

## Combined tables against the ecoregion tables they were built from

| distance | combined | region_table | region_rows | found_in_combined | missing_from_combined | largest_ndvi_difference |
|---|---|---|---|---|---|---|
| 100m | combined_all_regions_masterset.csv | hydrocarbons_Deserts_100m.csv | 196,823 | 196,823 | 0 | 0 |
| 100m | combined_all_regions_masterset.csv | hydrocarbons_Plains_100m.csv | 980,585 | 980,585 | 0 | 9.419e-17 |
| 100m | combined_all_regions_masterset.csv | hydrocarbons_SemiAridPlains_100m.csv | 46,257 | 0 | 46,257 |  |
| 100m | combined_all_regions_masterset.csv | hydrocarbons_SemiAridPrairies_100m.csv | 290,867 | 0 | 290,867 |  |
| 100m | combined_all_regions_masterset.csv | (all region tables together) | 1,514,532 | 1,177,408 | 337,124 |  |
| 100m | combined_desert_plains.csv | hydrocarbons_Deserts_100m.csv | 196,823 | 196,823 | 0 | 0 |
| 100m | combined_desert_plains.csv | hydrocarbons_Plains_100m.csv | 980,585 | 980,585 | 0 | 9.419e-17 |
| 100m | combined_desert_plains.csv | hydrocarbons_SemiAridPlains_100m.csv | 46,257 | 0 | 46,257 |  |
| 100m | combined_desert_plains.csv | hydrocarbons_SemiAridPrairies_100m.csv | 290,867 | 0 | 290,867 |  |
| 100m | combined_desert_plains.csv | (all region tables together) | 1,514,532 | 1,177,408 | 337,124 |  |
| 100m | combined_semiaridprairie_plains.csv | hydrocarbons_Deserts_100m.csv | 196,823 | 0 | 196,823 |  |
| 100m | combined_semiaridprairie_plains.csv | hydrocarbons_Plains_100m.csv | 980,585 | 0 | 980,585 |  |
| 100m | combined_semiaridprairie_plains.csv | hydrocarbons_SemiAridPlains_100m.csv | 46,257 | 46,257 | 0 | 0 |
| 100m | combined_semiaridprairie_plains.csv | hydrocarbons_SemiAridPrairies_100m.csv | 290,867 | 290,867 | 0 | 0 |
| 100m | combined_semiaridprairie_plains.csv | (all region tables together) | 1,514,532 | 337,124 | 1,177,408 |  |
| 250m | combined_hydrocarbons.csv | hydrocarbons_Deserts_250m.csv | 63,486 | 63,486 | 0 | 0 |
| 250m | combined_hydrocarbons.csv | hydrocarbons_Plains_250m.csv | 341,736 | 341,736 | 0 | 9.942e-17 |
| 250m | combined_hydrocarbons.csv | hydrocarbons_SemiAridPlains_250m.csv | 12,132 | 12,132 | 0 | 0 |
| 250m | combined_hydrocarbons.csv | hydrocarbons_SemiAridPrairiesEco_250m.csv | 142,057 | 0 | 142,057 |  |
| 250m | combined_hydrocarbons.csv | (all region tables together) | 559,411 | 417,354 | 142,057 |  |
| 250m | hydrocarbon_liquids_250m_masterdataset.csv | hydrocarbons_Deserts_250m.csv | 63,486 | 63,486 | 0 | 0 |
| 250m | hydrocarbon_liquids_250m_masterdataset.csv | hydrocarbons_Plains_250m.csv | 341,736 | 341,736 | 0 | 9.942e-17 |
| 250m | hydrocarbon_liquids_250m_masterdataset.csv | hydrocarbons_SemiAridPlains_250m.csv | 12,132 | 12,132 | 0 | 0 |
| 250m | hydrocarbon_liquids_250m_masterdataset.csv | hydrocarbons_SemiAridPrairiesEco_250m.csv | 142,057 | 142,057 | 0 | 6.711e-17 |
| 250m | hydrocarbon_liquids_250m_masterdataset.csv | (all region tables together) | 559,411 | 559,411 | 0 |  |
| 500m | combined_hydrocarbons_500m_masterdatset.csv | hydrocarbons_Deserts_500m_diameter_eco.csv | 111,905 | 111,905 | 0 | 0 |
| 500m | combined_hydrocarbons_500m_masterdatset.csv | hydrocarbons_Plains_500m.csv | 615,685 | 615,685 | 0 | 9.324e-17 |
| 500m | combined_hydrocarbons_500m_masterdatset.csv | hydrocarbons_SemiAridPlains_500m.csv | 15,523 | 15,523 | 0 | 0 |
| 500m | combined_hydrocarbons_500m_masterdatset.csv | hydrocarbons_SemiAridPrairies_500m.csv | 206,937 | 206,937 | 0 | 4.269e-17 |
| 500m | combined_hydrocarbons_500m_masterdatset.csv | (all region tables together) | 950,050 | 950,050 | 0 |  |
| 500m | combined_hydrocarbons_exclduing_semiaridprairies.csv | hydrocarbons_Deserts_500m_diameter_eco.csv | 111,905 | 111,905 | 0 | 0 |
| 500m | combined_hydrocarbons_exclduing_semiaridprairies.csv | hydrocarbons_Plains_500m.csv | 615,685 | 615,685 | 0 | 9.324e-17 |
| 500m | combined_hydrocarbons_exclduing_semiaridprairies.csv | hydrocarbons_SemiAridPlains_500m.csv | 15,523 | 15,523 | 0 | 0 |
| 500m | combined_hydrocarbons_exclduing_semiaridprairies.csv | hydrocarbons_SemiAridPrairies_500m.csv | 206,937 | 0 | 206,937 |  |
| 500m | combined_hydrocarbons_exclduing_semiaridprairies.csv | (all region tables together) | 950,050 | 743,113 | 206,937 |  |

## Result tables against the shapefiles uploaded to Earth Engine

| distance | shapefile | shapes_in_shx | records_in_dbf_header | records_that_fit_in_file | result_table | result_rows | rows_minus_shapes |
|---|---|---|---|---|---|---|---|
| 100m | Deserts/hydrocarbon_100m_deserts_diameter.shp | 196,823 | 196,823 | 196,823 | hydrocarbons_Deserts_100m.csv | 196,823 | 0 |
| 100m | Plains/hydrocarbon_100m_plains_eco.shp | 980,585 | 980,585 | 980,585 | hydrocarbons_Plains_100m.csv | 980,585 | 0 |
| 100m | SemiAridPlains/hydrocarbon_100m_semiaridplains_eco.shp | 46,257 | 46,257 | 46,257 | hydrocarbons_SemiAridPlains_100m.csv | 46,257 | 0 |
| 100m | SemiAridPrairies/hydrocarbon_100m_semiaridprairies_eco.shp | 290,867 | 290,867 | 290,867 | hydrocarbons_SemiAridPrairies_100m.csv | 290,867 | 0 |
| 250m | Desserts/hydrocarbon250m_deserts_eco.shp | 63,486 | 63,486 | 63,486 | hydrocarbons_Deserts_250m.csv | 63,486 | 0 |
| 250m | Plains/hydrocarbon250m_plains_eco.shp | 341,736 | 341,736 | 341,736 | hydrocarbons_Plains_250m.csv | 341,736 | 0 |
| 250m | Semiaridplains/hydrocarbon250m_semiaridplains_eco.shp | 12,132 | 12,132 | 12,132 | hydrocarbons_SemiAridPlains_250m.csv | 12,132 | 0 |
| 250m | Semiaridprairies/hydrocarbon250m_semiaridprairies_eco.shp | 142,057 | 142,057 | 142,057 | hydrocarbons_SemiAridPrairiesEco_250m.csv | 142,057 | 0 |
| 500m | Desserts/hydrocarbon_desserts_500m_eco_diameter.shp | 111,905 | 111,905 | 111,905 | hydrocarbons_Deserts_500m_diameter_eco.csv | 111,905 | 0 |
| 500m | Plains/hydrocarbon_plains_500m_eco_diameter.shp | 615,685 | 615,685 | 615,685 | hydrocarbons_Plains_500m.csv | 615,685 | 0 |
| 500m | Semiaridplains/hydrocarbons_semiaridplains_500m_eco_diameter.shp | 15,523 | 15,523 | 15,523 | hydrocarbons_SemiAridPlains_500m.csv | 15,523 | 0 |
| 500m | Semiaridprairies/hydrocarbon_semiaridprairies_500m_eco_diameter.shp | 206,937 | 206,937 | 206,937 | hydrocarbons_SemiAridPrairies_500m.csv | 206,937 | 0 |

`records_that_fit_in_file` below `records_in_dbf_header` means the attribute table was cut off.

## The same ID at two distances

| region | a | b | ids_a | ids_b | ids_in_both |
|---|---|---|---|---|---|
| Deserts | 100m | 250m | 196,823 | 63,486 | 3,532 |
| Plains | 100m | 250m | 980,585 | 341,736 | 197,059 |
| SEMI-ARID Prairies | 100m | 250m | 290,867 | 142,057 | 46,508 |
| SEMIARID Plains | 100m | 250m | 46,257 | 12,132 | 227 |
| Deserts | 100m | 500m | 196,823 | 111,905 | 12,990 |
| Plains | 100m | 500m | 980,585 | 615,685 | 387,183 |
| SEMI-ARID Prairies | 100m | 500m | 290,867 | 206,937 | 63,164 |
| SEMIARID Plains | 100m | 500m | 46,257 | 15,523 | 502 |
| Deserts | 250m | 500m | 63,486 | 111,905 | 9,665 |
| Plains | 250m | 500m | 341,736 | 615,685 | 189,027 |
| SEMI-ARID Prairies | 250m | 500m | 142,057 | 206,937 | 48,481 |
| SEMIARID Plains | 250m | 500m | 12,132 | 15,523 | 417 |
