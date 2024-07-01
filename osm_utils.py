from typing import Tuple, Union, List, Optional

import geopandas as gpd
import numpy as np
import osmnx as ox
import pandas as pd
from shapely.geometry import LineString, Polygon

highway_priority = [
    'motorway', 'trunk', 'primary', 'secondary', 'tertiary',
    'unclassified', 'residential', 'living_street', 'road',
    'motorway_link', 'trunk_link', 'primary_link', 'secondary_link',
    'tertiary_link', 'rest_area', 'crossing'
]


def get_gdfs_from_polygon(polygon: Polygon, network_type: str = 'drive') -> Tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """
    Generate nodes and edges GeoDataFrames from a given polygon and network type.

    Parameters:
    polygon (Polygon): The polygon defining the area of interest.
    network_type (str): The type of network to retrieve. Defaults to 'drive'.

    Returns:
    Tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]: A tuple containing the nodes and edges GeoDataFrames.
    """
    G = ox.graph_from_polygon(polygon, network_type=network_type)

    gdf_nodes, gdf_edges = ox.graph_to_gdfs(
        G,
        nodes=True, edges=True,
        node_geometry=True,
        fill_edge_geometry=True
    )

    gdf_nodes = gdf_nodes.to_crs(epsg=4326)
    gdf_edges = gdf_edges.to_crs(epsg=4326)

    gdf_nodes.reset_index(drop=True, inplace=True)
    gdf_edges.reset_index(drop=True, inplace=True)

    return gdf_nodes, gdf_edges


def select_highway_type(street_type: Union[str, List[str]]) -> str:
    """
    Select the most prioritized highway type from a list of street types.

    Parameters:
    street_type (Union[str, List[str]]): The street type or list of street types.

    Returns:
    str: The most prioritized highway type.
    """
    if isinstance(street_type, list):
        for highway in highway_priority:
            if highway in street_type:
                return highway
    return street_type


def select_max_value(value: Union[str, List[str]]) -> str:
    """
    Select the maximum value from a list of values.

    Parameters:
    value (Union[str, List[str]]): The value or list of values.

    Returns:
    str: The maximum value as a string.
    """
    if isinstance(value, list):
        return max(value, key=lambda x: float(x))
    return value


def filter_data(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Clean the gdf_edges GeoDataFrame.

    Parameters:
    gdf (gpd.GeoDataFrame): The GeoDataFrame to be cleaned.

    Returns:
    gpd.GeoDataFrame: The GeoDataFrame cleaned.
    """

    # the highway column might have list of values, we take only one based on priority
    gdf['highway'] = gdf['highway'].apply(select_highway_type)

    # the maxspeed column might have list of values, we take the greatest of the list
    gdf['maxspeed'] = gdf['maxspeed'].apply(select_max_value)

    gdf['maxspeed'] = pd.to_numeric(gdf['maxspeed'])

    for column in gdf.columns:
        if any(isinstance(val, list) for val in gdf[column]):
            gdf[column] = gdf[column].apply(lambda x: str(x) if isinstance(x, list) else x)
    return gdf


def merge_points_gdf_with_streets_edges(points_gdf: gpd.GeoDataFrame,
                                        streets_gdf: gpd.GeoDataFrame,
                                        how: str = 'inner',
                                        join_crs: Union[str, int] = 'EPSG:32632',
                                        output_crs: Union[str, int] = 'EPSG:4326',
                                        max_distance: int = 10,
                                        distance_col: str = 'distance') -> gpd.GeoDataFrame:
    """
    Merge points GeoDataFrame with streets edges GeoDataFrame using spatial join nearest operation.

    Parameters:
    points_gdf (gpd.GeoDataFrame): The GeoDataFrame containing points data.
    streets_gdf (gpd.GeoDataFrame): The GeoDataFrame containing streets edges data.
    how (str): The type of join to perform. Default is 'inner'.
    join_crs (Union[str, int]): The coordinate reference system to use for the join. Default is 'EPSG:32632'.
    output_crs (Union[str, int]): The coordinate reference system for the output GeoDataFrame. Default is 'EPSG:4326'.
    max_distance (int): The maximum distance for considering nearest neighbors. Default is 10.
    distance_col (str): The name of the column to store the distance values. Default is 'distance'.

    Returns:
    gpd.GeoDataFrame: The resulting GeoDataFrame after the spatial join with CRS set to the specified output CRS.
    """
    points_gdf.to_crs(join_crs, inplace=True)
    streets_gdf.to_crs(join_crs, inplace=True)

    streets_gdf = streets_gdf.drop(columns=['index_left', 'index_right'], errors='ignore')
    points_gdf = points_gdf.drop(columns=['index_left', 'index_right'], errors='ignore')

    spatial_gdf = gpd.sjoin_nearest(streets_gdf,
                                    points_gdf,
                                    how=how,
                                    max_distance=max_distance,
                                    distance_col=distance_col)
    spatial_gdf.to_crs(output_crs, inplace=True)

    return spatial_gdf

def simplify_linestring(linestring: LineString,
                        points_between: Optional[int] = None) -> List[Tuple[float, float]]:
    """
    Simplifies a LineString by reducing the number of points based on the specified points_between parameter.

    Parameters:
    linestring (LineString): The LineString object to be simplified.
    points_between (Optional[int]): The number of points to include between the start and end points.
                                    If None, a default calculation is used based on the length of the LineString.
                                    If -1, all points are returned.
                                    If 0, only the start and end points are returned.
                                    Must be non-negative or -1.

    Returns:
    List[Tuple[float, float]]: A list of tuples representing the coordinates of the simplified LineString.

    Raises:
    ValueError: If points_between is less than -1.
    """
    coords = list(linestring.coords)

    if points_between is None:
        length = linestring.length
        num_points = max(3, min(20, int(length / 1000) + 2))
    elif points_between < -1:
        raise ValueError("points_between must be non-negative or -1")
    elif points_between == -1:
        return coords
    elif points_between == 0:
        return [coords[0], coords[-1]]
    else:
        num_points = points_between + 2

    return [coords[i] for i in np.linspace(0, len(coords) - 1, num_points, dtype=int)]


def convert_gdf_to_single_point_list(gdf: gpd.GeoDataFrame,
                                     geometry_column: str = 'geometry',
                                     points_between: int = 3) -> List[Tuple[float, float]]:
    """
    Convert linestrings in a GeoDataFrame to a single list of points.

    Parameters:
    gdf (GeoDataFrame): GeoDataFrame containing linestrings.
    geometry_column (str): Name of the column containing geometries.
    points_between (int): Number of points to select between first and last for each linestring.

    Returns:
    List[Tuple[float, float]]: Single list of (lat, lon) tuples representing the points in the linestrings.
    """
    all_points = []

    for _, row in gdf.iterrows():
        linestring = row[geometry_column]
        if isinstance(linestring, LineString):
            selected_points = simplify_linestring(linestring, points_between)
            all_points.extend([(lat, lon) for lon, lat in selected_points])
    return all_points
