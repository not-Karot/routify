from typing import Optional

import folium
import streamlit as st
from streamlit_folium import folium_static
from folium.plugins import MarkerCluster
import geopandas as gpd
from shapely.geometry import Polygon
import polyline

from osm_utils import get_gdfs_from_polygon, filter_data, merge_points_gdf_with_streets_edges, \
    convert_gdf_to_single_point_list
from routing import get_osrm_trip


def compute_polygon_buffer(gdf: gpd.GeoDataFrame, buffer_distance: float = 0.01) -> Polygon:
    """
    Processes the input GeoDataFrame to create a buffered convex hull.

    This function takes an input GeoDataFrame, computes the convex hull
    of all its geometries, and then applies a buffer to the resulting polygon.

    Args:
        gdf (gpd.GeoDataFrame): The input GeoDataFrame containing geometries.
        buffer_distance (float, optional): The distance to buffer the convex hull. Defaults to 0.01.

    Returns:
        Polygon: The buffered convex hull of the geometries in the input GeoDataFrame.

    Raises:
        ValueError: If the input GeoDataFrame is empty or does not contain valid geometries.
    """
    if gdf.empty:
        raise ValueError("The input GeoDataFrame is empty")

    # Combine all geometries into a single geometry (unary union)
    combined_geometry = gdf.geometry.unary_union

    # Compute the convex hull of the combined geometry
    convex_hull = combined_geometry.convex_hull

    # Apply a buffer to the convex hull
    buffered_convex_hull = convex_hull.buffer(buffer_distance)

    if not isinstance(buffered_convex_hull, Polygon):
        raise ValueError("The processed geometry is not a valid Polygon")

    return buffered_convex_hull


def calculate_trip(gdf: gpd.GeoDataFrame, network_type: str = "drive") -> Optional[gpd.GeoDataFrame]:
    """
    Calculate a trip based on the input GeoDataFrame and network type.

    This function processes the input GeoDataFrame to create a buffered polygon,
    retrieves network nodes and edges within that polygon, filters the edges,
    merges the points with the streets, and calculates a trip using the OSRM API.

    Args:
        gdf (gpd.GeoDataFrame): The input GeoDataFrame containing points to calculate the trip for.
        network_type (str, optional): The type of network to use for the trip calculation. Defaults to "drive".

    Returns:
        Optional[gpd.GeoDataFrame]: A GeoDataFrame containing the calculated route segments if successful,
                                    or None if no valid route is found.

    Raises:
        ValueError: If the input GeoDataFrame is empty or invalid.
    """
    if gdf.empty:
        raise ValueError("The input GeoDataFrame is empty")

    assert gdf.crs is not None, "The input GeoDataFrame must have a valid CRS"

    # Remove index columns if present
    gdf = gdf.drop(columns=['index_left', 'index_right'], errors='ignore')

    # Compute the buffered polygon from the input GeoDataFrame
    polygon = compute_polygon_buffer(gdf)

    # Get network nodes and edges within the polygon
    gdf_nodes, gdf_edges = get_gdfs_from_polygon(polygon, network_type)

    # Filter the edges data
    gdf_edges = gdf_edges.pipe(filter_data)

    # Merge the points GeoDataFrame with the streets edges GeoDataFrame
    gdf_streets = merge_points_gdf_with_streets_edges(points_gdf=gdf, streets_gdf=gdf_edges)

    # Convert the merged GeoDataFrame to a list of single points
    point_list = convert_gdf_to_single_point_list(gdf_streets, points_between=-1)

    # Encode the points list to a polyline
    encoded_polyline = polyline.encode(point_list)

    # Get the trip routes using the OSRM API
    routes = get_osrm_trip(encoded_polyline)

    # Assert that routes are found
    assert routes is not None, "No valid routes found"

    # Create a GeoDataFrame from the routes
    routes_gdf = gpd.GeoDataFrame(geometry=routes)
    routes_gdf.reset_index(inplace=True)

    return routes_gdf


def display_map(gdf):
    # Display the map
    st.subheader("Map Visualization")

    # Create a Folium map
    m = folium.Map(location=[gdf.geometry.y.mean(),
                             gdf.geometry.x.mean()],
                   zoom_start=10)

    # Create a MarkerCluster
    marker_cluster = MarkerCluster().add_to(m)

    # Add points to the map with popup information
    for idx, row in gdf.iterrows():
        # Create popup content
        popup_content = "<br>".join([f"{col}: {val}" for col, val in row.items() if col != 'geometry'])

        # Add marker
        folium.Marker(
            location=[row.geometry.y, row.geometry.x],
            popup=folium.Popup(popup_content, max_width=300),
            tooltip=f"Point {idx}"
        ).add_to(marker_cluster)

    # Fit the map to the bounds of the data
    m.fit_bounds(m.get_bounds())

    # Display the map in Streamlit
    folium_static(m)

    # Display GeoDataFrame as a table
    st.subheader("Data Table")
    st.dataframe(gdf.drop(columns=['geometry'], errors="ignore"))
