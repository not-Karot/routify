from typing import Optional, Tuple

import folium
import requests
import streamlit as st
from shapely import Point
from streamlit_folium import folium_static
from folium.plugins import MarkerCluster
import geopandas as gpd
from shapely.geometry import Polygon
import polyline

from osm_utils import get_gdfs_from_polygon, filter_data, merge_points_gdf_with_streets_edges, \
    convert_gdf_to_single_point_list
from routing import get_osrm_trip

from enum import Enum


class TransportProfile(Enum):
    CAR = ("Car", "driving", "drive", 20)  # Nome, OSRM profile, OSM network type, average speed (km/h)
    BIKE = ("Bike", "cycling", "bike", 15)
    FOOT = ("Foot", "walking", "walk", 5)

    def __init__(self, display_name, osrm_profile, osm_network, avg_speed):
        self.display_name = display_name
        self.osrm_profile = osrm_profile
        self.osm_network = osm_network
        self.avg_speed = avg_speed

    @classmethod
    def get_by_display_name(cls, name):
        for profile in cls:
            if profile.display_name == name:
                return profile
        raise ValueError(f"No TransportProfile found for name: {name}")

    @classmethod
    def get_all_osrm_profiles(cls):
        return [profile.osrm_profile for profile in cls]


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


def calculate_trip(gdf: gpd.GeoDataFrame,
                   profile: TransportProfile,
                   roundtrip: bool, base_url: str,
                   streets: list = None,
                   optimize_points: bool = False,
                   start_point: Point = None,
                   end_point: Point = None,
                   max_distance: float = 10.0) -> Tuple[Optional[gpd.GeoDataFrame], Optional[gpd.GeoDataFrame]]:
    """
    Calculate a trip route and identify uncovered points.

    Args:
        gdf: A GeoDataFrame containing points.
        profile: A TransportProfile object specifying the profile for routing.
        roundtrip: A boolean indicating whether the trip should be a roundtrip or not.
        base_url: A string containing the base URL for the OSRM API.
        streets: A list of strings specifying the street types to consider.
        optimize_points: A boolean indicating whether to optimize the number of the points.
        start_point: The starting point for the trip (optional).
        end_point: The destination point for the trip (optional).
        max_distance: The maximum distance (in meters) for a point to be considered covered by the route.

    Returns:
        A tuple containing:
        - A GeoDataFrame containing the routes of the calculated trip, or None if no routes are found.
        - A GeoDataFrame containing the uncovered points, or None if all points are covered.

    Raises:
        ValueError: If the input GeoDataFrame is empty.
        AssertionError: If the input GeoDataFrame does not have a valid CRS.
    """
    if gdf.empty:
        raise ValueError("The input GeoDataFrame is empty")

    assert gdf.crs is not None, "The input GeoDataFrame must have a valid CRS"

    # Remove index columns if present
    gdf = gdf.drop(columns=['index_left', 'index_right'], errors='ignore')

    # if optimize then join all the points with the osm streets and take a variable
    # number of points from the linestring
    if optimize_points:
        # Compute the buffered polygon from the input GeoDataFrame
        polygon = compute_polygon_buffer(gdf)

        # Get network nodes and edges within the polygon
        _, gdf_edges = get_gdfs_from_polygon(polygon, profile.osm_network)

        # Filter the edges data
        gdf_edges = gdf_edges.pipe(filter_data)

        # Merge the points GeoDataFrame with the streets edges GeoDataFrame
        gdf_streets = merge_points_gdf_with_streets_edges(points_gdf=gdf, streets_gdf=gdf_edges)

        if streets:
            gdf_streets = gdf_streets[gdf_streets['highway'].isin(streets)]

        # Convert the merged GeoDataFrame to a list of single points
        point_list = convert_gdf_to_single_point_list(gdf_streets, points_between=-1)
    else:
        point_list = [(point.y, point.x) for point in gdf.geometry]

    if start_point:
        point_list.insert(0, (start_point.y, start_point.x))
    if end_point:
        point_list.append((end_point.y, end_point.x))

    # Encode the points list to a polyline
    encoded_polyline = polyline.encode(point_list)

    # Get the trip routes using the OSRM API
    routes = get_osrm_trip(encoded_polyline,
                           profile=profile.osrm_profile,
                           roundtrip=str(roundtrip).lower(),
                           base_url=base_url)

    if isinstance(routes, requests.Response):
        st.error(f"OSRM API error: {routes.status_code} - {routes.text}")
        return None

    # Assert that routes are found
    if not routes:
        st.warning("No valid routes found")
        return None

    # Create a GeoDataFrame from the routes
    routes_gdf = gpd.GeoDataFrame(geometry=routes, crs="EPSG:4326")

    gdf = gdf.drop(columns=['index_right'], errors='ignore')
    # Use sjoin_nearest to find uncovered points
    covered_points = gpd.sjoin_nearest(gdf.to_crs("EPSG:3857"), routes_gdf.to_crs("EPSG:3857"), how="left", max_distance=max_distance)

    routes_gdf.reset_index(inplace=True)
    uncovered_points = covered_points[covered_points['index_right'].isna()]
    if not uncovered_points.empty:
        st.warning(
            f"{len(uncovered_points)} points were not covered by the calculated route (max distance: {max_distance} meters).")
        return routes_gdf, uncovered_points.to_crs(epsg=4326)
    else:
        st.success(f"All points were covered by the calculated route (max distance: {max_distance} meters).")
        return routes_gdf, None

def update_point(point_type):
    if f'{point_type}_point_coords' in st.session_state:
        coords = st.session_state[f'{point_type}_point_coords']
        st.session_state[f'{point_type}_point'] = Point(coords['lon'], coords['lat'])

def handle_map_click(lat, lon):
    return Point(lon, lat)
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


def interpolate_color(value, start_color, end_color):
    """Interpolate color from start_color to end_color based on value in [0, 1]."""
    start_color = [int(start_color[i:i + 2], 16) for i in (1, 3, 5)]
    end_color = [int(end_color[i:i + 2], 16) for i in (1, 3, 5)]
    color = [int(start + (end - start) * value) for start, end in zip(start_color, end_color)]
    return f'#{color[0]:02x}{color[1]:02x}{color[2]:02x}'
