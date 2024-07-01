import streamlit as st
import json
import geopandas as gpd

from utils import calculate_trip, display_map

st.title('Magic Trip Solver')
st.info("This app let you upload a series of Points and provides you the optimal-like trip "
        "to visit all of them at least once.")

points_file = st.file_uploader("Choose a GeoJSON file with points", type="geojson")

if points_file is not None:
    # Read the file
    points = gpd.read_file(points_file)

    if points.crs != 'EPSG:4326':
        points.to_crs('EPSG:4326', inplace=True)

    # Check if the geometry type is Point
    if not all(points.geometry.type == 'Point'):
        st.error("The uploaded GeoJSON must contain only points. Please upload a different file.")
    else:
        display_map(points)

        # Perform elaboration
        trip_gdf = calculate_trip(points)

        # Convert back to GeoJSON
        trip_geojson = trip_gdf.to_json()

        # Create a download link
        btn = st.download_button(
            label="Download elaborated GeoJSON",
            data=trip_geojson,
            file_name="trip.geojson",
            mime="application/json"
        )
else:
    st.write("Upload a GeoJSON file with points to begin.")
